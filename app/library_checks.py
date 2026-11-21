"""Hard checks on the template library (brief section 5, checks 1-8).

Each check returns a list of error strings. The build fails if any list is non-empty.
"""
from __future__ import annotations

import re

from .knowledge import Knowledge
from .library import (
    FIGURE_RE, LEGAL_AS_FEATURE_RULES, NEUTRAL_LEGAL, ADVANTAGE_WORDS, Library, Template, TriggerEntry,
    contains_phrase, has_figure, lift_holds_for_template, norm, placeholders, placeholders_well_formed,
    strip_placeholders,
)

QUOTED = re.compile(r"'([^']+)'")


def rule_applies_to_template(rule, t: Template) -> bool:
    if not set(rule.audience) & set(t.requires.audience):
        return False
    rd = set(rule.scope.product_domains)
    if rd & {"ALL", "ALL_GOODS"}:
        return True
    td = set(t.requires.product_domains)
    if "ALL" not in td and not (rd & td):
        return False
    if rd <= set(t.requires.not_domains):
        return False
    return True


def phrase_hits(text: str, lang: str, entry: TriggerEntry) -> bool:
    if contains_phrase(text, entry.phrase, "en"):
        return True
    if lang == "de":
        return any(contains_phrase(text, p, "de") for p in entry.de)
    return False


def avoid_phrases(rule, trigger_de: dict) -> list[tuple[str, list[str]]]:
    out = []
    for a in rule.fix.avoid:
        for q in QUOTED.findall(a):
            out.append((q, trigger_de.get(q, [])))
    return out


def check_links(lib: Library, kb: Knowledge) -> list[str]:
    """Check 1: every template links to at least one rule, and the linked rules' quotes are verified."""
    errs = []
    for t in lib.templates.values():
        if not t.rule_ids:
            errs.append(f"{t.template_id}: links to no rule")
        for rid in t.rule_ids + t.satisfies:
            r = kb.rules.get(rid)
            if r is None:
                errs.append(f"{t.template_id}: unknown rule {rid}")
                continue
            if r.scope.routing == "future_watch":
                errs.append(f"{t.template_id}: rests on future-law rule {rid}")
            if len(kb.quotes.get(rid, [])) != len(r.basis):
                errs.append(f"{t.template_id}: rule {rid} has basis quotes that are not found word for word")
        if t.topic != "_mandatory" and t.topic not in lib.questionnaire["topics"]:
            errs.append(f"{t.template_id}: unknown topic {t.topic}")
    for f in kb.quote_failures:
        errs.append(f"knowledge: {f}")
    return errs


def check_placeholders(lib: Library) -> list[str]:
    """Check 2: placeholders are well formed and each has a slot (and the same set in both languages)."""
    errs = []
    opt_lists = set(lib.questionnaire["option_lists"]) | {"parts", "methods", "comparison"}
    for t in lib.templates.values():
        for lang, text in (("en", t.text_en), ("de", t.text_de)):
            if not text and lang == "de":
                continue
            for p in placeholders_well_formed(text):
                errs.append(f"{t.template_id} ({lang}): {p}")
        ph_en = set(placeholders(t.text_en))
        slots = {s.name for s in t.slots}
        for name in ph_en - slots:
            errs.append(f"{t.template_id}: placeholder [{name}] has no slot")
        for name in slots - ph_en:
            errs.append(f"{t.template_id}: slot {name} is not used in the text")
        if t.text_de and set(placeholders(t.text_de)) != ph_en:
            errs.append(f"{t.template_id}: German placeholders differ from English")
        for s in t.slots:
            if s.type == "choice" and s.options not in opt_lists:
                errs.append(f"{t.template_id}: slot {s.name} uses unknown option list {s.options}")
    return errs


