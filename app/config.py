"""Configuration: config.toml plus user overrides in userdata/settings.json."""
from __future__ import annotations

import json
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


@dataclass
class Settings:
    port: int = 0
    ollama_enabled: bool = True
    ollama_url: str = "http://127.0.0.1:11434"
    chat_model: str = "qwen3.5:4b"
    chat_model_large: str = "gpt-oss:20b"
    ollama_timeout_s: float = 90.0
    review_mode: bool = False
    usability_mode: bool = False
    extra: dict = field(default_factory=dict)

    def public(self) -> dict:
        d = asdict(self)
        d.pop("extra", None)
        return d


EDITABLE = {"ollama_enabled": bool, "chat_model": str, "review_mode": bool, "usability_mode": bool}


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
    return s


def save_settings(s: Settings, userdata: Path | None = None) -> None:
    userdata = userdata or USERDATA_DIR
    userdata.mkdir(parents=True, exist_ok=True)
    data = {k: getattr(s, k) for k in EDITABLE}
    _settings_file(userdata).write_text(json.dumps(data, indent=2), encoding="utf-8")
