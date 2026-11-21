"""The recommendation engine: answers in, 2-4 checked sentences out (brief section 6)."""
from __future__ import annotations

import logging
import re
import time

from ..config import Settings
from ..knowledge import Knowledge
from ..library import Library, Template
from ..ollama_client import OllamaClient
from . import ai
from .context import (
    AnswerError, Context, available_topics, build_context, evidence_options, parts_for, scope_options,
    segment_options, topic_fact_fields, validate_fact,
)
from .evidence import regulations_for
from .fill import fill_text, remaining_placeholders, slot_values
from .notes import adopted_future_notes, dfa_notes, future_watch_notes, gate_notes
from .select import Match, choose, mandatory_appends, select
from .validate import Segment, check_segments, context_dont_say, entry_hits

log = logging.getLogger("claimcomposer.engine")

STATUS_LINE = {"en": "Fits the checked requirements, provided the marked facts are verified.",
               "de": "Passt zu den geprüften Anforderungen, sofern die markierten Fakten belegt sind."}
DISCLAIMER = "Research prototype. Not legal advice. Human review required."
GERMAN_TAG = "German wording not yet reviewed"


def _label(lib: Library, list_name: str, value: str, lang: str = "en") -> str:
    for o in lib.questionnaire.get(list_name, []):
        if o["id"] == value:
            return o["label_de" if lang == "de" else "label_en"]
    return value


def slot_chip(t: Template, name: str, ctx: Context, lib: Library) -> dict:
    s = t.slot(name)
    chip = {"name": name, "type": s.type if s else "manual", "unit": s.unit if s else None,
            "editable": bool(s and s.source != "manual"), "options": None, "label": name}
    fields = {f["name"]: f for f in topic_fact_fields(ctx, lib, None)}
    if s:
        if s.source == "fact_field" and name in fields:
            chip["label"] = fields[name]["label_en"]
        elif s.source == "answer":
            chip["label"] = {"component": "Part covered", "excluded": "Part not included", "method": "Method or standard",
                             "year": "Reference year", "comparator": "Comparator"}.get(name, name)
        else:
            chip["label"] = f"{name} (complete outside the app)"
        opts = None
        if s.type == "choice":
            if s.options == "parts":
                opts = parts_for(ctx.domains, lib) if ctx.scope != "packaging" else lib.questionnaire["parts"]["PACKAGING"]
            elif s.options == "methods":
                opts = lib.questionnaire["topics"].get(ctx.topic, {}).get("methods", [])
            elif s.options == "comparison":
                chip["editable"] = False
            else:
                opts = lib.questionnaire["option_lists"].get(s.options or "", [])
        if opts is not None:
            chip["options"] = [{"id": o["id"], "label": o["label_de" if ctx.language == "de" else "label_en"]} for o in opts]
        if name == "comparator":
            chip["editable"] = False
            chip["label"] = "Named comparator (complete outside the app)"
    return chip


class Built:
    def __init__(self, match: Match, segments: list[Segment], values: dict, sentence: str, problems: list[str],
                 sentence_en: str, appended: list[Template]):
        self.match, self.segments, self.values, self.sentence = match, segments, values, sentence
        self.problems, self.sentence_en, self.appended = problems, sentence_en, appended


def build_one(m: Match, ctx: Context, lib: Library, kb: Knowledge, appends: list[Match], lang: str,
              overrides: dict | None = None) -> Built:
    t = m.template
    use_lang = lang if (lang == "en" or t.text_de) else "en"
    built_by_lang = {}
    for L in dict.fromkeys([use_lang, "en"]):
        values = slot_values(t, ctx, lib, L, overrides)
        segs = [Segment(fill_text(t.text(L), values), t)]
        appended = []
        for a in appends:
            at = a.template
            if t.kind == "official_info" and at.rule_ids[0] in t.rule_ids:
                continue  # the main template already is this official statement
            av = slot_values(at, ctx, lib, L, overrides)
            if fill_text(at.text(L), av).rstrip(".").lower() in segs[0].text.lower():
                continue  # the main sentence already contains this statement
            segs.append(Segment(fill_text(at.text(L), av), at))
            values = {**av, **values}
            appended.append(at)
        problems = check_segments(segs, L, ctx, lib, kb, values)
        built_by_lang[L] = (segs, values, problems, appended)
    segs, values, problems, appended = built_by_lang[use_lang]
    en_problems = built_by_lang["en"][2]
    all_problems = problems + [f"(en) {p}" for p in en_problems if use_lang != "en" and p not in problems]
    sentence = " ".join(s.text for s in segs)
    sentence_en = " ".join(s.text for s in built_by_lang["en"][0])
    return Built(m, segs, values, sentence, all_problems, sentence_en, appended)