def check_triggers(lib: Library, kb: Knowledge) -> list[str]:
    """Check 3: no template contains a trigger of a rule that applies to it unless the trigger is lifted.

    Prohibited rules: the template must list the rule in `satisfies` and its requirements must imply the lift.
    Case-by-case rules (stricter than the brief): banned wording never appears; conditional wording only
    where the template's requirements imply the lift. Detectors of case-by-case rules are topic keywords.
    """
    errs = []
    for t in lib.templates.values():
        for e in lib.catalogue:
            rule = kb.rules[e.rule_id]
            if not rule_applies_to_template(rule, t):
                continue
            if e.severity == "case_by_case" and e.status == "detector":
                continue
            for lang, text in (("en", t.text_en), ("de", t.text_de)):
                if not text or not phrase_hits(text, lang, e):
                    continue
                where = f"{t.template_id} ({lang}): '{e.phrase}' ({e.rule_id}, {e.status})"
                if e.status == "banned":
                    errs.append(f"{where} is banned wording")
                    continue
                lift = lib.lifts.get(e.lift or "")
                if lift is None:
                    errs.append(f"{where} has no lift route")
                    continue
                if e.severity == "prohibited" and e.rule_id not in t.satisfies:
                    errs.append(f"{where} appears but the template does not list {e.rule_id} in satisfies")
                    continue
                if not lift_holds_for_template(lift, t):
                    errs.append(f"{where} appears but the template's requirements do not imply the lift '{e.lift}'")
    return errs


def check_avoid(lib: Library, kb: Knowledge) -> list[str]:
    """Check 4: no template contains wording from any linked rule's fix.avoid."""
    errs = []
    for t in lib.templates.values():
        for rid in t.rule_ids:
            for phrase, de in avoid_phrases(kb.rules[rid], lib.trigger_de):
                if contains_phrase(t.text_en, phrase, "en") or any(contains_phrase(t.text_de, p, "de") for p in de):
                    errs.append(f"{t.template_id}: contains '{phrase}' from {rid} fix.avoid")
    return errs


def is_neutral_legal(text: str, lang: str) -> bool:
    n = norm(text)
    return any(re.search(p, n) for p in NEUTRAL_LEGAL[lang])


def advantage_hits(text: str, lang: str) -> list[str]:
    return [w for w in ADVANTAGE_WORDS[lang] if contains_phrase(text, w, lang)]


def check_legal_as_feature(lib: Library, kb: Knowledge) -> list[str]:
    """Check 5: a legal requirement is never presented as a special feature."""
    errs = []
    lf_triggers = {r: kb.rules[r].triggers for r in LEGAL_AS_FEATURE_RULES}
    for t in lib.templates.values():
        linked = [r for r in t.rule_ids if r in LEGAL_AS_FEATURE_RULES]
        touched = [r for r, trig in lf_triggers.items()
                   if rule_applies_to_template(kb.rules[r], t) and any(contains_phrase(t.text_en, p) for p in trig)]
        if (linked or touched) and t.kind != "legal_neutral":
            errs.append(f"{t.template_id}: rests on {linked or touched} but is not neutral legal wording")
        if t.kind == "legal_neutral":
            for lang, text in (("en", t.text_en), ("de", t.text_de)):
                if text and not is_neutral_legal(text, lang):
                    errs.append(f"{t.template_id} ({lang}): legal_neutral template lacks the neutral legal phrase")
                for w in advantage_hits(text, lang) if text else []:
                    errs.append(f"{t.template_id} ({lang}): legal_neutral template uses advantage word '{w}'")
    return errs


CERT_WORDS = re.compile(r"certif|licen[cs]e|registration number|zertifi|lizenz|registrierungsnummer", re.I)


def template_has_figure(t: Template) -> bool:
    return t.has_numeric_slot() or has_figure(t.text_en)


def check_figures(lib: Library) -> list[str]:
    """Check 6: a template with a figure (or a certificate) requires evidence other than 'None yet'."""
    errs = []
    for t in lib.templates.values():
        if "none_yet" not in t.requires.evidence_types:
            continue
        if template_has_figure(t):
            errs.append(f"{t.template_id}: has a figure but allows evidence 'none_yet'")
        if CERT_WORDS.search(strip_placeholders(t.text_en)) or any(s.name == "ID" for s in t.slots):
            errs.append(f"{t.template_id}: names a certificate or licence but allows evidence 'none_yet'")
    return errs


