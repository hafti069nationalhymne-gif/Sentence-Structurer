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
    # Whole-line comments first: quotes inside comments (e.g. "the app's") are not strings.
    src = "\n".join("" if l.strip().startswith("#") else l for l in src.splitlines())
    code = re.sub(r'"(?:[^"`]|`.)*"', '""', src)
    code = re.sub(r"'[^']*'", "''", code)
    code = "\n".join(l.split("#")[0] if not l.strip().startswith("#") else "" for l in code.splitlines())
    for a, b in ("{}", "()", "[]"):
        assert code.count(a) == code.count(b), f"unbalanced {a}{b}"
    for needed in ("irm https://astral.sh/uv/install.ps1 | iex", "UV_INSTALL_DIR", '@("python", "install", "3.12")',
                   '@("sync", "--frozen", "--no-dev", "--python", "3.12")',
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


def test_windows_setup_survives_stderr_and_broken_pythons():
    """Regression: a broken python3.12.exe on PATH made `uv python find` write to stderr, which aborted the
    script under $ErrorActionPreference = "Stop" in Windows PowerShell 5.1."""
    src = (ROOT / "installer/setup.ps1").read_text(encoding="utf-8")
    assert '$ErrorActionPreference = "Stop"' not in src and '$ErrorActionPreference = "Continue"' in src
    assert "*>" not in src, "native output must go through Native, not *> redirects"
    assert 'UV_PYTHON_PREFERENCE = "only-managed"' in src and "UV_PYTHON_BIN_DIR" in src
    assert "function Native" in src
    sh = (ROOT / "installer/common.sh").read_text()
    assert "only-managed" in sh and "UV_PYTHON_BIN_DIR" in sh


def test_windows_setup_handles_application_control_block():
    """Regression: Smart App Control blocked .venv\\Scripts\\python.exe, and the script then wrongly said the
    API key was invalid. Now it picks a Python that Windows allows and never blames the key for that."""
    src = (ROOT / "installer/setup.ps1").read_text(encoding="utf-8")
    assert "function ChooseRunnablePython" in src and "EnsureRunnablePython" in src
    assert ".venv\\\\Scripts\\\\python.exe" in src.replace("\\", "\\\\") or ".venv\\Scripts\\python.exe" in src
    assert "PythonCore\\3.12\\InstallPath" in src  # official python.org builds only
    assert "winget install --id Python.Python.3.12" in src
    assert "$env:PYTHONPATH = $SitePackages" in src
    assert "return -1" in src and "WindowsBlocked" in src
    i = src.index("function SetupCloud")
    cloud = src[i:src.index("function Setup {")]
    assert "$code -eq 4" in cloud and "could not run" in cloud  # only exit code 4 means "not a key"
    setup = src[src.index("function Setup {"):]
    assert setup.index("SyncEnv") < setup.index("EnsureRunnablePython") < setup.index("SetupCloud")
    sh = (ROOT / "installer/common.sh").read_text()
    assert '"$code" -eq 4' in sh and "could not run" in sh