def facts_to_verify(rule_ids: list[str], kb: Knowledge, remaining: list[str], limit: int = 6) -> list[str]:
    out = []
    for rid in [r for r in rule_ids if r != "E01"] + (["E01"] if "E01" in rule_ids else []):
        for f in kb.rules[rid].facts_needed:
            if f not in out:
                out.append(f)
    out = out[:limit]
    if remaining:
        out.append("Complete the marked placeholders: " + ", ".join(f"[{p}]" for p in remaining))
    return out


def why_template_mode(rule_ids: list[str], kb: Knowledge) -> str:
    main = next((r for r in rule_ids if r != "E01"), rule_ids[0] if rule_ids else None)
    return kb.rules[main].requirement if main else ""


def to_recommendation(b: Built, ctx: Context, lib: Library, kb: Knowledge) -> dict:
    t = b.match.template
    lang_used = ctx.language if (ctx.language == "en" or t.text_de) else "en"
    cited = list(b.match.cited_rules)
    for at in b.appended:
        cited += [r for r in at.rule_ids if r in ctx.candidates and r not in cited]
    remaining = remaining_placeholders(b.sentence)
    chips = []
    for name in remaining:
        owner = next((seg.template for seg in b.segments if seg.template.slot(name)), t)
        chips.append(slot_chip(owner, name, ctx, lib))
    return {
        "template_id": t.template_id,
        "appended_template_ids": [a.template_id for a in b.appended],
        "sentence": b.sentence,
        "sentence_en": b.sentence_en,
        "language": lang_used,
        "specificity": t.specificity,
        "kind": t.kind,
        "ai_adjusted": False,
        "ai_parts": [],
        "status_line": STATUS_LINE[lang_used],
        "why_it_fits": why_template_mode(b.match.cited_rules, kb),
        "why_source": "rule_requirement",
        "facts_to_verify": facts_to_verify(cited, kb, remaining),
        "placeholders": remaining,
        "placeholder_chips": chips,
        "values": b.values,
        "regulations": regulations_for(cited, kb),
        "rule_ids": cited,
        "german_unreviewed": lang_used == "de" and not t.de_reviewed,
        "tags": ([GERMAN_TAG] if lang_used == "de" and not t.de_reviewed else []),
        "safest": False,
    }


def what_to_obtain(ctx: Context, lib: Library, kb: Knowledge) -> list[dict]:
    tr = lib.topic_rules["topics"].get(ctx.topic or "", {})
    order = list(ctx.topic_rules) + [r for r in tr.get("product_rules", []) if r in ctx.candidates] + \
        [r for r in tr.get("general_rules", []) if r in ctx.candidates]
    out, seen = [], set()
    if ctx.topic == "general_benefit" and ctx.b2c:
        out.append({"item": "An EU Ecolabel licence for the product, or switch to a specific topic such as recycled content", "rule_id": "P01"})
    for rid in dict.fromkeys(order + ["E01"]):
        if rid not in ctx.candidates:
            continue
        for f in kb.rules[rid].facts_needed:
            if f.lower() in seen:
                continue
            seen.add(f.lower())
            out.append({"item": f, "rule_id": rid})
    return out[:10]


def topic_notes(ctx: Context, lib: Library) -> None:
    t = lib.questionnaire["topics"].get(ctx.topic or "", {})
    note = t.get("note")
    if not note:
        return
    if ctx.topic == "general_benefit" and not ctx.b2c:
        ctx.note("info", "Generic claims to businesses are not on the consumer black list, but they must not mislead (rule B01). "
                         "State the metric and method.", "B01")
        return
    if ctx.topic == "climate_neutral_or_offset":
        if ctx.b2c and ctx.subject != "company" and ctx.scope not in ("company", "site"):
            ctx.note("info", note["en"], "P03")
        elif ctx.b2c:
            ctx.note("info", "No climate-neutral sentence is offered. Company-level statements must keep emissions, reductions and "
                             "financed credits apart (rules M08, P03, CR03).", "M08")
        else:
            ctx.note("info", "For business audiences, state emissions and financed credits separately (rule RP07).", "RP07")
        return
    ctx.note("info", note["en"], {"general_benefit": "P01", "free_from_substances": "P05"}.get(ctx.topic))


