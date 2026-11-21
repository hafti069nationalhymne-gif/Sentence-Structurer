"""The loader validates all passages and rules, and every basis quote is found word for word."""
from app.knowledge import EXPECTED_CHUNKS, EXPECTED_RULES, load_knowledge


def test_counts(kb):
    assert len(kb.chunks) == EXPECTED_CHUNKS == 1166
    assert len(kb.rules) == EXPECTED_RULES == 94


def test_all_basis_quotes_verified(kb):
    assert kb.quote_failures == []
    total = sum(len(r.basis) for r in kb.rules.values())
    assert total == sum(len(v) for v in kb.quotes.values()) == 323
    for rid, quotes in kb.quotes.items():
        for q in quotes:
            assert q.quote in q.chunk.text
            assert q.chunk.parent_id == q.parent_id


def test_basis_chunk_is_parent_and_all_parts_loaded(kb):
    parts = kb.parent_parts("PPWR-ART-003-01")
    assert len(parts) == 15
    assert [p.part_no for p in parts] == list(range(1, 16))


def test_known_traps(kb):
    sev = {r.severity for r in kb.rules.values()}
    assert sev == {"gate", "prohibited", "case_by_case", "evidence", "info", "future"}
    assert {r.scope.routing for r in kb.rules.values()} == {"all", "eclass", "claim_object", "future_watch"}
    assert kb.rules["E01"].triggers == [] and kb.rules["B01"].triggers == []
    assert kb.rules["FW01"].triggers == ["*"] and kb.rules["FW02"].triggers == ["*"]


def test_routing_tables_reference_real_rules(kb):
    assert kb.segment("46") is not None
    assert "PK01" in kb.claim_object_rule_ids("packaging")
    assert kb.german_counterparts("EMPCO-UCPD-ART2-P")


def test_strict_counts_detect_missing_records(tmp_path, kb):
    src = kb  # noqa: F841
    from app.config import KNOWLEDGE_DIR
    import shutil
    d = tmp_path / "data"
    shutil.copytree(KNOWLEDGE_DIR, d)
    lines = (d / "rules.jsonl").read_text(encoding="utf-8").splitlines()
    (d / "rules.jsonl").write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    import pytest
    with pytest.raises(ValueError):
        load_knowledge(d)


def test_bm25_search_finds_passages(kb):
    res = kb.search("recycled content packaging", k=5)
    assert res and all(c.collection != "future_law" for c, _ in res)
