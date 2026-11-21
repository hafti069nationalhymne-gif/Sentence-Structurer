"""Local API, storage, exports, evaluation support and binding to 127.0.0.1 only."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from app.config import BIND_HOST, ROOT, load_settings
from app.main import free_port
from app.storage import sus_score
from conftest import segment_with


@pytest.fixture
def answers(kb):
    return {"segment": segment_with(kb, ["TX01", "TX02", "EN03"]), "audience": "consumers", "channel": "label",
            "topic": "recycled_content", "scope": "part", "part": "outer fabric", "evidence": "third_party_certificate",
            "use_date": "2026-11-21", "facts": {"X": "60", "material": "polyester"}}


def test_questionnaire_and_route(api, kb):
    q = api.get("/api/questionnaire").json()
    assert len(q["segments"]) == len(kb.eclass) + 2 == 42
    r = api.post("/api/route", json={"answers": {"segment": "30"}}).json()
    assert [o["id"] for o in r["refinements"]] == ["detergent", "biocide", "other_chemical"]
    assert r["rules"] and all({"rule_id", "title", "severity"} <= set(x) for x in r["rules"])


def test_recommend_saves_ticket_with_hashes(api, answers):
    res = api.post("/api/recommend", json={"answers": answers, "session_id": "s1", "use_ai": False}).json()
    assert res["ticket_id"] == 1 and res["recommendations"]
    t = api.get("/api/history/1").json()
    assert t["library_hash"] == res["run"]["library_hash"] and t["knowledge_hash"] == res["run"]["knowledge_hash"]
    assert t["mode"] == "template"
    assert api.get("/api/history").json()["tickets"][0]["id"] == 1


def test_response_shape(api, answers):
    res = api.post("/api/recommend", json={"answers": answers, "use_ai": False}).json()
    for key in ("answers", "recommendations", "dont_say", "what_to_obtain", "future_requirements", "notes",
                "human_review_required", "run"):
        assert key in res
    rec = res["recommendations"][0]
    for key in ("template_id", "sentence", "language", "specificity", "ai_adjusted", "why_it_fits", "facts_to_verify",
                "placeholders", "regulations"):
        assert key in rec
    g = rec["regulations"][0]
    for key in ("rule_id", "rule_title", "doc_title", "locator", "jurisdiction", "legal_status", "quote", "chunk_id",
                "caution", "german_counterpart"):
        assert key in g
    assert set(res["run"]) >= {"mode", "chat_model", "library_hash", "knowledge_hash", "duration_ms"}


def test_invalid_answers_and_free_text_rejected(api, answers):
    assert api.post("/api/recommend", json={"answers": {**answers, "facts": {"X": "sixty"}}}).status_code == 422
    assert api.post("/api/recommend", json={"answers": {**answers, "comment": "free text"}}).status_code == 422
    assert api.post("/api/recommend", json={"answers": {**answers, "topic": "x" * 200}}).status_code == 422


def test_revalidate_and_adjust(api, answers):
    r = api.post("/api/revalidate", json={"answers": answers, "template_id": "RC-PART-01", "values": {"ID": "GRS-77"}}).json()
    assert r["ok"] and "GRS-77" in r["recommendation"]["sentence"]
    r = api.post("/api/adjust", json={"answers": {**answers, "language": "de"}, "template_id": "RC-PART-01", "values": {}}).json()
    assert r["ok"] and r["recommendation"]["language"] == "de"


def test_exports(api, answers):
    api.post("/api/recommend", json={"answers": answers, "use_ai": False})
    api.post("/api/review", json={"ticket_id": 1, "template_id": "RC-PART-01", "fits": "yes", "would_use": 4, "comment": "ok"})
    j = api.get("/api/export?format=json").json()
    assert j["tickets"][0]["id"] == 1 and j["reviews"][0]["would_use"] == 4
    csv_text = api.get("/api/export?format=csv&ticket_id=1").text
    assert "template_id" in csv_text.splitlines()[0] and "RC-PART-01" in csv_text
    md = api.get("/api/export?format=md").text
    assert md.startswith("# ClaimComposer results") and "Not legal advice" in md
    assert api.get("/api/export?format=xml").status_code == 400


def test_review_usability_sus_and_clear(api, answers):
    api.post("/api/recommend", json={"answers": answers, "use_ai": False})
    assert api.post("/api/review", json={"template_id": "RC-PART-01", "would_use": 9}).status_code == 422
    assert api.post("/api/usability", json={"session_id": "s", "ticket_id": 1, "question_times": {"product": 1200},
                                            "back_steps": 2, "time_to_first_copy_ms": 50000}).json()["ok"]
    r = api.post("/api/sus", json={"session_id": "s", "answers": [5, 1, 5, 1, 5, 1, 5, 1, 5, 1]}).json()
    assert r["score"] == 100.0
    csv_text = api.get("/api/export/usability.csv").text
    assert "usability" in csv_text and "sus" in csv_text
    assert api.post("/api/clear", json={"confirm": "yes"}).status_code == 422
    assert api.post("/api/clear", json={"confirm": "DELETE"}).json()["ok"]
    assert api.get("/api/history").json()["tickets"] == []


def test_sus_score():
    assert sus_score([3] * 10) == 50.0
    with pytest.raises(ValueError):
        sus_score([6] * 10)


def test_settings_persist(api, tmp_path):
    r = api.post("/api/settings", json={"review_mode": True, "chat_model": "gpt-oss:20b"}).json()
    assert r["review_mode"] and r["chat_model"] == "gpt-oss:20b"
    assert api.post("/api/settings", json={"chat_model": "bad model; rm"}).status_code == 422
    s = load_settings(userdata=tmp_path / "userdata")
    assert s.review_mode and s.chat_model == "gpt-oss:20b"


def test_static_and_security_headers(api):
    r = api.get("/")
    assert r.status_code == 200 and "ClaimComposer" in r.text
    assert "default-src 'self'" in r.headers["content-security-policy"]
    html = r.text
    assert "http://" not in html.replace("http://www.w3.org", "") and "https://" not in html  # no CDN
    css = (ROOT / "app/static/css/app.css").read_text() + (ROOT / "app/static/css/fonts.css").read_text()
    assert "googleapis" not in css and "Inter" not in css and "Roboto" not in css and "Arial" not in css
    for f in ("gloock-latin-400-normal.woff2", "newsreader-latin-400-normal.woff2", "fragment-mono-latin-400-normal.woff2"):
        assert api.get(f"/static/fonts/{f}").status_code == 200


def test_frontend_never_uses_raw_html():
    for js in (ROOT / "app/static/js").glob("*.js"):
        src = js.read_text()
        assert "innerHTML" not in src and "outerHTML" not in src and "insertAdjacentHTML" not in src, js.name


def test_sources_and_search(api):
    s = api.get("/api/sources/P01").json()
    assert s["passages"] and all(p["text"] for p in s["passages"])
    assert api.get("/api/sources/NOPE").status_code == 404
    assert api.get("/api/search?q=recycled+content").json()["results"]


# ---- binding ----------------------------------------------------------------------------
def test_bind_host_is_loopback_and_not_configurable(tmp_path):
    assert BIND_HOST == "127.0.0.1"
    cfg = tmp_path / "config.toml"
    cfg.write_text('[server]\nhost = "0.0.0.0"\nport = 0\n[ollama]\nurl = "http://example.com:11434"\n')
    s = load_settings(cfg, tmp_path)
    assert s.ollama_url.startswith("http://127.0.0.1")
    assert not hasattr(s, "host")


def _external_ip():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return None


def test_server_binds_only_to_loopback(tmp_path):
    port = free_port()
    env = {**os.environ, "PYTHONUTF8": "1"}
    p = subprocess.Popen([sys.executable, "-m", "app.main", "--port", str(port)], cwd=ROOT, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                if httpx.get(f"http://127.0.0.1:{port}/api/status", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.25)
        else:
            pytest.fail("server did not start")
        ip = _external_ip()
        if ip and not ip.startswith("127."):
            with pytest.raises(OSError):
                socket.create_connection((ip, port), timeout=1).close()
    finally:
        p.terminate()
        p.wait(timeout=10)