# ---------------------------------------------------------------------------------------------
def ai_available(settings: Settings, client: OllamaClient | None) -> tuple[bool, str | None]:
    if not settings.ollama_enabled:
        return False, None
    if client is None:
        return False, "AI is switched off for this run, so template mode was used."
    st = client.status(settings.chat_model)
    if not st.available:
        return False, "Ollama is not running, so template mode was used. Results are complete without AI."
    if not st.model_present:
        return False, f"The model {settings.chat_model} is not installed, so template mode was used."
    return True, None


def apply_ai(rec: dict, b: Built, ctx: Context, lib: Library, kb: Knowledge, client: OllamaClient, model: str) -> list[str]:
    alog: list[str] = []
    t = b.match.template
    main_seg = b.segments[0]
    tail = " ".join(s.text for s in b.segments[1:])
    lang = rec["language"]

    def recheck(text: str, L: str) -> list[str]:
        segs = [Segment(text, t)] + b.segments[1:]
        if L != lang:
            return []
        return check_segments(segs, L, ctx, lib, kb, b.values)

    # translation: German requested and the German template text is missing or unreviewed
    if ctx.language == "de" and (not t.text_de or not t.de_reviewed):
        en_main = fill_text(t.text_en, slot_values(t, ctx, lib, "en"))
        de_values = slot_values(t, ctx, lib, "de")

        def extra_de(out):
            segs = [Segment(out, t)] + ([Segment(s.text, s.template) for s in b.segments[1:]] if lang == "de" else [])
            return check_segments(segs, "de", ctx, lib, kb, de_values)

        out = ai.translate_checked(client, model, en_main, t, slot_values(t, ctx, lib, "en"), de_values, extra_de, alog)
        if out:
            if lang != "de":
                tail_de = " ".join(fill_text(a.text("de"), slot_values(a, ctx, lib, "de")) for a in b.appended)
                tail = tail_de
                lang = rec["language"] = "de"
                rec["status_line"] = STATUS_LINE["de"]
            main_seg = Segment(out, t)
            rec["sentence"] = (out + " " + tail).strip()
            rec["ai_adjusted"] = True
            rec["ai_parts"].append("translation")
            rec["german_unreviewed"] = True
            rec["tags"] = [GERMAN_TAG]
    # tone
    if ctx.tone != "factual":
        out, l2 = ai.rewrite_tone(client, model, main_seg.text, lang, ctx.tone, b.values, lambda o: recheck(o, lang))
        alog += l2
        if out:
            rec["sentence"] = (out + " " + tail).strip()
            rec["ai_adjusted"] = True
            rec["ai_parts"].append("tone")
    # why it fits
    rules = [{"rule_id": r, "requirement": kb.rules[r].requirement} for r in rec["rule_ids"][:3]]
    passages = [p for p in rec["regulations"] if p["rule_id"] in {r["rule_id"] for r in rules}]
    if passages:
        why, cited = ai.explain_fit(client, model, rec["sentence"], rules, passages, alog)
        if why:
            rec["why_it_fits"] = why
            rec["why_source"] = "ai"
            rec["why_chunk_ids"] = cited
            rec["ai_parts"].append("why_it_fits")
    rec["placeholders"] = remaining_placeholders(rec["sentence"])
    return alog


