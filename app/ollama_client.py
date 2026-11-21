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
                 transport: httpx.BaseTransport | None = None, api_key: str | None = None, cloud: bool = False):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport
        self._api_key = api_key
        self.cloud = cloud
        self._think_supported: bool | None = None

    def _client(self, timeout: float | None = None) -> httpx.Client:
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        # A local Ollama is reached directly; Ollama Cloud may need the system's proxy settings.
        return httpx.Client(base_url=self.base_url, timeout=timeout or self.timeout, transport=self._transport,
                            trust_env=self.cloud, headers=headers)

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
            with self._client(timeout=10 if self.cloud else 5) as c:
                r = c.get("/api/tags")
                if r.status_code in (401, 403):
                    raise OllamaError("The Ollama Cloud API key was rejected.")
                r.raise_for_status()
                return [m.get("name", "") or m.get("model", "") for m in r.json().get("models", [])]
        except (httpx.HTTPError, ValueError) as e:
            raise OllamaError(f"Could not list models: {e}") from e

    @staticmethod
    def has_model(model: str, models: list[str]) -> bool:
        names = set(models) | {m.removesuffix("-cloud") for m in models}
        return model in names or model.removesuffix("-cloud") in names or (
            ":" not in model and any(m.split(":")[0] == model for m in names))

    def status(self, model: str) -> OllamaStatus:
        if self.cloud:
            if not self._api_key:
                return OllamaStatus(False, None, [], False, "No Ollama Cloud API key is set. Template mode still works.")
            try:
                models = self.tags()
            except OllamaError as e:
                msg = str(e) if "rejected" in str(e) else "Ollama Cloud is not reachable."
                return OllamaStatus(False, None, [], False, f"{msg} Template mode still works.")
            present = self.has_model(model, models)
            msg = (f"AI available via Ollama Cloud ({model}). Sentences and rule texts are sent to ollama.com."
                   if present else f"Ollama Cloud does not offer the model {model}. Template mode still works.")
            return OllamaStatus(True, "cloud", models, present, msg)
        try:
            v = self.version()
        except OllamaError:
            return OllamaStatus(False, None, [], False, "Ollama is not running. Template mode still works.")
        try:
            models = self.tags()
        except OllamaError:
            models = []
        present = self.has_model(model, models)
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
                if r.status_code in (401, 403):
                    raise OllamaError("The Ollama Cloud API key was rejected.")
                if r.status_code == 402:
                    raise OllamaError("Ollama Cloud needs usage credits or a plan for this account (see https://ollama.com/plans).")
                if r.status_code == 429:
                    raise OllamaError("Ollama Cloud's usage limit was reached for now.")
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


def make_client(settings, userdata=None, transport: httpx.BaseTransport | None = None) -> OllamaClient:
    """The client for the configured AI source. The API key is only ever sent to the cloud URL."""
    from .config import load_api_key

    if settings.cloud:
        return OllamaClient(settings.cloud_url, settings.ollama_timeout_s, transport=transport,
                            api_key=load_api_key(userdata), cloud=True)
    return OllamaClient(settings.ollama_url, settings.ollama_timeout_s, transport=transport)
