"""Step 6 (optional): tone, translation and short explanations from the local model.

Every model output is checked in code. If a check fails, the call is retried once with feedback;
if it fails again, the caller falls back to the template text and the rule's own requirement.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from ..config import PROMPTS_DIR
from ..library import Library, Template, norm, numbers_in, placeholders, strip_placeholders
from ..ollama_client import OllamaClient, OllamaError

SENTENCE_SCHEMA = {"type": "object", "properties": {"sentence": {"type": "string"}}, "required": ["sentence"]}
WHY_SCHEMA = {"type": "object", "properties": {"why": {"type": "string"},
                                               "chunk_ids": {"type": "array", "items": {"type": "string"}}},
              "required": ["why", "chunk_ids"]}

# Word stems that would add an environmental benefit if they appeared more often than in the source.
ENV_STEMS = {
    "en": ["sustainab", "green", "eco", "natural", "nature", "clean", "friendly", "responsib", "conscious", "planet",
           "earth", "environmentally", "climate", "neutral", "positive", "better", "best", "pure", "safe", "healthy",
           "renewable", "recycl", "compost", "biodegrad", "organic", "low", "zero", "kind", "gentle", "ethical"],
    "de": ["nachhaltig", "grün", "öko", "natürlich", "natur", "sauber", "freundlich", "verantwort", "bewusst", "planet",
           "erde", "umweltfreund", "klima", "neutral", "positiv", "besser", "beste", "rein", "sicher", "gesund",
           "erneuerbar", "recycel", "rezykl", "kompost", "abbaubar", "bio", "arm", "null", "schonend", "sanft", "ethisch"],
}
STANDARD_STEMS = ["iso", "din", "certif", "zertifi", "label", "seal", "siegel", "ecolabel", "emas", "pef", "licen", "lizenz",
                  "verified", "verifiziert", "validated", "validiert", "audited", "geprüft", "tested", "geprüft"]
LEGAL_REF = re.compile(r"(Regulation|Directive|Verordnung|Richtlinie|Delegated Regulation|Delegierte Verordnung)\s*\((?:EU|EG|EC)\)\s*(?:No\.?\s*|Nr\.\s*)?\d+/\d+"
                       r"|(?:EN\s+)?ISO\s+\d+(?:-\d+)?(?::\d{4})?|§\s*\d+\w*\s+\w+", re.I)
QUALIFIERS = {
    "en": ["not included", "does not reduce", "do not reduce", "not counted", "not suitable for home composting",
           "excluding carbon credits", "separately", "where available", "where collection", "as required by law",
           "only", "by weight", "not deducted", "other life-cycle stages", "eligibility only means", "does not show",
           "use biocides safely", "use plant protection products safely", "always read the label", "do not leave",
           "applicable minimum", "range a to g", "interim target", "independent verification", "separate statement", "per "],
    "de": ["nicht eingeschlossen", "nicht", "davon getrennt", "sofern vorhanden", "wie gesetzlich", "nur",
           "gewicht", "nicht angerechnet", "nicht eingerechnet", "andere lebenszyklusphasen", "biozidprodukte vorsichtig verwenden",
           "pflanzenschutzmittel vorsichtig verwenden", "etikett", "mindestanteil", "spektrum a bis g", "zwischenziel",
           "unabhängige überprüfung", "gesonderte angabe", "je "],
}
EN_TO_DE_QUALIFIER = {
    "not included": r"nicht eingeschlossen|nicht enthalten|nicht inbegriffen",
    "separate statement": r"gesondert",
    "does not reduce": r"\bnicht\b", "do not reduce": r"\bnicht\b",
    "where available": r"sofern (vorhanden|verfügbar)|wo verfügbar",
    "as required by law": r"wie gesetzlich|gesetzlich vorgeschrieben",
    "only": r"\bnur\b|ausschließlich", "by weight": r"gewicht",
    "separately": r"getrennt|gesondert", "not counted": r"nicht angerechnet|nicht eingerechnet|nicht berücksichtigt",
    "excluding carbon credits": r"nicht eingerechnet|ausgenommen|nicht berücksichtigt",
    "not suitable for home composting": r"nicht für die heimkompostierung",
}
FORBIDDEN_WHY = re.compile(r"\bcomplian|guarantee|garantie|rechtskonform|\blegal(ly)?\b|legal advice", re.I)

TONE_DESC = {"warm": "warm, friendly but factual", "short": "short and plain (as few words as possible)",
             "factual": "neutral and factual"}


def _prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")


def _stem_counts(text: str, stems: list[str]) -> Counter:
    t = norm(strip_placeholders(text))
    return Counter({s: len(re.findall(rf"(?<![a-zäöüß]){re.escape(s)}", t)) for s in stems})


def protected_phrases(text: str, lang: str, values: dict[str, str] | None = None) -> list[str]:
    n = norm(text)
    out = [m.group(0) for m in LEGAL_REF.finditer(text)]
    out += [q for q in QUALIFIERS[lang] if q in n and q.strip() not in ("nicht", "nur", "per", "je", "only", "gewicht")]
    out += [v for v in (values or {}).values() if v]
    return list(dict.fromkeys(out))


@dataclass
class CheckResult:
    ok: bool
    problems: list[str] = field(default_factory=list)


def structural_check(source: str, output: str, src_lang: str, out_lang: str, values: dict[str, str] | None = None,
                     out_values: dict[str, str] | None = None) -> CheckResult:
    """Compare numbers, placeholders, protected phrases and new claim words between source and output."""
    p: list[str] = []
    if not output or len(output) > 3 * len(source) + 80:
        p.append("empty or far too long")
    if sorted(placeholders(source)) != sorted(placeholders(output)):
        p.append("placeholders changed")
    if numbers_in(source) != numbers_in(output):
        p.append(f"numbers changed ({numbers_in(source)} -> {numbers_in(output)})")
    on = norm(output)
    if src_lang == out_lang:
        for ph in protected_phrases(source, src_lang, values):
            if norm(ph) not in on:
                p.append(f"protected phrase dropped: '{ph}'")
    else:
        de_words = re.findall(r"(?<![a-zäöüß])(der|die|das|des|dem|den|und|ist|sind|nach|für|mit|von|aus|bis|je|wie|nicht|im|zur|zum|wird|werden)(?![a-zäöüß])", on)
        if norm(output) == norm(source) or not de_words:
            p.append("output is not German")
        for m in LEGAL_REF.finditer(source):
            nums = re.findall(r"\d+/\d+|\d+", m.group(0))
            if not all(n in output for n in nums):
                p.append(f"legal reference changed: '{m.group(0)}'")
        for en_q, de_rx in EN_TO_DE_QUALIFIER.items():
            if en_q in norm(source) and not re.search(de_rx, on):
                p.append(f"qualifier lost in translation: '{en_q}'")
        for v in (out_values or {}).values():
            if v and norm(v) not in on:
                p.append(f"slot value missing: '{v}'")
    # no new environmental adjective or benefit, no new standard or certificate
    src_env = sum(_stem_counts(source, ENV_STEMS[src_lang]).values())
    if src_lang == out_lang:
        before, after = _stem_counts(source, ENV_STEMS[out_lang]), _stem_counts(output, ENV_STEMS[out_lang])
        added = [s for s in after if after[s] > before[s]]
        if added:
            p.append(f"adds environmental wording: {added}")
    else:
        if sum(_stem_counts(output, ENV_STEMS[out_lang]).values()) > src_env + 1:
            p.append("adds environmental wording")
    b, a = _stem_counts(source, STANDARD_STEMS), _stem_counts(output, STANDARD_STEMS)
    if src_lang == out_lang and any(a[s] > b[s] for s in a):
        p.append("adds a standard, label or certificate")
    if src_lang != out_lang and sum(a.values()) > sum(b.values()) + 1:
        p.append("adds a standard, label or certificate")
    return CheckResult(not p, p)


# ---------------------------------------------------------------------------------------------
def _call(client: OllamaClient, model: str, user: str, schema: dict) -> dict:
    return client.chat_json(model, _prompt("system"), user, schema)


def rewrite_tone(client: OllamaClient, model: str, sentence: str, lang: str, tone: str, values: dict[str, str],
                 extra_check=None) -> tuple[str | None, list[str]]:
    """Return (rewritten sentence or None, log)."""
    log = []
    feedback = ""
    for attempt in range(2):
        user = _prompt("tone").format(tone_description=TONE_DESC.get(tone, tone),
                                      language_name="German" if lang == "de" else "English",
                                      protected="; ".join(protected_phrases(sentence, lang, values)) or "none",
                                      feedback=feedback, sentence=sentence)
        try:
            out = str(_call(client, model, user, SENTENCE_SCHEMA).get("sentence", "")).strip()
        except OllamaError as e:
            log.append(f"tone: model error: {e}")
            return None, log
        res = structural_check(sentence, out, lang, lang, values)
        problems = list(res.problems)
        if extra_check and not problems:
            problems += extra_check(out)
        if not problems:
            log.append(f"tone: accepted on attempt {attempt + 1}")
            return out, log
        log.append(f"tone: rejected attempt {attempt + 1}: {'; '.join(problems)}")
        feedback = "Your previous answer was rejected because: " + "; ".join(problems) + ". Try again."
    return None, log


def translate_checked(client: OllamaClient, model: str, text_en: str, template: Template | None = None,
                      values_en: dict | None = None, values_de: dict | None = None, extra_check=None,
                      log: list | None = None) -> str | None:
    log = log if log is not None else []
    feedback = ""
    for attempt in range(2):
        user = _prompt("translate").format(feedback=feedback, sentence=text_en)
        try:
            out = str(_call(client, model, user, SENTENCE_SCHEMA).get("sentence", "")).strip()
        except OllamaError as e:
            log.append(f"translate: model error: {e}")
            return None
        res = structural_check(text_en, out, "en", "de", values_en, values_de)
        problems = list(res.problems)
        if extra_check and not problems:
            problems += extra_check(out)
        if not problems:
            log.append(f"translate: accepted on attempt {attempt + 1}")
            return out
        log.append(f"translate: rejected attempt {attempt + 1}: {'; '.join(problems)}")
        feedback = "Your previous answer was rejected because: " + "; ".join(problems) + ". Try again."
    return None


def explain_fit(client: OllamaClient, model: str, sentence: str, rules: list[dict], passages: list[dict],
                log: list | None = None) -> tuple[str | None, list[str]]:
    """'Why it fits' from the rules' requirements and verified quotes. Must cite supplied chunk_ids."""
    log = log if log is not None else []
    allowed = {p["chunk_id"] for p in passages}
    block = []
    for r in rules:
        block.append(f"RULE {r['rule_id']}: {r['requirement']}")
        for p in passages:
            if p["rule_id"] == r["rule_id"]:
                block.append(f"  PASSAGE chunk_id={p['chunk_id']} ({p['doc_title']}, {p['locator']}): \"{p['quote']}\"")
    feedback = ""
    for attempt in range(2):
        user = _prompt("why").format(feedback=feedback, sentence=sentence, passages="\n".join(block))
        try:
            data = _call(client, model, user, WHY_SCHEMA)
        except OllamaError as e:
            log.append(f"why: model error: {e}")
            return None, []
        why = str(data.get("why", "")).strip()
        cited = [str(c) for c in data.get("chunk_ids", []) if isinstance(c, (str, int))]
        problems = []
        n_sent = len([s for s in re.split(r"(?<=[.!?])\s+", why) if s.strip()])
        if not why or n_sent > 2 * max(1, len(rules)) or n_sent > 4:
            problems.append("too long or empty")
        if not cited or not set(cited) <= allowed:
            problems.append("cites chunk_ids that were not supplied" if cited else "cites no chunk_id")
        if FORBIDDEN_WHY.search(why):
            problems.append("uses forbidden wording (compliant/guaranteed/legal)")
        new_nums = set(numbers_in(why)) - set(numbers_in(sentence + " " + " ".join(r["requirement"] for r in rules)
                                                       + " ".join(p["quote"] for p in passages)))
        if new_nums:
            problems.append("adds numbers")
        if not problems:
            log.append(f"why: accepted on attempt {attempt + 1}")
            return why, cited
        log.append(f"why: rejected attempt {attempt + 1}: {'; '.join(problems)}")
        feedback = "Your previous answer was rejected because: " + "; ".join(problems) + ". Try again."
    return None, []
