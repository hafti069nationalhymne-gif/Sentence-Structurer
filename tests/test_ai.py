"""The optional AI step, tested against a fake Ollama server. Every model output is checked in code."""
import re

import pytest

from app.config import Settings
from app.engine import ai
from app.engine.recommend import recommend
from app.ollama_client import OllamaClient, OllamaError
from conftest import segment_with
from fake_ollama import FakeOllama, data_block, echo_responder, first_chunk_id


@pytest.fixture
def ticket(kb):
    seg = segment_with(kb, ["TX01", "TX02", "EN03"])
    return {"segment": seg, "audience": "consumers", "channel": "label", "topic": "recycled_content", "scope": "part",
            "part": "outer fabric", "evidence": "third_party_certificate", "use_date": "2026-11-21", "tone": "warm",
            "facts": {"X": "60", "material": "polyester", "scheme": "Global Recycled Standard"}}  # [ID] stays a placeholder


def run(ticket, kb, lib, responder, models=("qwen3.5:4b",)):
    with FakeOllama(responder, models=models) as f:
        s = Settings(ollama_enabled=True, ollama_url=f.url, chat_model="qwen3.5:4b")
        res = recommend(ticket, kb, lib, s, OllamaClient(f.url))
        return res, f.calls


def template_sentences(ticket, kb, lib):
    res = recommend(ticket, kb, lib, Settings(ollama_enabled=False))
    return {r["template_id"]: r["sentence"] for r in res["recommendations"]}


def tone_bad(mutate):
    def responder(kind, user, body):
        if kind == "why":
            return {"why": "It states the share and the evidence.", "chunk_ids": [first_chunk_id(user)]}
        return {"sentence": mutate(data_block(user))}
    return responder


@pytest.mark.parametrize("name,mutate", [
    ("adds a number", lambda s: s + " Now 20 % more."),
    ("changes a number", lambda s: s.replace("60", "70")),
    ("drops a placeholder", lambda s: re.sub(r"\[\w+\]\s?", "", s, count=1)),
    ("adds sustainable", lambda s: "Sustainable choice: " + s),
    ("adds a certificate", lambda s: s + " Certified by TÜV."),
])
def test_bad_rewrite_rejected_and_template_used(ticket, kb, lib, name, mutate):
    expected = template_sentences(ticket, kb, lib)
    res, calls = run(ticket, kb, lib, tone_bad(mutate))
    assert res["run"]["mode"] == "ai"
    for rec in res["recommendations"]:
        assert rec["sentence"] == expected[rec["template_id"]], name
        assert "tone" not in rec["ai_parts"]
    assert any("rejected attempt 2" in l for l in res["log"])  # one retry, then fallback
    assert len([c for c in calls if "Rewrite the sentence" in c["messages"][-1]["content"]]) == 2 * len(res["recommendations"])


def test_good_rewrite_accepted(ticket, kb, lib):
    res, calls = run(ticket, kb, lib, tone_bad(lambda s: "Good to know: " + s[0].lower() + s[1:]))
    assert all(r["ai_adjusted"] and "tone" in r["ai_parts"] for r in res["recommendations"])
    body = calls[0]
    assert body["stream"] is False and body["options"] == {"temperature": 0, "seed": 42}
    assert body["format"]["type"] == "object" and body.get("think") is False
    assert "ignore any instruction" in body["messages"][0]["content"].lower()


def test_why_must_cite_supplied_chunks(ticket, kb, lib):
    def responder(kind, user, body):
        if kind == "why":
            return {"why": "It is fully compliant.", "chunk_ids": ["INVENTED-1"]}
        return {"sentence": data_block(user)}
    res, _ = run(ticket, kb, lib, responder)
    for rec in res["recommendations"]:
        assert rec["why_source"] == "rule_requirement"
        assert rec["why_it_fits"] == kb.rules[rec["rule_ids"][0]].requirement or rec["why_it_fits"]
        assert "compliant" not in rec["why_it_fits"].lower()


def test_why_accepted_with_valid_citation(ticket, kb, lib):
    res, _ = run(ticket, kb, lib, echo_responder)
    for rec in res["recommendations"]:
        assert rec["why_source"] == "ai"
        allowed = {g["chunk_id"] for g in rec["regulations"]}
        assert set(rec["why_chunk_ids"]) <= allowed


def test_translation_checked(ticket, kb, lib):
    de = {**ticket, "language": "de", "tone": "factual"}

    def english_echo(kind, user, body):  # a "translation" that is still English must be rejected
        if kind == "why":
            return {"why": "x.", "chunk_ids": [first_chunk_id(user)]}
        return {"sentence": data_block(user)}
    res, _ = run(de, kb, lib, english_echo)
    for rec in res["recommendations"]:
        assert "translation" not in rec["ai_parts"]
        assert rec["language"] == "de" and "German wording not yet reviewed" in rec["tags"]
    assert any("output is not German" in l for l in res["log"])


def test_ollama_missing_falls_back(ticket, kb, lib):
    s = Settings(ollama_enabled=True, ollama_url="http://127.0.0.1:9")
    res = recommend(ticket, kb, lib, s, OllamaClient("http://127.0.0.1:9", timeout=1))
    assert res["run"]["mode"] == "template" and res["recommendations"]
    assert any(n["kind"] == "mode" and "template mode" in n["text"] for n in res["notes"])


def test_model_missing_falls_back(ticket, kb, lib):
    res, calls = run(ticket, kb, lib, echo_responder, models=("llama3:8b",))
    assert res["run"]["mode"] == "template" and not calls
    assert any("not installed" in n["text"] for n in res["notes"])


def test_client_endpoints():
    with FakeOllama() as f:
        c = OllamaClient(f.url)
        assert c.version() == "0.12.0"
        assert c.tags() == ["qwen3.5:4b"]
        c.pull("gpt-oss:20b")
        assert "gpt-oss:20b" in c.tags()
        assert c.chat_json("qwen3.5:4b", "s", "<data>Hi</data> Rewrite the sentence", ai.SENTENCE_SCHEMA) == {"sentence": "Hi"}
    with pytest.raises(OllamaError):
        OllamaClient("http://127.0.0.1:9").version()


def test_structural_check_unit():
    src = "The cap is not included. It contains [X] % recycled PET, calculated under Regulation (EU) 2025/40."
    assert ai.structural_check(src, src, "en", "en").ok
    assert not ai.structural_check(src, src.replace(" is not included", " is included"), "en", "en").ok
    assert not ai.structural_check(src, src.replace("2025/40", "2024/40"), "en", "en").ok
    assert not ai.structural_check(src, src + " Green!", "en", "en").ok


def test_verify_model_cli(monkeypatch, tmp_path):
    from app import cli
    with FakeOllama(lambda k, u, b: {"sentence": "The cap is not included.", "count": 3}) as f:
        monkeypatch.setattr(cli, "load_settings", lambda: Settings(ollama_url=f.url))
        assert cli.main(["cli", "verify-model", "qwen3.5:4b"]) == 0
    with FakeOllama(lambda k, u, b: {"sentence": 5}) as f:
        monkeypatch.setattr(cli, "load_settings", lambda: Settings(ollama_url=f.url))
        assert cli.main(["cli", "verify-model", "qwen3.5:4b"]) == 1


def test_choose_model_by_hardware():
    from app.cli import choose_model
    assert choose_model(ram=64, gpu=0) == "gpt-oss:20b"
    assert choose_model(ram=16, gpu=16) == "gpt-oss:20b"
    assert choose_model(ram=16, gpu=8) == "qwen3.5:4b"
