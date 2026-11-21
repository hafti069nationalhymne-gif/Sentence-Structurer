"""Ollama Cloud mode: no download, API key sent only to the cloud URL, never returned or exported."""
import os
import stat

import pytest

from app.config import Settings, api_key_file, load_api_key, load_settings, save_api_key
from app.engine.recommend import recommend
from app.ollama_client import OllamaClient, make_client
from conftest import segment_with
from fake_ollama import FakeOllama, echo_responder

KEY = "testkey0123456789abcdef.ABCDEFGHIJ-klmnop_qr"


@pytest.fixture
def ticket(kb):
    return {"segment": segment_with(kb, ["TX01", "TX02", "EN03"]), "audience": "consumers", "channel": "label",
            "topic": "recycled_content", "scope": "part", "part": "outer fabric", "evidence": "third_party_certificate",
            "use_date": "2026-11-21", "tone": "warm", "facts": {"X": "60", "material": "polyester"}}


@pytest.fixture(autouse=True)
def no_env_key(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)


def cloud_settings(url):
    return Settings(ollama_enabled=True, ai_source="cloud", cloud_url=url, cloud_model="gpt-oss:20b")


def test_recommend_via_cloud_sends_bearer_key(ticket, kb, lib, tmp_path):
    save_api_key(KEY, tmp_path)
    with FakeOllama(echo_responder, models=("gpt-oss:20b", "gpt-oss:120b"), api_key=KEY) as f:
        s = cloud_settings(f.url)
        res = recommend(ticket, kb, lib, s, make_client(s, tmp_path))
        assert res["run"]["mode"] == "ai" and res["run"]["chat_model"] == "gpt-oss:20b" and res["run"]["ai_source"] == "cloud"
        assert all(h == f"Bearer {KEY}" for h in f.auth_headers)
        assert any("ollama.com" in n["text"] for n in res["notes"] if n["kind"] == "mode")
        assert all(c["model"] == "gpt-oss:20b" for c in f.calls)


def test_wrong_key_falls_back_to_template(ticket, kb, lib, tmp_path):
    save_api_key("wrongkey0123456789abcdef", tmp_path)
    with FakeOllama(echo_responder, models=("gpt-oss:20b",), api_key=KEY) as f:
        s = cloud_settings(f.url)
        res = recommend(ticket, kb, lib, s, make_client(s, tmp_path))
    assert res["run"]["mode"] == "template" and res["recommendations"]
    assert any("rejected" in n["text"] for n in res["notes"])


def test_missing_key_and_missing_model(ticket, kb, lib, tmp_path):
    with FakeOllama(echo_responder, models=("gpt-oss:20b",), api_key=KEY) as f:
        s = cloud_settings(f.url)
        res = recommend(ticket, kb, lib, s, make_client(s, tmp_path))
        assert res["run"]["mode"] == "template" and any("No Ollama Cloud API key" in n["text"] for n in res["notes"])
        save_api_key(KEY, tmp_path)
        s.cloud_model = "not-a-model:1b"
        res = recommend(ticket, kb, lib, s, make_client(s, tmp_path))
        assert res["run"]["mode"] == "template" and any("does not offer" in n["text"] for n in res["notes"])


def test_cloud_tag_suffix_accepted():
    assert OllamaClient.has_model("gpt-oss:20b", ["gpt-oss:20b-cloud"])
    assert OllamaClient.has_model("gpt-oss:20b-cloud", ["gpt-oss:20b"])
    assert not OllamaClient.has_model("gpt-oss:120b", ["gpt-oss:20b"])


def test_key_storage(tmp_path, monkeypatch):
    save_api_key(KEY, tmp_path)
    assert load_api_key(tmp_path) == KEY
    if os.name == "posix":
        assert stat.S_IMODE(api_key_file(tmp_path).stat().st_mode) == 0o600
    with pytest.raises(ValueError):
        save_api_key("not a key; rm -rf", tmp_path)
    save_api_key("", tmp_path)
    assert load_api_key(tmp_path) is None
    monkeypatch.setenv("OLLAMA_API_KEY", KEY)
    assert load_api_key(tmp_path) == KEY


