"""All library checks of brief section 5 pass, and COVERAGE.md shows no uncovered rule."""
import json
import re

from app import library_checks
from app.config import LIBRARY_DIR
from app.library import Template, contains_phrase, has_figure, lift_holds_for_template, phrase_pattern


def test_all_hard_checks_pass(lib, kb):
    results = library_checks.run_all(lib, kb)
    assert {k: v for k, v in results.items() if v} == {}


def test_template_count_in_range(lib):
    n = len([t for t in lib.templates.values() if t.topic != "_mandatory"])
    assert 80 <= n <= 120


def test_coverage_report_has_no_uncovered_rule(lib, kb):
    cov = library_checks.coverage(lib, kb)
    assert all(v["covered"] for v in cov.values() if v["required"])
    text = (LIBRARY_DIR / "COVERAGE.md").read_text(encoding="utf-8")
    assert "**Uncovered: 0**" in text


def test_every_topic_has_templates_and_rules(lib):
    for topic in lib.questionnaire["topics"]:
        assert lib.by_topic(topic), topic
        assert topic in lib.topic_rules["topics"], topic


def test_questionnaire_is_data(lib):
    q = json.loads((LIBRARY_DIR / "questionnaire.json").read_text(encoding="utf-8"))
    assert [x["number"] for x in q["questions"]] == list(range(1, 10))
    assert len(q["topics"]) == 23


def test_examples_never_recommended(lib, kb):
    bad = {e.claim.lower().rstrip(".") for r in kb.rules.values() for e in r.examples}
    for t in lib.templates.values():
        assert t.text_en.lower().rstrip(".") not in bad


def test_dont_say_built_from_triggers_avoid_and_examples(lib, kb):
    sources = {d["source"] for d in lib.dont_say}
    assert {"trigger", "avoid", "example"} <= sources
    assert all(d["rule_id"] in kb.rules for d in lib.dont_say)
    assert not any(kb.rules[d["rule_id"]].scope.routing == "future_watch" for d in lib.dont_say)
    eco = [d for d in lib.dont_say if d["phrase_en"] == "eco-friendly" and d["rule_id"] == "P01"]
    assert eco and eco[0]["phrase_de"] == "umweltfreundlich"


def test_checks_catch_bad_templates(lib, kb):
    """The checks are real: a template with banned wording, a figure without evidence or a stray bracket fails."""
    base = lib.templates["RC-PART-01"].model_dump()
    bad1 = Template.model_validate({**base, "template_id": "X1", "text_en": base["text_en"] + " Eco-friendly too."})
    bad2 = Template.model_validate({**base, "template_id": "X2", "requires": {**base["requires"], "evidence_types": ["none_yet"]}})
    bad3 = Template.model_validate({**base, "template_id": "X3", "text_en": "The [component contains [X] %."})
    bad4 = Template.model_validate({**base, "template_id": "X4", "satisfies": []})
    saved = dict(lib.templates)
    try:
        lib.templates.clear()
        lib.templates.update({t.template_id: t for t in (bad1, bad2, bad3, bad4)})
        assert any("X1" in e for e in library_checks.check_triggers(lib, kb))
        assert any("X2" in e for e in library_checks.check_figures(lib))
        assert any("X3" in e for e in library_checks.check_placeholders(lib))
        assert any("X4" in e and "satisfies" in e for e in library_checks.check_triggers(lib, kb))
    finally:
        lib.templates.clear()
        lib.templates.update(saved)


def test_ecolabel_only_with_licence(lib):
    t = lib.templates["EL-01"]
    assert t.requires.evidence_types == ["eu_ecolabel_licence"] and "LB01" in t.satisfies
    assert lift_holds_for_template(lib.lifts["ecolabel"], t)


def test_phrase_matching():
    assert contains_phrase("Our eco-friendly bag", "eco-friendly")
    assert not contains_phrase("greenhouse gas", "green")
    assert contains_phrase("bleifreie Lötstellen", "~frei", "de")
    assert contains_phrase("umweltfreundliche Verpackung", "umweltfreundlich", "de")
    assert contains_phrase("lead-free solder", "-free")
    assert not contains_phrase("The [eco] part", "eco")  # placeholders are not wording
    assert has_figure("contains 60 % recycled") and not has_figure("Regulation (EU) 2025/40")
    assert phrase_pattern("*") is None


def test_german_texts_present_and_unreviewed(lib):
    for t in lib.templates.values():
        assert t.text_de, t.template_id
        assert set(re.findall(r"\[(\w+)\]", t.text_de)) == set(re.findall(r"\[(\w+)\]", t.text_en))
