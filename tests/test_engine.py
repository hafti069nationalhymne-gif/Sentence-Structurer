"""Engine properties: never a 'Don't say' match, future law only as notes, deterministic, figures need evidence."""
import random

import pytest

from app.engine.context import AnswerError, available_topics, build_context, evidence_options, scope_options, topic_fact_fields
from app.engine.recommend import recommend, revalidate
from app.engine.validate import entry_hits
from app.library import has_figure
from conftest import segment_with

FILL = {"percent": "40", "number": "12.5", "year": "2025", "date": "2026-06-30", "id": "ABC-123"}


def fill_facts(ctx, lib, kb):
    facts = {}
    for f in topic_fact_fields(ctx, lib, kb):
        if f["type"] == "choice":
            facts[f["name"]] = lib.questionnaire["option_lists"][f["options"]][0]["id"]
        else:
            facts[f["name"]] = FILL[f["type"]]
    return facts


def sample_answers(kb, lib, n=700, seed=7):
    """A deterministic sample across segments, product types, audiences, channels, topics, scopes and evidence."""
    rnd = random.Random(seed)
    q = lib.questionnaire
    segs = [r["eclass_segment"] for r in kb.eclass] + ["company", "not_sure"]
    out = []
    while len(out) < n:
        seg = rnd.choice(segs)
        refs = q["segment_refinements"].get(seg, [])
        a = {"segment": seg, "audience": rnd.choice(["consumers", "business", "both"]),
             "channel": rnd.choice([c["id"] for c in q["channel"]]),
             "use_date": rnd.choice(["2026-11-21", "2030-06-01", "2031-01-01"]),
             "language": rnd.choice(["en", "de"]), "on_market_before": rnd.choice(["yes", "no", "unknown"])}
        if refs:
            a["product_type"] = rnd.choice(refs)["id"]
        ctx = build_context(a, kb, lib, partial=True)
        topics = available_topics(ctx, lib)
        if not topics:
            continue
        a["topic"] = rnd.choice(topics)
        ctx = build_context(a, kb, lib, partial=True)
        a["scope"] = rnd.choice(scope_options(ctx, lib))
        ctx = build_context(a, kb, lib, partial=True)
        if a["scope"] in ("part", "packaging"):
            from app.engine.context import parts_for
            parts = parts_for({"PACKAGING"} if a["scope"] == "packaging" else ctx.domains, lib)
            a["part"] = rnd.choice(parts)["id"]
            if rnd.random() < .3:
                others = [p["id"] for p in parts if p["id"] != a["part"]]
                a["excluded"] = rnd.choice(others)
        a["evidence"] = rnd.choice(evidence_options(ctx, lib))
        methods = q["topics"][a["topic"]]["methods"]
        if methods and rnd.random() < .8:
            a["method"] = rnd.choice(methods)["id"]
        if q["topics"][a["topic"]]["comparable"]:
            a["comparison"] = rnd.choice(["none", "previous_model", "competitor", "industry_average"])
        ctx = build_context(a, kb, lib, partial=True)
        if rnd.random() < .85:
            a["facts"] = fill_facts(ctx, lib, kb)
            if a["evidence"] == "none_yet":
                a["facts"] = {k: v for k, v in a["facts"].items() if not v[0].isdigit() and k != "ID"}
        a["reference_year"] = "2025"
        out.append(a)
    return out


@pytest.fixture(scope="module")
def sweep(kb, lib):
    from app.config import Settings
    s = Settings(ollama_enabled=False)
    return [(a, recommend(a, kb, lib, s)) for a in sample_answers(kb, lib)]


def test_sweep_produces_recommendations(sweep):
    with_recs = sum(1 for _, r in sweep if r["recommendations"])
    assert with_recs > len(sweep) * 0.5


def test_never_returns_a_dont_say_match(sweep, lib, kb):
    by_id = {e["id"]: e for e in lib.dont_say}
    for a, res in sweep:
        for rec in res["recommendations"]:
            for d in res["dont_say"]:
                e = by_id[d["id"]]
                assert not entry_hits(e, rec["sentence"], rec["language"]), (a, rec["sentence"], d)
            # banned wording of every applicable rule, displayed or not, never appears
            for e in lib.dont_say:
                if e["status"] == "banned" and e["rule_id"] in res["context"]["candidate_rules"] and e["match"] != "none":
                    af = e.get("applies_from")
                    if af and af > res["context"]["use_date"]:
                        continue
                    assert not entry_hits(e, rec["sentence"], rec["language"]), (a, rec["sentence"], e["phrase_en"])


