"""The curated template library and the shared wording checks.

Both the library build (scripts/build_library.py) and the engine use this module,
so a template is checked with exactly the same code at build time and at run time.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Literal, Optional

from pydantic import BaseModel, Field

from .config import LIBRARY_DIR

# ---- vocabularies ------------------------------------------------------------
EVIDENCE_TYPES = [
    "third_party_certificate", "eu_ecolabel_licence", "emas_registration", "lca_study",
    "test_report", "supplier_declaration", "internal_measurement", "none_yet",
]
CHANNELS = ["label", "packaging", "advertising", "website", "social_media", "technical_material", "sustainability_report"]
SCOPES = ["whole_product", "part", "packaging", "site", "company"]
COMPARISONS = ["none", "previous_model", "competitor", "industry_average"]
KINDS = ["claim", "cautious", "legal_neutral", "mandatory_statement", "official_info", "financing_statement"]
SLOT_TYPES = ["percent", "number", "year", "date", "id", "choice", "manual"]
SLOT_SOURCES = ["fact_field", "answer", "manual"]
NUMERIC_SLOT_TYPES = {"percent", "number"}

# Rule channel names that a questionnaire channel satisfies.
CHANNEL_ALIASES = {
    "label": {"label", "point_of_sale"},
    "packaging": {"packaging", "point_of_sale"},
    "advertising": {"advertising"},
    "website": {"website"},
    "social_media": {"social_media", "advertising"},
    "technical_material": {"technical_material"},
    "sustainability_report": {"sustainability_report"},
}

PLACEHOLDER_RE = re.compile(r"\[([A-Za-z][A-Za-z0-9_]*)\]")
ANY_BRACKET_RE = re.compile(r"[\[\]]")

# Neutral wording for legal requirements (check 5) and advantage words it may not carry.
NEUTRAL_LEGAL = {
    "en": [r"\bas required by law for all\b", r"\bas required by (regulation|directive) .{0,30}? for all\b"],
    "de": [r"\bwie (gesetzlich )?für alle\b.*\bvorgeschrieben\b", r"\bwie gesetzlich vorgeschrieben für alle\b",
           r"\bwie (es )?die (verordnung|richtlinie) .{0,30}? für alle\b"],
}
ADVANTAGE_WORDS = {
    "en": ["unlike", "stands out", "special", "unique", "exclusive", "advantage", "better", "now", "only our", "best"],
    "de": ["im gegensatz", "besonders", "einzigartig", "exklusiv", "vorteil", "besser", "jetzt", "nur unser", "beste"],
}
LEGAL_AS_FEATURE_RULES = ["P05", "EE01", "DT01", "CS02", "WD01"]

# Literal figures: a number followed by a unit (regulation numbers such as 2025/40 are not figures).
FIGURE_RE = re.compile(
    r"(?<![/\w])\d+(?:[.,]\d+)?\s?(%|kg\b|t\b|g/km|g/kwh|kwh|mwh|years?\b|jahre?n?\b|cycles?\b|zyklen\b|db\b|l/100)", re.I
)


def norm(text: str) -> str:
    t = text.replace(" ", " ").replace("‑", "-").replace("‐", "-").replace("–", "-")
    t = t.replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", t).strip().lower()


def strip_placeholders(text: str) -> str:
    return PLACEHOLDER_RE.sub(" ", text)


_WORD = "a-z0-9äöüß"


@lru_cache(maxsize=8192)
def phrase_pattern(phrase: str, lang: str = "en") -> re.Pattern | None:
    p = norm(phrase)
    if not p or p == "*":
        return None
    esc = re.escape(p).replace(r"\ ", r"\s+")
    if p.startswith("-"):  # suffix trigger such as '-free'
        return re.compile(rf"(?<=[{_WORD}]){esc}(?![{_WORD}])")
    if p.startswith("~"):  # German compound suffix such as 'bleifrei' (written '~frei')
        core = re.escape(p[1:])
        return re.compile(rf"(?<=[{_WORD}]){core}(?:e|en|er|es|em)?(?![{_WORD}])")
    left = rf"(?<![{_WORD}])" if p[0].isalnum() else ""
    if p[-1].isalpha():
        suffix = "(?:s|es)?" if lang == "en" else "(?:e|en|er|es|em|n|s)?"
        right = rf"(?![{_WORD}])"
    elif p[-1].isalnum():
        suffix, right = "", rf"(?![{_WORD}])"
    else:
        suffix, right = "", ""
    return re.compile(left + esc + suffix + right)


def contains_phrase(text: str, phrase: str, lang: str = "en") -> bool:
    pat = phrase_pattern(phrase, lang)
    return bool(pat and pat.search(norm(strip_placeholders(text))))


def placeholders(text: str) -> list[str]:
    return PLACEHOLDER_RE.findall(text)


def placeholders_well_formed(text: str) -> list[str]:
    """Return problems with brackets: every bracket must belong to a [Name] placeholder."""
    rest = PLACEHOLDER_RE.sub("", text)
    return ["stray or malformed bracket"] if ANY_BRACKET_RE.search(rest) else []


def has_figure(text: str) -> bool:
    return bool(FIGURE_RE.search(strip_placeholders(text)))


def numbers_in(text: str) -> list[str]:
    return sorted(re.findall(r"\d+(?:[.,]\d+)?", strip_placeholders(text)))


# ---- templates -----------------------------------------------------------------
class Slot(BaseModel):
    name: str
    type: Literal[tuple(SLOT_TYPES)]  # type: ignore[valid-type]
    source: Literal[tuple(SLOT_SOURCES)]  # type: ignore[valid-type]
    unit: Optional[str] = None
    options: Optional[str] = None  # name of an option list in questionnaire.json
    label: Optional[str] = None


class Requires(BaseModel):
    audience: list[Literal["B2C", "B2B"]]
    channels: list[Literal[tuple(CHANNELS)]]  # type: ignore[valid-type]
    product_domains: list[str]
    evidence_types: list[Literal[tuple(EVIDENCE_TYPES)]]  # type: ignore[valid-type]
    scope: list[Literal[tuple(SCOPES)]]  # type: ignore[valid-type]
    comparison: list[Literal[tuple(COMPARISONS)]]  # type: ignore[valid-type]
    not_domains: list[str] = []  # product domains for which another template takes priority


class Template(BaseModel):
    template_id: str
    topic: str
    text_en: str
    text_de: str = ""
    de_reviewed: bool = False
    specificity: int = Field(ge=1, le=3)
    slots: list[Slot] = []
    requires: Requires
    rule_ids: list[str]
    satisfies: list[str] = []
    applies_from: Optional[str] = None
    valid_until: Optional[str] = None
    origin: str = ""
    notes: str = ""
    kind: Literal[tuple(KINDS)] = "claim"  # type: ignore[valid-type]
    approved: bool = False
    # Optional conditions on answers or facts, e.g. {"method": ["ppwr_adopted"]} or {"excluded": ["*"]}.
    when: dict[str, list[str]] = {}

    def slot(self, name: str) -> Slot | None:
        return next((s for s in self.slots if s.name == name), None)

    def text(self, lang: str) -> str:
        return self.text_de if lang == "de" and self.text_de else self.text_en

    def has_numeric_slot(self) -> bool:
        return any(s.type in NUMERIC_SLOT_TYPES for s in self.slots)


# ---- trigger catalogue: curated status of every trigger phrase ---------------------
@dataclass
class TriggerEntry:
    rule_id: str
    phrase: str
    status: Literal["banned", "conditional", "detector"]
    lift: Optional[str]
    de: list[str]
    severity: str


@dataclass
class Lift:
    lift_id: str
    label: str
    alternatives: list[dict]


@dataclass
class Library:
    templates: dict[str, Template]
    questionnaire: dict
    topic_rules: dict
    dont_say: list[dict]
    lifts: dict[str, Lift]
    curation: dict
    trigger_de: dict[str, list[str]]
    library_hash: str
    catalogue: list[TriggerEntry] = field(default_factory=list)

    def by_topic(self, topic: str) -> list[Template]:
        return [t for t in self.templates.values() if t.topic == topic]


def load_lifts(path: Path = LIBRARY_DIR / "curation" / "lifts.json") -> dict[str, Lift]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: Lift(k, v["label"], v["alternatives"]) for k, v in data["lifts"].items()}


def load_curation(path: Path = LIBRARY_DIR / "curation" / "triggers.json") -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def trigger_status(curation: dict, rule_id: str, phrase: str) -> tuple[str, Optional[str]]:
    """Return (status, lift_id) for a trigger phrase of a rule."""
    key = f"{rule_id}:{phrase}"
    raw = curation.get("rule_overrides", {}).get(key)
    if raw is None:
        if phrase in curation.get("detector", {}):
            raw = curation["detector"][phrase] or "detector"
            if raw != "detector" and not raw.startswith("detector"):
                raw = "detector:" + raw
        else:
            raw = None
            for lift_id, phrases in curation.get("conditional", {}).items():
                if phrase in phrases:
                    raw = f"conditional:{lift_id}"
                    break
            raw = raw or "banned"
    status, _, lift = raw.partition(":")
    return status, (lift or None)


def build_catalogue(rules: Iterable, curation: dict, trigger_de: dict[str, list[str]]) -> list[TriggerEntry]:
    out = []
    for r in rules:
        if r.severity not in ("prohibited", "case_by_case"):
            continue
        for ph in r.triggers:
            if ph == "*":
                continue
            st, lift = trigger_status(curation, r.rule_id, ph)
            out.append(TriggerEntry(r.rule_id, ph, st, lift, trigger_de.get(ph, []), r.severity))
    return out


# ---- lift evaluation -----------------------------------------------------------
def _subset(a: Iterable, b: Iterable) -> bool:
    return set(a) <= set(b)


def lift_holds_for_template(lift: Lift, t: Template) -> bool:
    """True if every context the template can be used in satisfies one alternative."""
    for alt in lift.alternatives:
        ok = True
        if "evidence_types" in alt and not _subset(t.requires.evidence_types, alt["evidence_types"]):
            ok = False
        if "scope" in alt and not _subset(t.requires.scope, alt["scope"]):
            ok = False
        if "comparison" in alt and not _subset(t.requires.comparison, alt["comparison"]):
            ok = False
        if "channels" in alt and not _subset(t.requires.channels, alt["channels"]):
            ok = False
        if "domains" in alt and not _subset(t.requires.product_domains, alt["domains"]):
            ok = False
        if "kinds" in alt and t.kind not in alt["kinds"]:
            ok = False
        if ok:
            return True
    return False


def lift_holds_for_context(lift: Lift, ctx, t: Template | None) -> bool:
    for alt in lift.alternatives:
        ok = True
        if "evidence_types" in alt and ctx.evidence not in alt["evidence_types"]:
            ok = False
        if "scope" in alt and ctx.scope not in alt["scope"]:
            ok = False
        if "comparison" in alt and ctx.comparison not in alt["comparison"]:
            ok = False
        if "channels" in alt and ctx.channel not in alt["channels"]:
            ok = False
        if "domains" in alt and not (set(ctx.domains) & set(alt["domains"])):
            ok = False
        if "kinds" in alt and (t is None or t.kind not in alt["kinds"]):
            ok = False
        if ok:
            return True
    return False


def context_only(lift: Lift) -> bool:
    """True if at least one alternative depends only on the answers, not on the template wording."""
    return any("kinds" not in alt for alt in lift.alternatives)


# ---- loading -------------------------------------------------------------------
def library_hash(path: Path = LIBRARY_DIR) -> str:
    h = hashlib.sha256()
    for name in ["templates.jsonl", "questionnaire.json", "topic_rules.json", "dont_say.jsonl",
                 "curation/lifts.json", "curation/triggers.json", "curation/trigger_de.json"]:
        p = path / name
        if p.exists():
            h.update(name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_templates(path: Path = LIBRARY_DIR / "templates.jsonl") -> dict[str, Template]:
    out: dict[str, Template] = {}
    for row in read_jsonl(path):
        t = Template.model_validate(row)
        if t.template_id in out:
            raise ValueError(f"duplicate template_id {t.template_id}")
        out[t.template_id] = t
    return out


def load_library(path: Path = LIBRARY_DIR, rules=None) -> Library:
    curation = load_curation(path / "curation" / "triggers.json")
    trigger_de = json.loads((path / "curation" / "trigger_de.json").read_text(encoding="utf-8"))
    lib = Library(
        templates=load_templates(path / "templates.jsonl"),
        questionnaire=json.loads((path / "questionnaire.json").read_text(encoding="utf-8")),
        topic_rules=json.loads((path / "topic_rules.json").read_text(encoding="utf-8")) if (path / "topic_rules.json").exists() else {},
        dont_say=read_jsonl(path / "dont_say.jsonl"),
        lifts=load_lifts(path / "curation" / "lifts.json"),
        curation=curation,
        trigger_de=trigger_de,
        library_hash=library_hash(path),
    )
    if rules is not None:
        lib.catalogue = build_catalogue(rules, curation, trigger_de)
    return lib


@lru_cache(maxsize=1)
def get_library() -> Library:
    from .knowledge import get_knowledge

    return load_library(rules=get_knowledge().rules.values())
