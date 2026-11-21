"""Step 1: validate the answers and route them to the candidate rules."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from ..knowledge import Knowledge
from ..library import CHANNEL_ALIASES, Library


class AnswerError(ValueError):
    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


@dataclass
class Context:
    answers: dict
    segment: str | None = None
    product_type: str | None = None
    subject: str = "unknown"
    audience_answer: str = "consumers"
    audiences: list[str] = field(default_factory=lambda: ["B2C"])
    channel: str = "advertising"
    topic: str | None = None
    scope: str | None = None
    part: str | None = None
    excluded: str | None = None
    evidence: str | None = None
    method: str | None = None
    reference_year: str | None = None
    facts: dict = field(default_factory=dict)
    comparison: str = "none"
    use_date: str = field(default_factory=lambda: date.today().isoformat())
    on_market_before: str = "unknown"
    language: str = "en"
    tone: str = "factual"
    domains: set = field(default_factory=set)
    product_rules: list[str] = field(default_factory=list)
    topic_rules: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    future_dated: list[str] = field(default_factory=list)
    excluded_rules: dict = field(default_factory=dict)  # rule_id -> reason
    notes: list[dict] = field(default_factory=list)
    human_review: bool = False
    manual_review: bool = False
    log: list[str] = field(default_factory=list)

    @property
    def b2c(self) -> bool:
        return "B2C" in self.audiences

    @property
    def goods(self) -> bool:
        return self.subject in ("product", "unknown")

    def value(self, key: str):
        """Value used by template `when` conditions."""
        if key in ("method", "excluded", "part", "scope", "evidence", "comparison", "channel", "segment", "product_type"):
            return getattr(self, key)
        return self.facts.get(key)

    def note(self, kind: str, text: str, rule_id: str | None = None):
        n = {"kind": kind, "text": text, "rule_id": rule_id}
        if n not in self.notes:
            self.notes.append(n)


# ---------------------------------------------------------------------------------------------
def _ids(options: list[dict]) -> set[str]:
    return {o["id"] for o in options}


def segment_options(kb: Knowledge, lib: Library) -> list[dict]:
    q = lib.questionnaire
    out = [{"id": r["eclass_segment"], "label_en": f"{r['eclass_segment']} · {r['segment_name']}",
            "segment_name": r["segment_name"], "note": r["note"] or None,
            "subject": "service" if r["eclass_segment"] in q["service_segments"] else "product",
            "manual_review": r["eclass_segment"] in q["manual_review_segments"]}
           for r in kb.eclass]
    out += [{"id": o["id"], "label_en": o["label_en"], "subject": o["subject"], "note": None,
             "manual_review": o["id"] == "not_sure"} for o in q["extra_products"]]
    return out


def subject_of(seg: str | None, lib: Library) -> str:
    q = lib.questionnaire
    if seg == "company":
        return "company"
    if seg in (None, "not_sure") or seg in q["manual_review_segments"]:
        return "unknown"
    if seg in q["service_segments"]:
        return "service"
    return "product"


def parts_for(domains: set, lib: Library) -> list[dict]:
    q = lib.questionnaire
    for d in q["parts_priority"]:
        if d in domains:
            return q["parts"][d]
    return q["parts"]["default"]


def method_label(lib: Library, topic: str | None, method: str | None, lang: str) -> str | None:
    if not (topic and method):
        return None
    for m in lib.questionnaire["topics"].get(topic, {}).get("methods", []):
        if m["id"] == method:
            key = "de" if lang == "de" else "en"
            return m.get(f"fill_{key}") or m[f"label_{key}"]
    return None


def topic_fact_fields(ctx: Context, lib: Library, kb: Knowledge) -> list[dict]:
    q = lib.questionnaire
    fields = list(q["topics"].get(ctx.topic, {}).get("facts", [])) if ctx.topic else []
    for dom, rule_id in q["domain_facts_rules"].items():
        if dom in ctx.domains and rule_id in ctx.candidates:
            fields += q["domain_facts"][dom]
    seen, out = set(), []
    for f in fields:
        if f["name"] not in seen:
            seen.add(f["name"])
            out.append(f)
    return out


def available_topics(ctx: Context, lib: Library) -> list[str]:
    out = []
    for tid, t in lib.questionnaire["topics"].items():
        if ctx.subject not in t["subjects"]:
            continue
        if t["domains"] and not (set(t["domains"]) & ctx.domains):
            continue
        if not set(t["audiences"]) & set(ctx.audiences):
            continue
        out.append(tid)
    return out


def scope_options(ctx: Context, lib: Library) -> list[str]:
    q = lib.questionnaire
    allowed = set(q["subject_scopes"][ctx.subject])
    tscopes = q["topics"].get(ctx.topic, {}).get("scopes", [s["id"] for s in q["scope"]])
    return [s for s in tscopes if s in allowed]


def evidence_options(ctx: Context, lib: Library) -> list[str]:
    t = lib.questionnaire["topics"].get(ctx.topic or "", {})
    if not t:
        return [e["id"] for e in lib.questionnaire["evidence"]]
    if ctx.b2c and t.get("evidence_b2c"):
        return t["evidence_b2c"]
    return t["evidence"]


# ---------------------------------------------------------------------------------------------
def validate_fact(fdef: dict, raw, lib: Library) -> str:
    """Return the cleaned value or raise ValueError. Only short structured values are accepted."""
    if raw is None:
        raise ValueError("empty")
    v = str(raw).strip()
    if not v:
        raise ValueError("empty")
    typ = fdef["type"]
    pats = lib.questionnaire["patterns"]
    if typ == "choice":
        opts = lib.questionnaire["option_lists"].get(fdef.get("options", ""), [])
        if v not in _ids(opts):
            raise ValueError("not one of the listed choices")
        return v
    if typ not in pats:
        raise ValueError(f"unsupported field type {typ}")
    if not re.fullmatch(pats[typ], v):
        raise ValueError(f"does not match the {typ} format")
    if typ == "percent" and not (0 <= float(v) <= 100):
        raise ValueError("must be between 0 and 100")
    if typ == "number":
        v = v.replace(",", ".")
    return v


def build_context(answers: dict, kb: Knowledge, lib: Library, partial: bool = False) -> Context:
    """Validate answers and route. With partial=True missing answers are allowed (live summary)."""
    q = lib.questionnaire
    a = dict(answers or {})
    errs: dict[str, str] = {}
    ctx = Context(answers=a)

    seg = a.get("segment")
    seg_ids = {r["eclass_segment"] for r in kb.eclass} | _ids(q["extra_products"])
    if seg is not None and str(seg) not in seg_ids:
        errs["segment"] = "unknown segment"
        seg = None
    ctx.segment = str(seg) if seg is not None else None
    ctx.subject = subject_of(ctx.segment, lib)
    ctx.manual_review = ctx.segment in (["not_sure"] + q["manual_review_segments"])

    refinements = q["segment_refinements"].get(ctx.segment or "", [])
    pt = a.get("product_type")
    if refinements:
        if pt is not None and pt not in _ids(refinements):
            errs["product_type"] = "unknown product type for this segment"
            pt = None
    else:
        pt = None
    ctx.product_type = pt

    aud = a.get("audience", "consumers" if partial else None)
    if aud not in _ids(q["audience"]):
        if aud is not None or not partial:
            errs["audience"] = "choose consumers, businesses only or both"
        aud = "consumers"
    ctx.audience_answer = aud
    ctx.audiences = list(next(o for o in q["audience"] if o["id"] == aud)["audiences"])

    ch = a.get("channel", None)
    if ch is not None and ch not in _ids(q["channel"]):
        errs["channel"] = "unknown channel"
        ch = None
    if ch is None and not partial:
        errs.setdefault("channel", "required")
    ctx.channel = ch or "advertising"
    if ch in q["public_channels"] and "B2C" not in ctx.audiences:
        ctx.audiences = ["B2C", "B2B"]
        ctx.note("info", "A public website or social media post also reaches consumers, so the consumer rules apply as well (rule G02).", "G02")

    # ---- product rules and domains
    if not ctx.manual_review and ctx.subject in ("product", "service"):
        seg_rules = kb.segment_rule_ids(ctx.segment)
        keep_domains = None
        if refinements and ctx.product_type:
            keep_domains = set(next(o for o in refinements if o["id"] == ctx.product_type)["domains"])
        for rid in seg_rules:
            rd = set(kb.rules[rid].scope.product_domains)
            if keep_domains is not None and not (rd & (keep_domains | {"ALL", "ALL_GOODS"})):
                ctx.excluded_rules[rid] = "not relevant for the chosen product type"
                continue
            ctx.product_rules.append(rid)
        for rid in ctx.product_rules:
            ctx.domains |= set(kb.rules[rid].scope.product_domains) - {"ALL", "ALL_GOODS"}
        if keep_domains is not None:
            ctx.domains |= keep_domains
    ctx.domains |= {"ALL"}
    if ctx.goods:
        ctx.domains.add("ALL_GOODS")

    # ---- topic, scope, part
    topic = a.get("topic")
    if topic is not None and topic not in q["topics"]:
        errs["topic"] = "unknown topic"
        topic = None
    ctx.topic = topic
    if topic and topic not in available_topics(ctx, lib):
        errs["topic"] = "this topic does not fit the product and audience"
    if topic is None and not partial:
        errs.setdefault("topic", "required")

    scope = a.get("scope")
    if scope is not None:
        if scope not in _ids(q["scope"]) or (topic and scope not in scope_options(ctx, lib)):
            errs["scope"] = "this scope does not fit the topic"
            scope = None
    if scope is None and not partial:
        errs.setdefault("scope", "required")
    ctx.scope = scope
    if scope == "packaging" or (topic and q["topics"][topic].get("implies_packaging")):
        ctx.domains.add("PACKAGING")

    part_opts = parts_for(ctx.domains if scope != "packaging" else {"PACKAGING"}, lib)
    for key in ("part", "excluded"):
        v = a.get(key)
        if v in (None, "", "none"):
            continue
        if v not in _ids(part_opts) or scope not in ("part", "packaging", "whole_product"):
            errs[key] = "choose a part from the list"
            continue
        setattr(ctx, key, v)
    if ctx.excluded and ctx.excluded == ctx.part:
        errs["excluded"] = "the excluded part cannot be the covered part"
        ctx.excluded = None

    # ---- topic claim-object rules
    if topic:
        tr = lib.topic_rules["topics"][topic]
        ctx.topic_rules = list(tr["claim_object_rules"])
        if "PACKAGING" in ctx.domains:
            ctx.topic_rules += [r for r in tr["claim_object_rules_if_packaging"] if r not in ctx.topic_rules]

    # ---- evidence
    ev = a.get("evidence")
    if ev is not None and ev not in evidence_options(ctx, lib):
        errs["evidence"] = "this evidence type is not offered for the topic"
        ev = None
    if ev is None and not partial:
        errs.setdefault("evidence", "required")
    ctx.evidence = ev or "none_yet"
    m = a.get("method")
    if m not in (None, ""):
        if topic and m not in {x["id"] for x in q["topics"][topic]["methods"]}:
            errs["method"] = "unknown method for the topic"
        else:
            ctx.method = m
    ry = a.get("reference_year")
    if ry not in (None, ""):
        if re.fullmatch(q["patterns"]["year"], str(ry)):
            ctx.reference_year = str(ry)
        else:
            errs["reference_year"] = "use a four-digit year"

    comp = a.get("comparison") or "none"
    if comp not in _ids(q["comparison"]):
        errs["comparison"] = "unknown comparison"
        comp = "none"
    if comp != "none" and topic and not q["topics"][topic]["comparable"]:
        comp = "none"
    ctx.comparison = comp

    d = a.get("use_date") or date.today().isoformat()
    if not re.fullmatch(q["patterns"]["date"], str(d)):
        errs["use_date"] = "use the format YYYY-MM-DD"
        d = date.today().isoformat()
    ctx.use_date = str(d)
    omb = a.get("on_market_before") or "unknown"
    if omb not in _ids(q["on_market_before"]):
        errs["on_market_before"] = "choose yes, no or unknown"
        omb = "unknown"
    ctx.on_market_before = omb
    lang = a.get("language") or "en"
    ctx.language = lang if lang in ("en", "de") else "en"
    tone = a.get("tone") or "factual"
    ctx.tone = tone if tone in _ids(q["tone"]) else "factual"

    # ---- candidate rules
    route_rules(ctx, kb)

    # ---- facts (validated after routing, because domain facts depend on candidate rules)
    fields = {f["name"]: f for f in topic_fact_fields(ctx, lib, kb)}
    for k, v in (a.get("facts") or {}).items():
        if v in (None, ""):
            continue
        if k not in fields:
            errs[f"facts.{k}"] = "unknown fact field"
            continue
        try:
            ctx.facts[k] = validate_fact(fields[k], v, lib)
        except ValueError as e:
            errs[f"facts.{k}"] = str(e)

    if errs and not partial:
        raise AnswerError(errs)
    if errs:
        ctx.log += [f"answer {k}: {v}" for k, v in errs.items()]
    return ctx


def rule_channel_ok(rule, channel: str) -> bool:
    ch = set(rule.scope.channels)
    return "any" in ch or bool(ch & CHANNEL_ALIASES.get(channel, {channel}))


def rule_domain_ok(rule, ctx: Context) -> bool:
    rd = set(rule.scope.product_domains)
    if "ALL" in rd:
        return True
    if "ALL_GOODS" in rd:
        return ctx.goods
    return bool(rd & ctx.domains)


def route_rules(ctx: Context, kb: Knowledge) -> None:
    pool = [r.rule_id for r in kb.rules.values() if r.scope.routing == "all"]
    pool += [r for r in ctx.product_rules if r not in pool]
    pool += [r for r in ctx.topic_rules if r not in pool]
    ctx.candidates, ctx.future_dated = [], []
    for rid in pool:
        r = kb.rules[rid]
        if not set(r.audience) & set(ctx.audiences):
            ctx.excluded_rules[rid] = "audience"
            continue
        if not rule_domain_ok(r, ctx):
            ctx.excluded_rules[rid] = "product domain"
            continue
        if not rule_channel_ok(r, ctx.channel):
            ctx.excluded_rules[rid] = "channel"
            continue
        if r.scope.applies_from and r.scope.applies_from > ctx.use_date:
            ctx.future_dated.append(rid)
            continue
        ctx.candidates.append(rid)
    if ctx.manual_review:
        ctx.human_review = True
        ctx.note("review", "The product segment is unknown or interim (segment 90), so only the general and topic rules were checked. "
                           "A person must check the product-specific rules.", None)
