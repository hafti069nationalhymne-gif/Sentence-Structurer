"""Scenario tests (tests/scenarios.yaml), run in template mode and in AI mode.

Real Ollama is not available in the test environment, so 'AI mode' uses the fake Ollama server with a
well-behaved model (echo rewrites, cited explanations). The same expectations must hold in both modes.
"""
import re
from pathlib import Path

import pytest
import yaml

from app.config import Settings
from app.engine.recommend import recommend
from app.library import has_figure
from app.ollama_client import OllamaClient
from conftest import segment_with
from fake_ollama import FakeOllama, echo_responder

SCENARIOS = yaml.safe_load((Path(__file__).parent / "scenarios.yaml").read_text(encoding="utf-8"))


def resolve(kb, answers):
    a = dict(answers)
    rules = a.pop("segment_rules", None)
    name = a.pop("segment_name", None)
    if rules:
        a["segment"] = segment_with(kb, rules, name)
    a.setdefault("use_date", "2026-11-21")
    a.setdefault("tone", "warm")  # exercise the tone step in AI mode
    return a


def word_in(word, text):
    return re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", text, re.I) is not None


def check(res, e):
    recs = res["recommendations"]
    sents = [r["sentence"] for r in recs]
    cited = {rid for r in recs for rid in r["rule_ids"]}
    if "min_recs" in e:
        assert len(recs) >= e["min_recs"], sents
    if "max_recs" in e:
        assert len(recs) <= e["max_recs"], sents
    if "some_sentence_contains_all" in e:
        assert any(all(x in s for x in e["some_sentence_contains_all"]) for s in sents), sents
    for x in e.get("every_sentence_contains", []):
        assert all(x in s for s in sents), (x, sents)
    for w in e.get("no_sentence_contains_words", []):
        assert not any(word_in(w, s) for s in sents), (w, sents)
    if e.get("no_figures"):
        assert not any(has_figure(s) for s in sents), sents
    for rid in e.get("any_rec_cites", []):
        assert rid in cited, (rid, cited)
    for rid in e.get("no_rec_cites", []):
        assert rid not in cited, (rid, cited)
    if "every_rec_cites_one_of" in e:
        assert all(set(r["rule_ids"]) & set(e["every_rec_cites_one_of"]) for r in recs)
    if "some_template" in e:
        assert any(r["template_id"] in e["some_template"] for r in recs), [r["template_id"] for r in recs]
    ds = {d["phrase"].lower() for d in res["dont_say"]}
    for ph in e.get("dont_say_includes", []):
        assert ph.lower() in ds, ph
    notes = {n["rule_id"] for n in res["notes"]}
    for rid in e.get("notes_rules", []):
        assert rid in notes, (rid, res["notes"])
    fut = {f["rule_id"] for f in res["future_requirements"]}
    for rid in e.get("future_rules", []):
        assert rid in fut, (rid, fut)
    for rid in e.get("not_future_rules", []):
        assert rid not in fut
    if e.get("what_to_obtain"):
        assert res["what_to_obtain"]
    if "language" in e:
        assert all(r["language"] == e["language"] for r in recs)
    if e.get("german_tag"):
        assert all("German wording not yet reviewed" in r["tags"] for r in recs)
    if "dont_say_language" in e:
        phrases = [d for d in res["dont_say"] if d["kind"] == "phrase"]
        share = sum(d["phrase_language"] == e["dont_say_language"] for d in phrases) / max(1, len(phrases))
        assert share > 0.8


@pytest.mark.parametrize("sc", SCENARIOS, ids=[s["name"] for s in SCENARIOS])
def test_scenario_template_mode(sc, kb, lib):
    res = recommend(resolve(kb, sc["answers"]), kb, lib, Settings(ollama_enabled=False))
    assert res["run"]["mode"] == "template"
    check(res, sc["expect"])


@pytest.fixture(scope="module")
def fake():
    with FakeOllama(echo_responder) as f:
        yield f


@pytest.mark.parametrize("sc", SCENARIOS, ids=[s["name"] for s in SCENARIOS])
def test_scenario_ai_mode(sc, kb, lib, fake):
    s = Settings(ollama_enabled=True, ollama_url=fake.url, chat_model="qwen3.5:4b")
    res = recommend(resolve(kb, sc["answers"]), kb, lib, s, OllamaClient(fake.url))
    if res["recommendations"]:
        assert res["run"]["mode"] == "ai"
    check(res, sc["expect"])
