"""Build dist/ClaimComposer-portable.zip: the app without .venv, .tools, logs or user data.

Usage: uv run python scripts/build_release.py
Executable bits for the macOS and Linux launchers are kept in the zip.
"""
from __future__ import annotations

import stat
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
EXCLUDE_DIRS = {".venv", ".tools", "logs", "userdata", ".git", "dist", "__pycache__", ".pytest_cache", "drafts", ".claude"}
EXCLUDE_FILES = {".DS_Store", "Environmental_Claims_RAG_Complete.zip"}
EXECUTABLE = {".sh", ".command"}


def included(p: Path) -> bool:
    rel = p.relative_to(ROOT)
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return False
    return p.is_file() and p.name not in EXCLUDE_FILES and not p.name.endswith((".pyc", ".sqlite"))


def build() -> Path:
    DIST.mkdir(exist_ok=True)
    out = DIST / "ClaimComposer-portable.zip"
    files = sorted(p for p in ROOT.rglob("*") if included(p))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            arc = Path("ClaimComposer") / p.relative_to(ROOT)
            info = zipfile.ZipInfo.from_file(p, arc.as_posix())
            mode = 0o755 if p.suffix in EXECUTABLE else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, p.read_bytes())
    print(f"wrote {out.relative_to(ROOT)} with {len(files)} files ({out.stat().st_size / 1e6:.1f} MB)")
    return out


if __name__ == "__main__":
    build()
    sys.exit(0)
