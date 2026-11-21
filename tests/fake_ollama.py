"""A fake Ollama server for unit tests. It speaks the four endpoints ClaimComposer uses."""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def data_block(text: str) -> str:
    m = re.search(r"<data>\s*(.*?)\s*</data>", text, re.S)
    return m.group(1) if m else ""


class FakeOllama:
    """Run with `with FakeOllama(responder) as f: f.url`. `responder(kind, user_prompt, body) -> dict`."""

    def __init__(self, responder=None, models=("qwen3.5:4b",), version="0.12.0", api_key=None, fail_models=None):
        """With api_key set it behaves like Ollama Cloud: Bearer auth required, no /api/version."""
        self.responder = responder or echo_responder
        self.models = list(models)
        self.version = version
        self.api_key = api_key
        self.calls: list[dict] = []
        self.auth_headers: list[str | None] = []
        self.fail_models = dict(fail_models or {})  # model -> (status, error text), like Ollama Cloud's 402
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _authorised(self):
                fake.auth_headers.append(self.headers.get("Authorization"))
                if fake.api_key is None:
                    return True
                if self.headers.get("Authorization") != f"Bearer {fake.api_key}":
                    self._json(401, {"error": "unauthorized"})
                    return False
                return True

            def do_GET(self):
                if not self._authorised():
                    return
                if self.path == "/api/version":
                    if fake.api_key is not None:
                        return self._json(404, {"error": "not found"})
                    return self._json(200, {"version": fake.version})
                if self.path == "/api/tags":
                    return self._json(200, {"models": [{"name": m} for m in fake.models]})
                self._json(404, {"error": "not found"})

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                if not self._authorised():
                    return
                if self.path == "/api/pull":
                    fake.models.append(body.get("model"))
                    return self._json(200, {"status": "success"})
                if self.path == "/api/chat":
                    fake.calls.append(body)
                    if body.get("model") in fake.fail_models:
                        code, err = fake.fail_models[body["model"]]
                        return self._json(code, {"error": err})
                    user = body["messages"][-1]["content"]
                    kind = "why" if "why the recommended sentence fits" in user else (
                        "translate" if "Translate the sentence" in user else "tone")
                    content = fake.responder(kind, user, body)
                    return self._json(200, {"message": {"role": "assistant", "content": json.dumps(content)}, "done": True})
                self._json(404, {"error": "not found"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._t = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()


def first_chunk_id(user: str) -> str:
    m = re.search(r"chunk_id=([A-Za-z0-9_.-]+)", user)
    return m.group(1) if m else "NONE"


def echo_responder(kind, user, body):
    """Well-behaved model: returns the sentence unchanged and a correct, cited explanation."""
    if kind == "why":
        return {"why": "It states the measured share and names the evidence, as the rule requires.",
                "chunk_ids": [first_chunk_id(user)]}
    return {"sentence": data_block(user)}
