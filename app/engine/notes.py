"""Steps 7 and 8: future notes and notes from gates. Future law never changes a recommendation."""
from __future__ import annotations

from datetime import date

from ..knowledge import FUTURE_ROLES, Knowledge
from ..library import Library, contains_phrase
from .context import Context

PREFIX = "Possible future requirement (not law):"


def _fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B')} {d.year}"


def future_watch_notes(ctx: Context, kb: Knowledge, lib: Library, sentences: list[str]) -> list[dict]:
    if not ctx.b2c:
        return []
    topic_fw = set(lib.topic_rules["topics"].get(ctx.topic or "", {}).get("future_rules", []))
    out = []
    for r in kb.rules.values():
        if r.scope.routing != "future_watch":
            continue
        hit = r.rule_id in topic_fw
        if not hit and "*" in r.triggers and sentences:
            hit = True
        if not hit:
            hit = any(contains_phrase(s, p, "en") for s in sentences for p in r.triggers if p != "*")
        if not hit:
            continue
        srcs = [{"doc_title": q.chunk.doc_title, "locator": q.chunk.locator, "role": q.role, "quote": q.quote,
                 "chunk_id": q.chunk.chunk_id, "legal_status": "Not law"}
                for q in kb.quotes.get(r.rule_id, []) if q.role in FUTURE_ROLES or q.chunk.collection == "future_law"]
        out.append({"type": "future_watch", "rule_id": r.rule_id, "title": r.title,
                    "text": f"{PREFIX} {r.requirement}",
                    "positions": [p.model_dump() for p in r.positions], "sources": srcs[:3]})
    return out


def adopted_future_notes(ctx: Context, kb: Knowledge, future_matches) -> list[dict]:
    """Rules adopted but not yet applicable on the use date, and the templates that will only fit from then."""
    out = []
    relevant = set(ctx.future_dated)
    for rid in sorted(relevant):
        r = kb.rules[rid]
        tpls = [m.template for m in future_matches if rid in m.template.rule_ids]
        out.append({"type": "not_yet_applicable", "rule_id": rid, "title": r.title, "applies_from": r.scope.applies_from,
                    "text": f"{PREFIX} from {_fmt_date(r.scope.applies_from)} — {r.requirement}",
                    "positions": [], "template_previews": [{"template_id": t.template_id, "text": t.text(ctx.language)} for t in tpls]})
    # templates that are future only because of their own applies_from
    for m in future_matches:
        t = m.template
        if not any(t.template_id in [p["template_id"] for p in n["template_previews"]] for n in out):
            out.append({"type": "not_yet_applicable", "rule_id": t.rule_ids[0], "title": kb.rules[t.rule_ids[0]].title,
                        "applies_from": t.applies_from,
                        "text": f"{PREFIX} wording that becomes available from {_fmt_date(t.applies_from)}.",
                        "positions": [], "template_previews": [{"template_id": t.template_id, "text": t.text(ctx.language)}]})
    return out


def dfa_notes(rule_ids: list[str], kb: Knowledge) -> list[dict]:
    out, seen = [], set()
    for rid in rule_ids:
        for row in kb.dfa_rows(rid):
            key = (row["current_provision"], row["dfa_provision"])
            if key in seen:
                continue
            seen.add(key)
            out.append({"type": "digital_fairness_act", "rule_id": rid, "title": row["topic"],
                        "text": f"{PREFIX} under the Digital Fairness Act proposal, {row['current_provision']} would move to "
                                f"{row['dfa_provision']} ({row['change'].strip() or 'see proposal'}).",
                        "positions": [], "dfa_chunk_id": row["dfa_chunk_id"]})
    return out


def gate_notes(ctx: Context, kb: Knowledge) -> None:
    if ctx.on_market_before == "yes" and "G04" in ctx.candidates:
        ctx.note("info", kb.rules["G04"].requirement, "G04")
    if "PK01" in ctx.candidates and ctx.method != "ppwr_adopted" and ctx.topic in (
            "recycled_content", "recyclability", "compostable", "packaging_reduction"):
        ctx.human_review = True
        ctx.note("review", "Human review required: no PPWR calculation method has been adopted for this packaging property yet, "
                           "so the claim cannot yet be checked against the PPWR criteria (rule PK01).", "PK01")
    if "TY01" in ctx.candidates:
        ctx.note("info", "Show the EU tyre label with any visual advertisement or technical material for a specific tyre type (rule TY01).", "TY01")
    if "RP05" in ctx.candidates and ctx.topic == "reporting_status":
        ctx.note("review", kb.rules["RP05"].notes or "", "RP05")
        ctx.human_review = True
    for rid in ("CR03",):
        if rid in ctx.candidates and ctx.topic in ("climate_neutral_or_offset", "carbon_removal") and kb.rules[rid].notes:
            ctx.note("review", kb.rules[rid].notes, rid)
