"""Step 3: fill template slots from the answers and fact fields. Missing values stay as placeholders."""
from __future__ import annotations

import re

from ..library import Library, Template, PLACEHOLDER_RE
from .context import Context, method_label, parts_for


def _option_label(lib: Library, list_name: str | None, value: str, lang: str) -> str | None:
    for o in lib.questionnaire["option_lists"].get(list_name or "", []):
        if o["id"] == value:
            return o["label_de" if lang == "de" else "label_en"]
    return None


def _part_label(lib: Library, ctx: Context, value: str | None, lang: str) -> str | None:
    if not value:
        return None
    pools = [parts_for(ctx.domains, lib), lib.questionnaire["parts"]["PACKAGING"]]
    for pool in pools:
        for o in pool:
            if o["id"] == value:
                return o["label_de" if lang == "de" else "label_en"].lower() if lang == "en" else o["label_de"]
    return None


def format_number(v: str, lang: str) -> str:
    if lang == "de":
        return v.replace(".", ",")
    return v


def slot_values(t: Template, ctx: Context, lib: Library, lang: str, overrides: dict | None = None) -> dict[str, str]:
    """Values for the template's slots. `overrides` are inline chip edits (already validated)."""
    q = lib.questionnaire
    facts = dict(ctx.facts)
    if overrides:
        facts.update({k: v for k, v in overrides.items() if v not in (None, "")})
    out: dict[str, str] = {}
    for s in t.slots:
        v = None
        if s.source == "answer":
            if s.name == "component":
                v = _part_label(lib, ctx, facts.get("component") or ctx.part, lang)
                if v is None and ctx.scope in ("whole_product", "packaging") and "PACKAGING" in ctx.domains:
                    v = "Verpackungseinheit" if lang == "de" else "packaging unit"
            elif s.name == "excluded":
                v = _part_label(lib, ctx, facts.get("excluded") or ctx.excluded, lang)
            elif s.name == "method":
                v = method_label(lib, ctx.topic if t.topic != "_mandatory" else None, ctx.method, lang)
            elif s.name == "year":
                v = facts.get("year") or ctx.reference_year
            elif s.name == "comparator":
                fill = q["comparator_fill"].get(ctx.comparison)
                v = fill[lang] if fill else None
        elif s.source == "fact_field":
            raw = facts.get(s.name)
            if raw not in (None, ""):
                if s.type == "choice":
                    v = _option_label(lib, s.options, raw, lang)
                elif s.type in ("percent", "number"):
                    v = format_number(str(raw), lang)
                else:
                    v = str(raw)
        if v:
            out[s.name] = v
    return out


def fill_text(text: str, values: dict[str, str]) -> str:
    def rep(m: re.Match) -> str:
        return values.get(m.group(1), m.group(0))

    filled = PLACEHOLDER_RE.sub(rep, text)
    # Sentence start after filling, e.g. "[model]: ..." stays as given; capitalise a lower-case first letter.
    if filled and filled[0].islower():
        filled = filled[0].upper() + filled[1:]
    return filled


def remaining_placeholders(text: str) -> list[str]:
    return list(dict.fromkeys(PLACEHOLDER_RE.findall(text)))
