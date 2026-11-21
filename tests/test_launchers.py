"""Launch scripts pass a syntax check on the platforms available here (bash; static checks for Windows files)."""
import os
import re
import shutil
import subprocess
import zipfile

import pytest

from app.config import ROOT

SHELL = ["start_claimcomposer.sh", "install_claimcomposer.sh", "uninstall_claimcomposer.sh",
         "START_ClaimComposer.command", "INSTALL_ClaimComposer.command", "UNINSTALL_ClaimComposer.command",
         "installer/common.sh", "installer/install_common.sh", "installer/uninstall_common.sh"]
BAT = ["START_ClaimComposer.bat", "INSTALL_ClaimComposer.bat", "UNINSTALL_ClaimComposer.bat"]


@pytest.mark.parametrize("name", SHELL)
def test_shell_syntax_lf_and_executable(name):
    p = ROOT / name
    data = p.read_bytes()
    assert b"\r\n" not in data, "shell files use LF"
    assert data.startswith(b"#!/usr/bin/env bash")
    assert os.access(p, os.X_OK), "executable bit"
    subprocess.run(["bash", "-n", str(p)], check=True)


def test_shellcheck_if_available():
    import sys
    exe = shutil.which("shellcheck") or shutil.which("shellcheck", path=os.path.dirname(sys.executable))
    if not exe:
        pytest.skip("shellcheck not installed")
    subprocess.run([exe, "-S", "warning", "-x", *[str(ROOT / n) for n in SHELL]], check=True, cwd=ROOT)


@pytest.mark.parametrize("name", BAT)
def test_bat_crlf_and_targets(name):
    data = (ROOT / name).read_bytes()
    assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b""), "bat files use CRLF"
    text = data.decode("ascii")
    assert "installer\\setup.ps1" in text and "-ExecutionPolicy Bypass" in text
    mode = re.search(r"-Mode (\w+)", text).group(1)
    assert mode in ("start", "install", "uninstall")


def test_powershell_static_check():
    """No PowerShell here, so check structure: balanced brackets outside strings, modes, required commands."""
    src = (ROOT / "installer/setup.ps1").read_text(encoding="utf-8")
    pwsh = shutil.which("pwsh")
    if pwsh:
        cmd = f"$null = [System.Management.Automation.Language.Parser]::ParseFile('{ROOT / 'installer/setup.ps1'}', [ref]$null, [ref]$e); if ($e) {{ exit 1 }}"
        subprocess.run([pwsh, "-NoProfile", "-Command", cmd], check=True)
    code = re.sub(r'"(?:[^"`]|`.)*"', '""', src)
    code = re.sub(r"'[^']*'", "''", code)
    code = "\n".join(l.split("#")[0] if not l.strip().startswith("#") else "" for l in code.splitlines())
    for a, b in ("{}", "()", "[]"):
        assert code.count(a) == code.count(b), f"unbalanced {a}{b}"
    for needed in ("irm https://astral.sh/uv/install.ps1 | iex", "UV_INSTALL_DIR", "python install 3.12", "sync --frozen",
                   "winget install --id Ollama.Ollama -e", "OllamaSetup.exe", "--open", "LOCALAPPDATA", "setup.log"):
        assert needed in src, needed
    assert "$args" not in src.replace("$arguments", "")


def test_shell_setup_covers_required_steps():
    src = (ROOT / "installer/common.sh").read_text()
    for needed in ("https://astral.sh/uv/install.sh", "UV_INSTALL_DIR", "python install 3.12", "sync --frozen",
                   "https://ollama.com/install.sh", "brew install ollama", "sudo", "pull", "--open", "setup.log",
                   "free_disk_gb", "total_ram_gb", "trap cleanup"):
        assert needed in src, needed


def test_release_zip_excludes_local_state(tmp_path):
    subprocess.run(["python", "scripts/build_release.py"], cwd=ROOT, check=True, capture_output=True)
    z = zipfile.ZipFile(ROOT / "dist/ClaimComposer-portable.zip")
    names = z.namelist()
    assert "ClaimComposer/START_ClaimComposer.bat" in names and "ClaimComposer/knowledge/data/rules.jsonl" in names
    assert not any(re.search(r"/(\.venv|\.tools|logs|userdata|\.git)/", n) for n in names)
    info = z.getinfo("ClaimComposer/start_claimcomposer.sh")
    assert (info.external_attr >> 16) & 0o111