# ---------------------------------------------------------------------------------------------
def recommend(answers: dict, kb: Knowledge, lib: Library, settings: Settings,
              client: OllamaClient | None = None, use_ai: bool = True) -> dict:
    t0 = time.perf_counter()
    ctx = build_context(answers, kb, lib)
    gate_notes(ctx, kb)
    topic_notes(ctx, lib)
    usable, future, rejected = select(ctx, lib, kb)
    appends, missing = mandatory_appends(ctx, lib, kb)
    for m in missing:
        ctx.note("info", f"The mandatory statement for rule {m.template.rule_ids[0]} could not be added "
                         f"({', '.join(m.reasons)}). It must accompany the claim: \"{m.template.text_en}\"", m.template.rule_ids[0])
        ctx.human_review = True
    for m in rejected:
        ctx.log.append(f"template {m.template.template_id} not used: {', '.join(m.reasons)}")

    built: dict[str, Built] = {}
    passing: list[Match] = []
    for m in usable:
        b = build_one(m, ctx, lib, kb, appends, ctx.language)
        if b.problems:
            ctx.log.append(f"template {m.template.template_id} dropped: {'; '.join(b.problems)}")
            log.info("dropped %s: %s", m.template.template_id, b.problems)
            continue
        built[m.template.template_id] = b
        passing.append(m)
    picked = choose(passing, ctx)
    recs = [to_recommendation(built[m.template.template_id], ctx, lib, kb) for m in picked]
    if recs:
        from .select import safety_key
        safest_id = min(picked, key=safety_key).template.template_id
        for r in recs:
            r["safest"] = r["template_id"] == safest_id

    mode, chat_model = "template", None
    ok, msg = ai_available(settings, client) if use_ai else (False, None)
    if msg:
        ctx.note("mode", msg, None)
    if ok and recs:
        mode, chat_model = "ai", settings.chat_model
        for r in recs:
            ctx.log += apply_ai(r, built[r["template_id"]], ctx, lib, kb, client, settings.chat_model)

    if not recs:
        ctx.human_review = True
        if ctx.topic == "general_benefit" and ctx.b2c:
            ctx.note("empty", "No generic sentence is possible without recognised excellent environmental performance (rule P01). "
                              "Obtain an EU Ecolabel licence, or switch to a specific topic.", "P01")
        elif ctx.evidence == "none_yet":
            ctx.note("empty", "No sentence can be recommended before evidence exists (rule E01). See what to obtain first.", "E01")
        else:
            ctx.note("empty", "No predefined sentence fits these answers. Try another scope, evidence type or method, "
                              "or ask a reviewer to add a template.", None)
    if ctx.evidence == "none_yet":
        ctx.human_review = True

    # Don't say
    tr = lib.topic_rules["topics"].get(ctx.topic or "", {})
    topic_rule_ids = list(ctx.topic_rules) + tr.get("product_rules", []) + tr.get("general_rules", [])
    ds_rows = context_dont_say(ctx, lib, topic_rule_ids)
    sentences = [r["sentence"] for r in recs]
    by_id = {e["id"]: e for e in lib.dont_say}
    ds_rows = [d for d in ds_rows if not (d["status"] == "conditional" and any(
        entry_hits(by_id[d["id"]], s, r["language"]) for s, r in zip(sentences, recs)))]

    # future notes
    en_sentences = [r["sentence_en"] for r in recs]
    cited_all = list(dict.fromkeys([rid for r in recs for rid in r["rule_ids"]] + [r for r in topic_rule_ids if r in ctx.candidates]))
    future_reqs = adopted_future_notes(ctx, kb, future) + future_watch_notes(ctx, kb, lib, en_sentences) + dfa_notes(cited_all, kb)

    q = lib.questionnaire
    return {
        "answers": answers,
        "context": {
            "segment": ctx.segment, "product_type": ctx.product_type, "subject": ctx.subject, "audiences": ctx.audiences,
            "channel": ctx.channel, "topic": ctx.topic, "scope": ctx.scope, "evidence": ctx.evidence,
            "domains": sorted(ctx.domains - {"ALL", "ALL_GOODS"}), "use_date": ctx.use_date, "language": ctx.language,
            "candidate_rules": ctx.candidates, "future_dated_rules": ctx.future_dated,
            "topic_label": q["topics"].get(ctx.topic, {}).get("label_en"),
        },
        "recommendations": recs,
        "dont_say": ds_rows,
        "what_to_obtain": what_to_obtain(ctx, lib, kb) if (ctx.evidence == "none_yet" or not recs) else [],
        "future_requirements": future_reqs,
        "notes": ctx.notes,
        "human_review_required": bool(ctx.human_review),
        "disclaimer": DISCLAIMER,
        "log": ctx.log,
        "run": {"mode": mode, "chat_model": chat_model, "library_hash": lib.library_hash,
                "knowledge_hash": kb.knowledge_hash, "duration_ms": int((time.perf_counter() - t0) * 1000)},
    }


def _validate_overrides(ctx: Context, t: Template, overrides: dict, lib: Library, kb: Knowledge) -> tuple[dict, dict]:
    errors, clean = {}, {}
    fields = {f["name"]: f for f in topic_fact_fields(ctx, lib, kb)}
    for name, v in (overrides or {}).items():
        s = t.slot(name) or next((a.slot(name) for a in lib.by_topic("_mandatory") if a.slot(name)), None)
        if s is None or s.source == "manual" or name == "comparator":
            errors[name] = "this placeholder cannot be edited in the app"
            continue
        if v in (None, ""):
            continue
        if name in ("component", "excluded"):
            pool = parts_for(ctx.domains, lib) + lib.questionnaire["parts"]["PACKAGING"]
            if v not in {o["id"] for o in pool}:
                errors[name] = "choose a part from the list"
                continue
            clean[name] = v
        elif name == "year":
            if not re.fullmatch(lib.questionnaire["patterns"]["year"], str(v)):
                errors[name] = "use a four-digit year"
                continue
            clean[name] = str(v)
        elif name == "method":
            errors[name] = "change the method in question 6"
        else:
            fdef = fields.get(name) or {"type": s.type, "options": s.options}
            try:
                clean[name] = validate_fact(fdef, v, lib)
            except ValueError as e:
                errors[name] = str(e)
    return clean, errors


