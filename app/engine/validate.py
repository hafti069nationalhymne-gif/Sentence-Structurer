"""Step 4: validate filled sentences in code, and build the context's 'Don't say' list.

The same matching is used to (a) reject sentences and (b) list the phrases to avoid,
so a returned sentence can never match a 'Don't say' entry for its context.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..knowledge import Knowledge
from ..library import (
    LEGAL_AS_FEATURE_RULES, Library, Template, contains_phrase, has_figure, lift_holds_for_context, norm,
    placeholders, placeholders_well_formed, strip_placeholders,
)
from ..library_checks import advantage_hits, avoid_phrases, is_neutral_legal
from .context import Context


@dataclass
class Segment:
    """One part of a recommended sentence: the main template or an appended mandatory statement."""
    text: str
    template: Template


def entry_active(entry: dict, ctx: Context) -> bool:
    if entry["rule_id"] not in ctx.candidates:
        return False
    af = entry.get("applies_from")
    return not (af and af > ctx.use_date)


def entry_phrases(entry: dict, lang: str) -> list[tuple[str, str]]:
    out = [(entry["phrase_en"], "en")]
    if lang == "de":
        out += [(p, "de") for p in entry.get("de_all") or []]
    return out


def entry_hits(entry: dict, text: str, lang: str) -> bool:
    if entry["match"] == "none":
        return False
    if entry["match"] == "sentence":
        t = norm(strip_placeholders(text))
        return any(norm(strip_placeholders(p)) in t for p, _ in entry_phrases(entry, lang) if p)
    return any(contains_phrase(text, p, l) for p, l in entry_phrases(entry, lang))


def entry_lifted(entry: dict, ctx: Context, lib: Library, tpl: Template | None) -> bool:
    if entry["status"] != "conditional":
        return False
    lift = lib.lifts.get(entry.get("lift") or "")
    if lift is None:
        return False
    if entry["severity"] == "prohibited" and tpl is not None and entry["rule_id"] not in tpl.satisfies:
        return False
    return lift_holds_for_context(lift, ctx, tpl)


def dont_say_violations(text: str, lang: str, ctx: Context, lib: Library, tpl: Template | None) -> list[dict]:
    """Entries of the context's 'Don't say' list (incl. prohibited detectors) that the text matches."""
    out = []
    for e in lib.dont_say:
        if not entry_active(e, ctx) or e["match"] == "none":
            continue
        if e["status"] == "detector":
            # Topic keywords only matter for prohibited rules, and only outside their lift.
            if e["severity"] != "prohibited" or not entry_hits(e, text, lang):
                continue
            lift = lib.lifts.get(e.get("lift") or "")
            if tpl is not None and lift and e["rule_id"] in tpl.satisfies and lift_holds_for_context(lift, ctx, tpl):
                continue
            out.append(e)
            continue
        if entry_hits(e, text, lang) and not entry_lifted(e, ctx, lib, tpl):
            out.append(e)
    return out


def check_segments(segments: list[Segment], lang: str, ctx: Context, lib: Library, kb: Knowledge,
                   values: dict[str, str]) -> list[str]:
    """All code checks for one recommended sentence. Returns the reasons it fails (empty = passes)."""
    problems: list[str] = []
    full = " ".join(s.text for s in segments)
    # placeholders
    for p in placeholders_well_formed(full):
        problems.append(f"placeholder: {p}")
    for seg in segments:
        t = seg.template
        # prohibited triggers, banned wording, 'Don't say' entries
        for e in dont_say_violations(seg.text, lang, ctx, lib, t):
            problems.append(f"don't say: '{e['phrase_en']}' ({e['rule_id']})")
        # fix.avoid of linked rules
        for rid in t.rule_ids:
            for phrase, de in avoid_phrases(kb.rules[rid], lib.trigger_de):
                if contains_phrase(seg.text, phrase, "en") or (lang == "de" and any(contains_phrase(seg.text, p, "de") for p in de)):
                    problems.append(f"fix.avoid: '{phrase}' ({rid})")
        # legal requirement presented as a feature
        lf = [r for r in LEGAL_AS_FEATURE_RULES if r in ctx.candidates
              and any(contains_phrase(seg.text, p) for p in kb.rules[r].triggers)]
        if (lf or set(t.rule_ids) & set(LEGAL_AS_FEATURE_RULES)) and t.kind != "legal_neutral":
            problems.append(f"legal requirement as feature ({', '.join(lf or sorted(set(t.rule_ids) & set(LEGAL_AS_FEATURE_RULES)))})")
        if t.kind == "legal_neutral":
            if not is_neutral_legal(seg.text, lang):
                problems.append("legal requirement without neutral wording")
            for w in advantage_hits(seg.text, lang):
                problems.append(f"legal requirement with advantage word '{w}'")
    # figures without evidence
    if ctx.evidence == "none_yet":
        numeric = any(s.type in ("percent", "number") and s.name in values for seg in segments for s in seg.template.slots)
        if has_figure(full) or numeric:
            problems.append("figure without evidence")
        if any(s.name == "ID" and s.name in values for seg in segments for s in seg.template.slots):
            problems.append("certificate without evidence")
    # scope stated (P02 / PK02)
    scope_rules = [r for r in ("P02", "PK02") if r in ctx.candidates]
    if scope_rules and ctx.scope in ("part", "packaging", "site"):
        names = [values.get("component"), values.get("site"), "[component]", "[site]", "packaging unit", "verpackungseinheit"]
        if not any(n and n.lower() in full.lower() for n in names):
            problems.append(f"scope not stated ({', '.join(scope_rules)})")
    if scope_rules and ctx.excluded:
        if not re.search(r"not included|nicht eingeschlossen", full, re.I):
            problems.append(f"excluded part not stated ({', '.join(scope_rules)})")
    # comparison reference (M06 / B02)
    comp_rules = [r for r in ("M06", "B02") if r in ctx.candidates]
    if ctx.comparison != "none" and comp_rules:
        ref = values.get("comparator")
        if not ((ref and ref.lower() in full.lower()) or "[comparator]" in full):
            problems.append(f"comparison reference missing ({', '.join(comp_rules)})")
    # never certify legal compliance
    if re.search(r"legally compliant|guaranteed|rechtskonform|garantiert", full, re.I):
        problems.append("certifies legal compliance")
    return problems


# ---------------------------------------------------------------------------------------------
def context_dont_say(ctx: Context, lib: Library, topic_rule_ids: list[str], limit: int | None = None) -> list[dict]:
    """The 'Don't say' list for the context, most relevant first, phrases in the output language."""
    lang = ctx.language
    rows, seen = [], set()
    for e in lib.dont_say:
        if not e.get("show", True) or not entry_active(e, ctx):
            continue
        if e["status"] == "conditional":
            lift = lib.lifts.get(e.get("lift") or "")
            if lift and lift_holds_for_context(lift, ctx, None):
                continue  # allowed with the evidence and scope given
        phrase = e["phrase_de"] if lang == "de" and e.get("phrase_de") else e["phrase_en"]
        key = (norm(phrase), e["source"] == "practice")
        if key in seen:
            continue
        seen.add(key)
        prio = (0 if e["rule_id"] in topic_rule_ids else 1,
                {"prohibited": 0, "case_by_case": 1}.get(e["severity"], 2),
                {"trigger": 0, "avoid": 1, "example": 2, "practice": 3}[e["source"]])
        rows.append((prio, {
            "phrase": phrase, "phrase_language": "de" if (lang == "de" and e.get("phrase_de")) else "en",
            "rule_id": e["rule_id"], "reason": e["reason"], "requirement": e["requirement"],
            "kind": {"trigger": "phrase", "avoid": "phrase", "example": "example", "practice": "advice"}[e["source"]],
            "status": e["status"], "id": e["id"],
        }))
    rows.sort(key=lambda r: r[0])
    out = [r for _, r in rows]
    return out[:limit] if limit else out
