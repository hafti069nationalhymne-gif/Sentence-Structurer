"""Step 2: select and rank templates for the context."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..knowledge import Knowledge
from ..library import Library, Template
from .context import Context

KIND_SAFETY = {"cautious": 0, "legal_neutral": 1, "official_info": 2, "financing_statement": 3, "mandatory_statement": 4, "claim": 5}


@dataclass
class Match:
    template: Template
    ok: bool
    future: bool = False          # matches, but applies only from a later date
    reasons: list[str] = field(default_factory=list)
    cited_rules: list[str] = field(default_factory=list)


def requires_match(t: Template, ctx: Context) -> list[str]:
    r = t.requires
    why = []
    if ctx.b2c and "B2C" not in r.audience:
        why.append("audience")
    if not ctx.b2c and "B2B" not in r.audience:
        why.append("audience")
    if ctx.channel not in r.channels:
        why.append("channel")
    if "ALL" not in r.product_domains and not (set(r.product_domains) & ctx.domains):
        why.append("product domain")
    if set(r.not_domains) & ctx.domains:
        why.append("another template covers this product domain")
    if ctx.evidence not in r.evidence_types:
        why.append("evidence")
    if ctx.scope not in r.scope:
        why.append("scope")
    if ctx.comparison not in r.comparison:
        why.append("comparison")
    for key, vals in t.when.items():
        v = ctx.value(key)
        if vals == ["*"]:
            if not v:
                why.append(f"needs {key}")
        elif v not in vals:
            why.append(f"{key} is {v or 'not given'}")
    return why


def match_template(t: Template, ctx: Context, kb: Knowledge) -> Match:
    why = requires_match(t, ctx)
    future = False
    cited = []
    for rid in t.rule_ids:
        if rid in ctx.candidates:
            cited.append(rid)
        elif rid in ctx.future_dated:
            future = True
        elif ctx.excluded_rules.get(rid) == "audience" or not set(kb.rules[rid].audience) & set(ctx.audiences):
            continue  # the rule does not apply to this audience; it is simply not cited
        elif t.kind == "mandatory_statement":
            continue  # a mandatory statement needs only one of its rules to apply
        else:
            why.append(f"rule {rid} does not apply")
    if not cited and not future:
        why.append("no linked rule applies")
    if t.applies_from and t.applies_from > ctx.use_date:
        future = True
    return Match(t, ok=not why, future=future and not why, reasons=why, cited_rules=cited)


def rank_key(m: Match, ctx: Context):
    t = m.template
    ev = t.requires.evidence_types
    fit = ev.index(ctx.evidence) if ctx.evidence in ev else 99
    spec = t.specificity if ctx.evidence == "none_yet" else -t.specificity
    return (fit, spec, KIND_SAFETY.get(t.kind, 9), t.template_id)


def safety_key(m: Match):
    t = m.template
    return (t.specificity, KIND_SAFETY.get(t.kind, 9), len(t.slots), t.template_id)


def select(ctx: Context, lib: Library, kb: Knowledge) -> tuple[list[Match], list[Match], list[Match]]:
    """Return (ranked usable matches, future-only matches, rejected matches) for the topic."""
    usable, future, rejected = [], [], []
    for t in lib.by_topic(ctx.topic or ""):
        m = match_template(t, ctx, kb)
        if m.ok and not m.future:
            usable.append(m)
        elif m.future:
            future.append(m)
        else:
            rejected.append(m)
    usable.sort(key=lambda m: rank_key(m, ctx))
    return usable, future, rejected


def mandatory_appends(ctx: Context, lib: Library, kb: Knowledge) -> tuple[list[Match], list[Match]]:
    """Mandatory statements that fit the context, and those whose rule applies but which cannot be filled."""
    ok, missing = [], []
    for t in lib.by_topic("_mandatory"):
        m = match_template(t, ctx, kb)
        if m.ok and not m.future:
            ok.append(m)
        elif all(r in ctx.candidates for r in t.rule_ids[:1]) and not t.when:
            missing.append(m)
    return ok, missing


def choose(usable: list[Match], ctx: Context, n_max: int = 4) -> list[Match]:
    """2 to 4 recommendations that always include the safest option. 'None yet' gives at most one."""
    if not usable:
        return []
    safest = min(usable, key=safety_key)
    if ctx.evidence == "none_yet":
        return [safest]
    picked = usable[:3]
    if safest not in picked:
        picked.append(safest)
    return picked[:n_max]
