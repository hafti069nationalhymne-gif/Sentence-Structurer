"""Configuration: config.toml plus user overrides in userdata/settings.json."""
from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = ROOT / "knowledge" / "data"
LIBRARY_DIR = ROOT / "library"
STATIC_DIR = ROOT / "app" / "static"
PROMPTS_DIR = ROOT / "app" / "prompts"
USERDATA_DIR = ROOT / "userdata"
LOG_DIR = ROOT / "logs"

BIND_HOST = "127.0.0.1"  # never configurable: the app is local-only
CLOUD_URL = "https://ollama.com"  # the only remote host the optional cloud mode may call
API_KEY_RE = re.compile(r"^[A-Za-z0-9._\-]{20,200}$")


@dataclass
class Settings:
    port: int = 0
    ollama_enabled: bool = True
    ollama_url: str = "http://127.0.0.1:11434"
    chat_model: str = "qwen3.5:4b"
    chat_model_large: str = "gpt-oss:20b"
    ollama_timeout_s: float = 90.0
    ai_source: str = "local"          # "local" (Ollama on this computer) or "cloud" (Ollama Cloud with an API key)
    cloud_url: str = CLOUD_URL
    cloud_model: str = "gpt-oss:20b"
    review_mode: bool = False
    usability_mode: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def cloud(self) -> bool:
        return self.ai_source == "cloud"

    @property
    def active_model(self) -> str:
        return self.cloud_model if self.cloud else self.chat_model

    @property
    def active_url(self) -> str:
        return self.cloud_url if self.cloud else self.ollama_url

    def public(self) -> dict:
        d = asdict(self)
        d.pop("extra", None)
        d["active_model"] = self.active_model
        return d


EDITABLE = {"ollama_enabled": bool, "chat_model": str, "review_mode": bool, "usability_mode": bool,
            "ai_source": str, "cloud_model": str}


# ---- Ollama Cloud API key: stored only on this computer, never returned by the API -------------
def api_key_file(userdata: Path | None = None) -> Path:
    return (userdata or USERDATA_DIR) / "ollama_api_key.txt"


def load_api_key(userdata: Path | None = None) -> str | None:
    env = os.environ.get("OLLAMA_API_KEY", "").strip()
    if env and API_KEY_RE.fullmatch(env):
        return env
    f = api_key_file(userdata)
    if f.exists():
        key = f.read_text(encoding="utf-8").strip()
        if API_KEY_RE.fullmatch(key):
            return key
    return None


def save_api_key(key: str, userdata: Path | None = None) -> None:
    """Store the key (or delete it when empty). Raises ValueError for anything that does not look like a key."""
    f = api_key_file(userdata)
    key = (key or "").strip()
    if not key:
        f.unlink(missing_ok=True)
        return
    if not API_KEY_RE.fullmatch(key):
        raise ValueError("this does not look like an Ollama API key")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(key, encoding="utf-8")
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass


def _settings_file(userdata: Path) -> Path:
    return userdata / "settings.json"


def load_settings(config_path: Path | None = None, userdata: Path | None = None) -> Settings:
    config_path = config_path or ROOT / "config.toml"
    userdata = userdata or USERDATA_DIR
    s = Settings()
    if config_path.exists():
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        srv, oll, app = data.get("server", {}), data.get("ollama", {}), data.get("app", {})
        s.port = int(srv.get("port", s.port))
        s.ollama_enabled = bool(oll.get("enabled", s.ollama_enabled))
        url = str(oll.get("url", s.ollama_url))
        # Ollama must be local as well; a remote URL is refused.
        if url.startswith("http://127.0.0.1") or url.startswith("http://localhost"):
            s.ollama_url = url
        s.chat_model = str(oll.get("chat_model", s.chat_model))
        s.chat_model_large = str(oll.get("chat_model_large", s.chat_model_large))
        src = str(oll.get("source", s.ai_source))
        s.ai_source = src if src in ("local", "cloud") else "local"
        s.cloud_model = str(oll.get("cloud_model", s.cloud_model))
        # The cloud URL is fixed: the API key may only ever be sent to Ollama Cloud.
        s.ollama_timeout_s = float(oll.get("timeout_s", s.ollama_timeout_s))
        s.review_mode = bool(app.get("review_mode", s.review_mode))
        s.usability_mode = bool(app.get("usability_mode", s.usability_mode))
    f = _settings_file(userdata)
    if f.exists():
        try:
            override = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            override = {}
        for k, typ in EDITABLE.items():
            if k in override and isinstance(override[k], typ):
                setattr(s, k, override[k])
    if s.ai_source not in ("local", "cloud"):
        s.ai_source = "local"
    return s


def save_settings(s: Settings, userdata: Path | None = None) -> None:
    userdata = userdata or USERDATA_DIR
    userdata.mkdir(parents=True, exist_ok=True)
    data = {k: getattr(s, k) for k in EDITABLE}
    _settings_file(userdata).write_text(json.dumps(data, indent=2), encoding="utf-8")