def test_future_law_only_in_notes(sweep, kb):
    for a, res in sweep:
        future_dated = set(res["context"]["future_dated_rules"])
        for rec in res["recommendations"]:
            assert not any(kb.rules[r].scope.routing == "future_watch" for r in rec["rule_ids"])
            assert not (set(rec["rule_ids"]) & future_dated)
            for g in rec["regulations"]:
                assert kb.chunks[g["chunk_id"]].collection not in ("future_law", "reference_only")
        assert not any(kb.rules[d["rule_id"]].scope.routing == "future_watch" for d in res["dont_say"])
        for f in res["future_requirements"]:
            assert f["text"].startswith("Possible future requirement (not law):")


def test_none_yet_never_gives_figures(sweep):
    n = 0
    for a, res in sweep:
        if a.get("evidence") != "none_yet":
            continue
        n += 1
        assert len(res["recommendations"]) <= 1
        assert res["human_review_required"]
        for rec in res["recommendations"]:
            assert not has_figure(rec["sentence"]), rec["sentence"]
            assert "certif" not in rec["sentence"].lower()
        if not res["recommendations"]:
            assert res["what_to_obtain"]
    assert n > 20


def test_two_to_four_and_safest_included(sweep):
    for a, res in sweep:
        recs = res["recommendations"]
        assert len(recs) <= 4
        if recs:
            assert sum(r["safest"] for r in recs) == 1


def test_wording_rule_and_disclaimer(sweep):
    for a, res in sweep:
        assert res["disclaimer"] == "Research prototype. Not legal advice. Human review required."
        for rec in res["recommendations"]:
            assert "compliant" not in rec["status_line"].lower() and "guarantee" not in rec["status_line"].lower()
            assert rec["status_line"] in ("Fits the checked requirements, provided the marked facts are verified.",
                                          "Passt zu den geprüften Anforderungen, sofern die markierten Fakten belegt sind.")


def test_template_mode_is_deterministic(kb, lib, off):
    for a in sample_answers(kb, lib, n=60, seed=3):
        r1, r2 = recommend(a, kb, lib, off), recommend(a, kb, lib, off)
        r1["run"].pop("duration_ms"), r2["run"].pop("duration_ms")
        assert r1 == r2


def test_regulations_carry_verified_quotes(sweep, kb):
    for a, res in sweep[:150]:
        for rec in res["recommendations"]:
            assert rec["regulations"]
            for g in rec["regulations"]:
                assert g["quote"] in kb.chunks[g["chunk_id"]].text
                assert g["legal_status"] and g["locator"] and g["doc_title"]


def test_not_sure_routes_to_manual_review(kb, lib, off):
    a = {"segment": "not_sure", "audience": "consumers", "channel": "website", "topic": "recycled_content",
         "scope": "whole_product", "evidence": "supplier_declaration", "method": "supplier_records"}
    res = recommend(a, kb, lib, off)
    assert res["human_review_required"]
    assert any(n["kind"] == "review" for n in res["notes"])
    assert not any(r in res["context"]["candidate_rules"] for r in ("TX01", "EE01", "BI01"))


def test_channel_filters_rules(kb, lib):
    seg = segment_with(kb, ["BI02"])
    base = {"segment": seg, "product_type": "biocide", "audience": "consumers", "topic": "free_from_substances",
            "scope": "whole_product", "evidence": "none_yet"}
    assert "BI02" in build_context({**base, "channel": "advertising"}, kb, lib).candidates
    assert "BI02" not in build_context({**base, "channel": "label"}, kb, lib).candidates


def test_free_text_and_bad_values_rejected(kb, lib, off):
    seg = segment_with(kb, ["TX01", "TX02", "EN03"])
    a = {"segment": seg, "audience": "consumers", "channel": "label", "topic": "recycled_content", "scope": "part",
         "part": "outer fabric", "evidence": "third_party_certificate", "facts": {"X": "about sixty"}}
    with pytest.raises(AnswerError):
        recommend(a, kb, lib, off)
    with pytest.raises(AnswerError):
        recommend({**a, "facts": {"material": "recycled eco stuff"}}, kb, lib, off)
    with pytest.raises(AnswerError):
        recommend({**a, "facts": {"comment": "free text"}}, kb, lib, off)


def test_chip_edit_revalidates_without_ai(kb, lib):
    seg = segment_with(kb, ["TX01", "TX02", "EN03"])
    a = {"segment": seg, "audience": "consumers", "channel": "label", "topic": "recycled_content", "scope": "part",
         "part": "outer fabric", "evidence": "third_party_certificate", "facts": {"X": "60", "material": "polyester"}}
    r = revalidate(a, "RC-PART-01", {"ID": "GRS-1", "scheme": "Global Recycled Standard"}, kb, lib)
    assert r["ok"] and "GRS-1" in r["recommendation"]["sentence"]
    assert not revalidate(a, "RC-PART-01", {"X": "160"}, kb, lib)["ok"]
    assert not revalidate(a, "RC-PART-01", {"cert_body": "Anyone"}, kb, lib)["ok"]
