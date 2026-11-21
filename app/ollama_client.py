"""Minimal client for the local Ollama API (http://127.0.0.1:11434).

Only these endpoints are used: GET /api/version, GET /api/tags, POST /api/pull and
POST /api/chat (stream false, JSON Schema in `format`, temperature 0, seed 42).
Every failure is reported as OllamaError so callers can fall back to template mode.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx


class OllamaError(Exception):
    pass


@dataclass
class OllamaStatus:
    available: bool
    version: str | None
    models: list[str]
    model_present: bool
    message: str

    def as_dict(self) -> dict:
        return self.__dict__.copy()


class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", timeout: float = 90.0,
                 transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport
        self._think_supported: bool | None = None

    def _client(self, timeout: float | None = None) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=timeout or self.timeout, transport=self._transport,
                            trust_env=False)

    def version(self) -> str:
        try:
            with self._client(timeout=3) as c:
                r = c.get("/api/version")
                r.raise_for_status()
                return r.json().get("version", "unknown")
        except (httpx.HTTPError, ValueError) as e:
            raise OllamaError(f"Ollama is not reachable: {e}") from e

    def tags(self) -> list[str]:
        try:
            with self._client(timeout=5) as c:
                r = c.get("/api/tags")
                r.raise_for_status()
                return [m.get("name", "") for m in r.json().get("models", [])]
        except (httpx.HTTPError, ValueError) as e:
            raise OllamaError(f"Could not list models: {e}") from e

    def status(self, model: str) -> OllamaStatus:
        try:
            v = self.version()
        except OllamaError:
            return OllamaStatus(False, None, [], False, "Ollama is not running. Template mode still works.")
        try:
            models = self.tags()
        except OllamaError:
            models = []
        present = model in models or (":" not in model and any(m.split(":")[0] == model for m in models))
        msg = "AI available." if present else f"Model {model} is not installed. Template mode still works."
        return OllamaStatus(True, v, models, present, msg)

    def pull(self, model: str, progress=None) -> None:
        """Pull a model, streaming progress lines to `progress(dict)`."""
        try:
            with self._client(timeout=None) as c:
                with c.stream("POST", "/api/pull", json={"model": model, "stream": True}, timeout=None) as r:
                    r.raise_for_status()
                    for line in r.iter_lines():
                        if line and progress:
                            progress(json.loads(line))
        except (httpx.HTTPError, ValueError) as e:
            raise OllamaError(f"Pull failed: {e}") from e

    def chat_json(self, model: str, system: str, user: str, schema: dict[str, Any]) -> dict:
        """One non-streaming chat call constrained by a JSON Schema. Returns the parsed object."""
        body: dict[str, Any] = {
            "model": model,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0, "seed": 42},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if self._think_supported is not False:
            body["think"] = False
        try:
            with self._client() as c:
                r = c.post("/api/chat", json=body)
                if r.status_code == 400 and "think" in body and "think" in r.text.lower():
                    # Older Ollama or a model without thinking support: retry without the flag.
                    self._think_supported = False
                    body.pop("think")
                    r = c.post("/api/chat", json=body)
                r.raise_for_status()
                content = r.json().get("message", {}).get("content", "")
        except httpx.HTTPError as e:
            raise OllamaError(f"Chat call failed: {e}") from e
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise OllamaError("Model did not return valid JSON") from e
        if not isinstance(data, dict):
            raise OllamaError("Model returned JSON that is not an object")
        return data