def _build_single(answers: dict, template_id: str, overrides: dict, kb: Knowledge, lib: Library):
    ctx = build_context(answers, kb, lib)
    t = lib.templates.get(template_id)
    if t is None:
        return ctx, None, {"template_id": "unknown template"}
    clean, errors = _validate_overrides(ctx, t, overrides, lib, kb)
    if errors:
        return ctx, None, errors
    m = next((x for x in select(ctx, lib, kb)[0] if x.template.template_id == template_id), None)
    if m is None:
        return ctx, None, {"template_id": "this template does not fit the current answers"}
    appends, _ = mandatory_appends(ctx, lib, kb)
    b = build_one(m, ctx, lib, kb, appends, ctx.language, clean)
    if b.problems:
        return ctx, b, {"sentence": "; ".join(b.problems)}
    return ctx, b, {}


def revalidate(answers: dict, template_id: str, overrides: dict, kb: Knowledge, lib: Library) -> dict:
    """Re-run fill and validation for one template after a placeholder chip edit (template mode, no AI)."""
    ctx, b, errors = _build_single(answers, template_id, overrides, kb, lib)
    if errors:
        return {"ok": False, "errors": errors, "problems": b.problems if b else []}
    return {"ok": True, "recommendation": to_recommendation(b, ctx, lib, kb)}


def adjust_one(answers: dict, template_id: str, overrides: dict, kb: Knowledge, lib: Library, settings: Settings,
               client: OllamaClient | None) -> dict:
    """One proof slip in another language or tone. Uses the AI when available, else the template text."""
    ctx, b, errors = _build_single(answers, template_id, overrides, kb, lib)
    if errors:
        return {"ok": False, "errors": errors}
    rec = to_recommendation(b, ctx, lib, kb)
    ok, msg = ai_available(settings, client)
    if not ok:
        note = msg or "AI is switched off."
        if ctx.tone != "factual":
            note += " Tone changes need the local AI, so the template wording is kept."
        return {"ok": True, "recommendation": rec, "message": note, "mode": "template"}
    alog = apply_ai(rec, b, ctx, lib, kb, client, settings.chat_model)
    return {"ok": True, "recommendation": rec, "mode": "ai", "log": alog}


def route_summary(answers: dict, kb: Knowledge, lib: Library) -> dict:
    """Live view for the job ticket: routed rules and the options for the next questions."""
    ctx = build_context(answers, kb, lib, partial=True)
    q = lib.questionnaire
    topics = available_topics(ctx, lib)
    rules = [{"rule_id": r, "title": kb.rules[r].title, "severity": kb.rules[r].severity,
              "origin": "product" if r in ctx.product_rules else ("topic" if r in ctx.topic_rules else "general")}
             for r in ctx.candidates]
    scope_part_domains = {"PACKAGING"} if ctx.scope == "packaging" else ctx.domains
    return {
        "segment_options": None,
        "refinements": q["segment_refinements"].get(ctx.segment or "", []),
        "subject": ctx.subject,
        "audiences": ctx.audiences,
        "topics": [{"id": t, "label_en": q["topics"][t]["label_en"], "comparable": q["topics"][t]["comparable"]} for t in topics],
        "scopes": scope_options(ctx, lib) if ctx.topic else [],
        "parts": parts_for(scope_part_domains, lib),
        "evidence": evidence_options(ctx, lib) if ctx.topic else [],
        "methods": q["topics"].get(ctx.topic or "", {}).get("methods", []),
        "fact_fields": topic_fact_fields(ctx, lib, kb),
        "comparable": bool(ctx.topic and q["topics"][ctx.topic]["comparable"]),
        "topic_note": (q["topics"].get(ctx.topic or "", {}).get("note") or {}).get("en"),
        "rules": rules,
        "future_dated_rules": ctx.future_dated,
        "domains": sorted(ctx.domains - {"ALL", "ALL_GOODS"}),
        "notes": ctx.notes,
        "manual_review": ctx.manual_review,
    }
