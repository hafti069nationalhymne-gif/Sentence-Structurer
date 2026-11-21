"""Build dist/ClaimComposer-portable.zip: the app without .venv, .tools, logs or user data.

Usage: uv run python scripts/build_release.py            # local AI variant
       uv run python scripts/build_release.py --cloud    # dist/ClaimComposer-cloud.zip: Ollama Cloud preselected
The cloud variant contains no API key: the launcher asks for it once and stores it in userdata/.
Executable bits for the macOS and Linux launchers are kept in the zip.
"""
from __future__ import annotations

import stat
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
EXCLUDE_DIRS = {".venv", ".tools", "logs", "userdata", ".git", "dist", "__pycache__", ".pytest_cache", "drafts", ".claude", "screenshots"}
EXCLUDE_FILES = {".DS_Store", "Environmental_Claims_RAG_Complete.zip", "ollama_api_key.txt", "default_choice.txt"}
EXECUTABLE = {".sh", ".command"}


def included(p: Path) -> bool:
    rel = p.relative_to(ROOT)
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return False
    return p.is_file() and p.name not in EXCLUDE_FILES and not p.name.endswith((".pyc", ".sqlite"))


def build(cloud: bool = False) -> Path:
    DIST.mkdir(exist_ok=True)
    out = DIST / ("ClaimComposer-cloud.zip" if cloud else "ClaimComposer-portable.zip")
    files = sorted(p for p in ROOT.rglob("*") if included(p))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            arc = Path("ClaimComposer") / p.relative_to(ROOT)
            info = zipfile.ZipInfo.from_file(p, arc.as_posix())
            mode = 0o755 if p.suffix in EXECUTABLE else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            data = p.read_bytes()
            if cloud and p == ROOT / "config.toml":
                data = data.replace(b'source = "local"', b'source = "cloud"')
            z.writestr(info, data)
        if cloud:
            info = zipfile.ZipInfo("ClaimComposer/installer/default_choice.txt")
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            z.writestr(info, "3\n")
    print(f"wrote {out.relative_to(ROOT)} with {len(files)} files ({out.stat().st_size / 1e6:.1f} MB)")
    return out


if __name__ == "__main__":
    build(cloud="--cloud" in sys.argv)
    sys.exit(0)
