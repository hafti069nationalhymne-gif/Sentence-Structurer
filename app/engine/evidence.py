"""Step 5: collect the verified legal basis for a recommendation."""
from __future__ import annotations

from ..knowledge import FUTURE_ROLES, LEGAL_STATUS, Knowledge

ROLE_ORDER = {"primary": 0, "german_law": 1, "case_law": 2, "interpretation": 3}


def regulations_for(rule_ids: list[str], kb: Knowledge, max_per_rule: int = 3) -> list[dict]:
    out = []
    for rid in rule_ids:
        rule = kb.rules[rid]
        quotes = [q for q in kb.quotes.get(rid, [])
                  if q.role not in FUTURE_ROLES and q.chunk.collection not in ("future_law", "reference_only")]
        quotes.sort(key=lambda q: (ROLE_ORDER.get(q.role, 9), q.chunk.authority_rank))
        for q in quotes[:max_per_rule]:
            c = q.chunk
            gc = None
            if c.jurisdiction == "EU":
                rows = kb.german_counterparts(c.parent_id) or kb.german_counterparts(c.chunk_id)
                if rows:
                    row = rows[0]
                    gchunk = kb.chunks.get(row["german_chunk_id"]) or next(iter(kb.parent_parts(row["german_chunk_id"])), None)
                    gc = {"provision": row["german_provision"], "chunk_id": row["german_chunk_id"],
                          "doc_title": gchunk.doc_title if gchunk else None}
            out.append({
                "rule_id": rid, "rule_title": rule.title, "doc_title": c.doc_title, "locator": c.locator,
                "jurisdiction": c.jurisdiction, "legal_status": LEGAL_STATUS.get(c.source_type, c.source_type),
                "quote": q.quote, "chunk_id": c.chunk_id, "caution": c.caution, "german_counterpart": gc,
                "role": q.role, "currency": c.currency, "language": c.language,
            })
    return out


def sources_for_rule(rule_id: str, kb: Knowledge, include_future: bool = False) -> list[dict]:
    """Full passages behind a rule, for the 'Show sources' view."""
    rule = kb.rules[rule_id]
    out = []
    for q in kb.quotes.get(rule_id, []):
        if not include_future and (q.role in FUTURE_ROLES or q.chunk.collection == "future_law"):
            continue
        parts = kb.parent_parts(q.parent_id)
        out.append({
            "rule_id": rule_id, "rule_title": rule.title, "role": q.role, "quote": q.quote,
            "chunk_id": q.chunk.chunk_id, "parent_id": q.parent_id, "doc_title": q.chunk.doc_title,
            "locator": q.chunk.locator, "jurisdiction": q.chunk.jurisdiction,
            "legal_status": LEGAL_STATUS.get(q.chunk.source_type, q.chunk.source_type),
            "caution": q.chunk.caution, "currency": q.chunk.currency,
            "text": "\n\n".join(p.text for p in parts),
        })
    return out