def check_future(lib: Library, kb: Knowledge) -> list[str]:
    """Check 7: templates based on rules with an applies_from date carry that date."""
    errs = []
    for t in lib.templates.values():
        dates = [kb.rules[r].scope.applies_from for r in t.rule_ids if kb.rules[r].scope.applies_from]
        need = max(dates) if dates else None
        if need and t.applies_from != need:
            errs.append(f"{t.template_id}: linked rules apply from {need} but template applies_from is {t.applies_from}")
        if t.applies_from and not need:
            errs.append(f"{t.template_id}: has applies_from {t.applies_from} but no linked rule is future-dated")
    return errs


def coverage(lib: Library, kb: Knowledge) -> dict[str, dict]:
    """Check 8 data: which rules are covered by a template or a 'Don't say' entry."""
    out = {}
    tpl_by_rule: dict[str, list[str]] = {}
    for t in lib.templates.values():
        for r in t.rule_ids:
            tpl_by_rule.setdefault(r, []).append(t.template_id)
    ds_by_rule: dict[str, int] = {}
    for d in lib.dont_say:
        if d.get("show", True):
            ds_by_rule[d["rule_id"]] = ds_by_rule.get(d["rule_id"], 0) + 1
    for r in kb.rules.values():
        required = r.severity in ("prohibited", "case_by_case", "evidence") and r.scope.routing in ("eclass", "claim_object")
        out[r.rule_id] = {
            "severity": r.severity, "routing": r.scope.routing, "required": required,
            "templates": tpl_by_rule.get(r.rule_id, []), "dont_say": ds_by_rule.get(r.rule_id, 0),
            "covered": bool(tpl_by_rule.get(r.rule_id) or ds_by_rule.get(r.rule_id)),
        }
    return out


def check_coverage(lib: Library, kb: Knowledge) -> list[str]:
    return [f"{rid}: not covered by any template or 'Don't say' entry"
            for rid, c in coverage(lib, kb).items() if c["required"] and not c["covered"]]


def check_scope_named(lib: Library) -> list[str]:
    """A template offered for one part names [component]; one offered for one site names [site] (rules P02, PK02)."""
    errs = []
    for t in lib.templates.values():
        if t.kind == "mandatory_statement":
            continue
        sc = set(t.requires.scope)
        if sc & {"part", "packaging"} and "[component]" not in t.text_en and "packaging unit" not in t.text_en:
            errs.append(f"{t.template_id}: offered for a part but does not name [component]")
        if "site" in sc and "[site]" not in t.text_en:
            errs.append(f"{t.template_id}: offered for one site but does not name [site]")
    return errs


def check_when(lib: Library) -> list[str]:
    errs = []
    q = lib.questionnaire
    for t in lib.templates.values():
        for key, vals in t.when.items():
            if key == "method":
                ms = {m["id"] for m in q["topics"].get(t.topic, {}).get("methods", [])}
                bad = set(vals) - ms
                if bad:
                    errs.append(f"{t.template_id}: when.method uses unknown methods {sorted(bad)}")
    return errs


ALL_CHECKS = [
    ("1 links and verified quotes", lambda lib, kb: check_links(lib, kb)),
    ("2 placeholders and slots", lambda lib, kb: check_placeholders(lib)),
    ("3 prohibited and banned triggers", lambda lib, kb: check_triggers(lib, kb)),
    ("4 fix.avoid wording", lambda lib, kb: check_avoid(lib, kb)),
    ("5 legal requirement as feature", lambda lib, kb: check_legal_as_feature(lib, kb)),
    ("6 figures need evidence", lambda lib, kb: check_figures(lib)),
    ("7 future application dates", lambda lib, kb: check_future(lib, kb)),
    ("8 coverage", lambda lib, kb: check_coverage(lib, kb)),
    ("scope named (P02/PK02)", lambda lib, kb: check_scope_named(lib)),
    ("conditions", lambda lib, kb: check_when(lib)),
]


def run_all(lib: Library, kb: Knowledge) -> dict[str, list[str]]:
    return {name: fn(lib, kb) for name, fn in ALL_CHECKS}
