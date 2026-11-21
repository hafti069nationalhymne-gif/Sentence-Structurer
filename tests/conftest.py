import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import Settings  # noqa: E402
from app.knowledge import get_knowledge  # noqa: E402
from app.library import get_library  # noqa: E402


@pytest.fixture(scope="session")
def kb():
    return get_knowledge()


@pytest.fixture(scope="session")
def lib():
    return get_library()


@pytest.fixture
def off():
    """Settings with the AI switched off: pure template mode."""
    return Settings(ollama_enabled=False)


@pytest.fixture
def api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app(tmp_path / "userdata")
    # Hermetic: never talk to an Ollama that happens to run on this machine.
    app.state.settings["settings"].ollama_enabled = False
    return TestClient(app)


def segment_with(kb, rules, name=None):
    """Pick an ECLASS segment by the rules it routes to (never a hard-coded number)."""
    from app.knowledge import split_ids

    for row in kb.eclass:
        routed = set(split_ids(row["product_rule_ids"]))
        if set(rules) <= routed and (name is None or name.lower() in row["segment_name"].lower()):
            return row["eclass_segment"]
    raise LookupError(f"no segment routes {rules} ({name})")
