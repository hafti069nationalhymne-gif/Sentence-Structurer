"""Small helper commands used by the launchers.

    python -m app.cli hardware        # prints RAM and GPU memory in GB
    python -m app.cli choose-model    # prints the model to use for this hardware
    python -m app.cli set-model NAME  # stores the model in userdata/settings.json
    python -m app.cli set-ai on|off   # switches the optional AI on or off
    python -m app.cli verify-model [NAME]  # JSON Schema test against the configured Ollama (exit 1 if it fails)
    python -m app.cli set-cloud       # reads an Ollama Cloud API key from stdin (or OLLAMA_API_KEY) and switches to the cloud
    python -m app.cli set-local       # switches back to a local Ollama
    python -m app.cli check           # loads the knowledge base and library (exit 1 on error)
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys

from .config import USERDATA_DIR, load_settings, save_api_key, save_settings

LARGE, SMALL = "gpt-oss:20b", "qwen3.5:4b"


def ram_gb() -> float:
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) / 1024 / 1024
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5).stdout
            return int(out.strip()) / 1024 ** 3
        if sys.platform.startswith("win"):
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys / 1024 ** 3
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return 0.0


def gpu_gb() -> float:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return 0.0
    try:
        out = subprocess.run([exe, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        vals = [int(x.strip()) for x in out.splitlines() if x.strip().isdigit()]
        return max(vals) / 1024 if vals else 0.0
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0.0


def choose_model(ram: float | None = None, gpu: float | None = None) -> str:
    """16 GB GPU memory or 32 GB RAM -> the larger model, otherwise the small one (see docs/MODEL_CHOICE.md)."""
    ram = ram_gb() if ram is None else ram
    gpu = gpu_gb() if gpu is None else gpu
    return LARGE if (gpu >= 15.5 or ram >= 31.0) else SMALL


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "help"
    if cmd == "hardware":
        print(json.dumps({"ram_gb": round(ram_gb(), 1), "gpu_gb": round(gpu_gb(), 1), "os": platform.platform()}))
        return 0
    if cmd == "choose-model":
        print(choose_model())
        return 0
    if cmd in ("set-model", "set-ai"):
        s = load_settings()
        if cmd == "set-model":
            if s.cloud:
                s.cloud_model = argv[2]
            else:
                s.chat_model = argv[2]
        else:
            s.ollama_enabled = argv[2] == "on"
        save_settings(s, USERDATA_DIR)
        print("ok")
        return 0
    if cmd == "set-cloud":
        # The key comes from stdin or the environment, never from the command line (it would show in process lists).
        key = os.environ.get("OLLAMA_API_KEY", "").strip() or sys.stdin.readline().strip()
        try:
            save_api_key(key, USERDATA_DIR)
        except ValueError as e:
            print(f"FAIL: {e}")
            return 1
        s = load_settings()
        s.ai_source, s.ollama_enabled = "cloud", True
        save_settings(s, USERDATA_DIR)
        print(f"ok: Ollama Cloud with model {s.cloud_model}")
        return 0
    if cmd == "set-local":
        s = load_settings()
        s.ai_source = "local"
        save_settings(s, USERDATA_DIR)
        print("ok")
        return 0
    if cmd == "verify-model":
        from .ollama_client import OllamaError, make_client

        s = load_settings()
        model = argv[2] if len(argv) > 2 else s.active_model
        schema = {"type": "object", "properties": {"sentence": {"type": "string"}, "count": {"type": "integer"}},
                  "required": ["sentence", "count"]}
        try:
            client = make_client(s)
            client.timeout = 300
            out = client.chat_json(
                model, "Answer with JSON only.",
                'Return {"sentence": "The cap is not included.", "count": 3} exactly.', schema)
        except OllamaError as e:
            print(f"FAIL {model}: {e}")
            return 1
        ok = isinstance(out.get("sentence"), str) and isinstance(out.get("count"), int)
        print(("OK " if ok else "FAIL ") + f"{model}: {out}")
        return 0 if ok else 1
    if cmd == "check":
        from .knowledge import get_knowledge
        from .library import get_library

        kb, lib = get_knowledge(), get_library()
        print(f"knowledge {len(kb.chunks)} passages, {len(kb.rules)} rules; library {len(lib.templates)} templates")
        return 0
    print(__doc__)
    return 0 if cmd == "help" else 2


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    sys.exit(main(sys.argv))