def test_local_mode_never_sends_key(tmp_path):
    save_api_key(KEY, tmp_path)
    with FakeOllama(echo_responder) as f:
        c = make_client(Settings(ollama_url=f.url), tmp_path)
        c.status("qwen3.5:4b")
        assert all(h is None for h in f.auth_headers)


def test_cloud_url_cannot_be_redirected_by_config(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[ollama]\nsource = "cloud"\ncloud_url = "https://evil.example.com"\n')
    s = load_settings(cfg, tmp_path)
    assert s.cloud and s.cloud_url == "https://ollama.com"


def test_api_settings_key_is_write_only(api, tmp_path):
    r = api.post("/api/settings", json={"ai_source": "cloud", "api_key": KEY})
    assert r.status_code == 200 and r.json()["api_key_set"] is True and KEY not in r.text
    st = api.get("/api/status")
    assert st.json()["ai_source"] == "cloud" and st.json()["api_key_set"] is True and KEY not in st.text
    assert api.post("/api/settings", json={"api_key": "bad key!"}).status_code == 422
    assert KEY not in api.get("/api/export?format=json").text
    assert KEY not in (tmp_path / "userdata" / "settings.json").read_text()
    assert api.post("/api/settings", json={"api_key": ""}).json()["api_key_set"] is False


def test_cli_set_cloud_reads_stdin(tmp_path, monkeypatch):
    import io
    from app import cli, config
    monkeypatch.setattr(cli, "USERDATA_DIR", tmp_path)
    monkeypatch.setattr(config, "USERDATA_DIR", tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(KEY + "\n"))
    assert cli.main(["cli", "set-cloud"]) == 0
    assert load_api_key(tmp_path) == KEY
    assert load_settings(userdata=tmp_path).ai_source == "cloud"
    monkeypatch.setattr("sys.stdin", io.StringIO("nope\n"))
    assert cli.main(["cli", "set-cloud"]) == 1


def test_launchers_read_key_from_file_without_asking():
    from app.config import ROOT
    sh = (ROOT / "installer/common.sh").read_text()
    ps = (ROOT / "installer/setup.ps1").read_text()
    for src in (sh, ps):
        assert "OLLAMA_API_KEY.txt" in src and "use-key-file" in src
        assert "read -r -s" not in src and "AsSecureString" not in src  # no key prompt any more
        assert "set-cloud $" not in src  # the key is never passed as an argument


def test_cloud_release_zip(tmp_path):
    import subprocess
    import zipfile
    from app.config import ROOT
    subprocess.run(["python", "scripts/build_release.py", "--cloud"], cwd=ROOT, check=True, capture_output=True)
    z = zipfile.ZipFile(ROOT / "dist/ClaimComposer-cloud.zip")
    assert 'source = "cloud"' in z.read("ClaimComposer/config.toml").decode()
    assert z.read("ClaimComposer/installer/default_choice.txt").decode().strip() == "3"
    assert not any("api_key.txt" in n.lower() and "OLLAMA_API_KEY.txt" not in n for n in z.namelist())
    assert not any("/userdata/" in n or "screenshots" in n for n in z.namelist())
    from app.config import KEY_FILE_TEMPLATE
    assert z.read("ClaimComposer/OLLAMA_API_KEY.txt").decode() == KEY_FILE_TEMPLATE


def test_payment_required_falls_back_once(ticket, kb, lib, tmp_path):
    """A valid key on an account without credits: one failed call, then template mode with the reason."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    calls = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

        def do_GET(self):
            self._send(200, {"models": [{"name": "gpt-oss:20b"}]})

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            calls.append(1)
            self._send(402, {"error": "Add usage credits or subscribe"})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        save_api_key(KEY, tmp_path)
        s = cloud_settings(f"http://127.0.0.1:{srv.server_address[1]}")
        res = recommend(ticket, kb, lib, s, make_client(s, tmp_path))
    finally:
        srv.shutdown()
    assert res["run"]["mode"] == "template" and res["recommendations"]
    assert any("usage credits" in n["text"] for n in res["notes"])
    assert not any("AI via Ollama Cloud" in n["text"] for n in res["notes"])
    assert len(calls) <= 2  # stops after the first proof instead of failing on every call


# ---- key in OLLAMA_API_KEY.txt ---------------------------------------------------------------
from app.config import KEY_FILE_TEMPLATE, key_file_status  # noqa: E402


@pytest.mark.parametrize("content,encoding", [
    (KEY_FILE_TEMPLATE + KEY + "\n", "utf-8"),
    (KEY_FILE_TEMPLATE + KEY, "utf-8-sig"),        # Notepad "UTF-8 with BOM"
    (KEY_FILE_TEMPLATE + KEY + "\r\n", "utf-16"),   # Notepad "Unicode"
    (f"  {KEY}  \n", "utf-8"),
    (f'"{KEY}"', "utf-8"),
    (f"Bearer {KEY}", "utf-8"),
    (f"OLLAMA_API_KEY={KEY}", "utf-8"),
])
def test_key_file_variants(tmp_path, content, encoding):
    f = tmp_path / "OLLAMA_API_KEY.txt"
    f.write_bytes(content.encode(encoding))
    assert key_file_status(f) == ("ok", KEY)
    assert load_api_key(tmp_path, key_file=f) == KEY


def test_key_file_empty_missing_invalid(tmp_path):
    f = tmp_path / "OLLAMA_API_KEY.txt"
    assert key_file_status(f)[0] == "missing"
    f.write_text(KEY_FILE_TEMPLATE)
    assert key_file_status(f)[0] == "empty"
    f.write_text(KEY_FILE_TEMPLATE + "paste my key here please\n")
    assert key_file_status(f)[0] == "invalid"


def test_key_file_switches_to_cloud(tmp_path):
    f = tmp_path / "OLLAMA_API_KEY.txt"
    f.write_text(KEY_FILE_TEMPLATE + KEY)
    s = load_settings(userdata=tmp_path, key_file=f)
    assert s.cloud and s.ollama_enabled and s.cloud_model == "auto"
    f.write_text(KEY_FILE_TEMPLATE)
    assert not load_settings(userdata=tmp_path, key_file=f).cloud


def test_cli_use_key_file(tmp_path, monkeypatch):
    from app import cli, config
    f = tmp_path / "OLLAMA_API_KEY.txt"
    monkeypatch.setattr(config, "KEY_FILE", f)
    monkeypatch.setattr(cli, "USERDATA_DIR", tmp_path)
    monkeypatch.setattr(config, "USERDATA_DIR", tmp_path)
    f.write_text(KEY_FILE_TEMPLATE)
    assert cli.main(["cli", "use-key-file"]) == 3
    f.write_text("not a key at all!")
    assert cli.main(["cli", "use-key-file"]) == 4
    f.write_text(KEY_FILE_TEMPLATE + KEY)
    assert cli.main(["cli", "use-key-file"]) == 0
    assert load_settings(userdata=tmp_path, key_file=f).ai_source == "cloud"


def test_repository_key_file_has_no_key():
    from app.config import ROOT
    assert (ROOT / "OLLAMA_API_KEY.txt").read_text(encoding="utf-8") == KEY_FILE_TEMPLATE


# ---- choosing the cloud model from what the key offers ------------------------------------------
from app.model_pick import pick_model, rank_models  # noqa: E402

KEY_MODELS = ["beam", "clef:27b", "deepseek-v4-pro:0813", "deepseek-v4.1-flash", "gemma4:31b", "glm-5.3-flash",
              "gpt-oss:120b", "gpt-oss:20b", "kimi-k2.7-code", "kimi-k3", "mistral-large-4", "nemotron-3-super"]


def test_ranking_without_qwen():
    order = [m for m, _ in rank_models(KEY_MODELS)]
    assert order[:3] == ["mistral-large-4", "gemma4:31b", "gpt-oss:20b"]
    assert "kimi-k2.7-code" not in order  # code models are excluded
    assert order.index("deepseek-v4.1-flash") < order.index("gpt-oss:120b")
    assert set(order[-2:]) == {"clef:27b", "beam"}  # unknown names come last


def test_qwen_preferred_and_small_first():
    order = [m for m, _ in rank_models(KEY_MODELS + ["qwen3-coder:480b", "qwen3.5:122b", "qwen3.5:4b", "qwen3-vl:235b"])]
    assert order[:2] == ["qwen3.5:4b", "qwen3.5:122b"]
    assert "qwen3-coder:480b" not in order and "qwen3-vl:235b" not in order


def test_pick_first_model_that_works(tmp_path):
    fails = {"mistral-large-4": (500, "model overloaded")}  # one model down: the next one is tried
    with FakeOllama(lambda k, u, b: {"sentence": "The cap is not included.", "count": 3},
                    models=KEY_MODELS, api_key=KEY, fail_models=fails) as f:
        c = OllamaClient(f.url, 30, api_key=KEY, cloud=True)
        res = pick_model(c)
    assert res["ok"] and res["model"] == "gemma4:31b"
    assert [t[0] for t in res["tried"]] == ["mistral-large-4", "gemma4:31b"]


def test_pick_without_credits_stops_and_keeps_best(tmp_path):
    fails = {m: (402, "Add usage credits or subscribe") for m in KEY_MODELS}
    with FakeOllama(models=KEY_MODELS, api_key=KEY, fail_models=fails) as f:
        res = pick_model(OllamaClient(f.url, 30, api_key=KEY, cloud=True))
        assert len(f.calls) == 1  # an account problem: no need to try every model
    assert not res["ok"] and res["model"] == "mistral-large-4" and "usage credits" in res["reason"]


def test_auto_model_resolved_by_server(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app import config
    monkeypatch.setattr(config, "KEY_FILE", tmp_path / "none.txt")
    save_api_key(KEY, tmp_path / "ud")
    with FakeOllama(echo_responder, models=KEY_MODELS, api_key=KEY) as f:
        app = create_app(tmp_path / "ud")
        s = app.state.settings["settings"]
        s.ai_source, s.cloud_url, s.cloud_model, s.ollama_enabled = "cloud", f.url, "auto", True
        st = TestClient(app).get("/api/status").json()
    assert st["mode"] == "ai" and st["settings"]["active_model"] == "mistral-large-4"


def test_cli_pick_cloud_model(tmp_path, monkeypatch):
    from app import cli, config
    monkeypatch.setattr(cli, "USERDATA_DIR", tmp_path)
    monkeypatch.setattr(config, "USERDATA_DIR", tmp_path)
    monkeypatch.setattr(config, "KEY_FILE", tmp_path / "none.txt")
    save_api_key(KEY, tmp_path)
    with FakeOllama(lambda k, u, b: {"sentence": "x", "count": 1}, models=KEY_MODELS, api_key=KEY) as f:
        monkeypatch.setattr(config, "CLOUD_URL", f.url)
        real = config.load_settings
        monkeypatch.setattr(cli, "load_settings", lambda: (lambda s: (setattr(s, "cloud_url", f.url), s)[1])(real(userdata=tmp_path)))
        assert cli.main(["cli", "pick-cloud-model"]) == 0
    assert config.load_settings(userdata=tmp_path).cloud_model == "mistral-large-4"
