#!/usr/bin/env bash
# Shared setup for ClaimComposer on macOS and Linux. Sourced by the launchers.
# Every step checks first and skips work that is already done, so re-running after an
# interruption continues safely. Everything goes to logs/setup.log.

set -u

CC_ROOT="${CC_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
CC_TOOLS="$CC_ROOT/.tools"
CC_LOG_DIR="$CC_ROOT/logs"
CC_LOG="$CC_LOG_DIR/setup.log"
CC_USERDATA="$CC_ROOT/userdata"
CC_CHOICE_FILE="$CC_USERDATA/setup_choice.txt"
OLLAMA_URL="http://127.0.0.1:11434"
OLLAMA_PID=""

mkdir -p "$CC_LOG_DIR" "$CC_USERDATA" "$CC_TOOLS"
export UV_INSTALL_DIR="$CC_TOOLS/uv"
export UV_PYTHON_INSTALL_DIR="$CC_TOOLS/python"
export UV_CACHE_DIR="$CC_TOOLS/uv-cache"
export UV_PROJECT_ENVIRONMENT="$CC_ROOT/.venv"
export UV_NO_MODIFY_PATH=1
export PYTHONUTF8=1
UV="$UV_INSTALL_DIR/uv"

say()  { printf '%s\n' "$*"; printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$CC_LOG"; }
log()  { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$CC_LOG"; }

fail() {
  # One plain-language message, the next step and the log path.
  say ""
  say "ClaimComposer could not finish setting up: $1"
  say "Next step: ${2:-check your internet connection and double-click the launcher again.}"
  say "Details are in: $CC_LOG"
  if [ -t 0 ]; then read -r -p "Press Enter to close this window." _ || true; fi
  exit 1
}

free_disk_gb() { df -Pk "$CC_ROOT" 2>/dev/null | awk 'NR==2 {printf "%d", $4/1024/1024}'; }
total_ram_gb() {
  if [ "$(uname -s)" = "Darwin" ]; then sysctl -n hw.memsize 2>/dev/null | awk '{printf "%d", $1/1024/1024/1024}'
  else awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo 2>/dev/null; fi
}

have_uv()      { [ -x "$UV" ]; }
have_python()  { have_uv && "$UV" python find 3.12 >/dev/null 2>&1; }
have_env()     { [ -x "$CC_ROOT/.venv/bin/python" ] && "$CC_ROOT/.venv/bin/python" -c "import fastapi, uvicorn, pydantic, httpx, yaml" >/dev/null 2>&1; }
have_ollama()  { command -v ollama >/dev/null 2>&1 || [ -x "/Applications/Ollama.app/Contents/Resources/ollama" ]; }
ollama_bin()   { command -v ollama 2>/dev/null || echo "/Applications/Ollama.app/Contents/Resources/ollama"; }
ollama_up()    { curl -fsS --max-time 2 "$OLLAMA_URL/api/version" >/dev/null 2>&1; }
model_present() { curl -fsS --max-time 4 "$OLLAMA_URL/api/tags" 2>/dev/null | grep -q "\"name\":\"$1\""; }

ask_first_run() {
  # Show what will be downloaded and ask once. The answer is remembered.
  if [ -f "$CC_CHOICE_FILE" ]; then CC_CHOICE="$(cat "$CC_CHOICE_FILE")"; return; fi
  local disk ram
  disk="$(free_disk_gb)"; ram="$(total_ram_gb)"
  say ""
  say "Welcome to ClaimComposer. This first start sets things up once:"
  have_uv     || say "  - uv, a small installer for Python                 (about 35 MB)"
  have_python || say "  - Python 3.12, only for this app (system Python untouched) (about 70 MB)"
  have_env    || say "  - the app's Python packages                         (about 40 MB)"
  say "  Optional AI for tone, translation and explanations:"
  have_ollama || say "  - Ollama, the local AI runtime                      (about 1.5 GB)"
  say "  - a language model: qwen3.5:4b (about 3.4 GB) or gpt-oss:20b on strong computers (about 14 GB)"
  say "  Free disk space here: ${disk:-?} GB · memory: ${ram:-?} GB"
  if [ -n "${disk:-}" ] && [ "$disk" -lt 2 ]; then
    fail "there is less than 2 GB of free disk space." "free some disk space, then start again."
  fi
  if [ -n "${disk:-}" ] && [ "$disk" -lt 20 ]; then say "  Warning: under 20 GB free. Choose 'Template mode only' unless you can free space."; fi
  if [ -n "${ram:-}" ] && [ "$ram" -lt 8 ]; then say "  Warning: under 8 GB of memory. The AI would be slow. Template mode is recommended."; fi
  say ""
  say "  [1] Install with AI      [2] Template mode only (works fully without AI)      [Q] Quit"
  local ans=""
  if [ -t 0 ]; then read -r -p "Your choice [1/2/Q]: " ans || ans="2"; else ans="${CC_DEFAULT_CHOICE:-2}"; fi
  case "$ans" in
    1) CC_CHOICE="ai" ;;
    2|"") CC_CHOICE="template" ;;
    *) say "Nothing was installed."; exit 0 ;;
  esac
  echo "$CC_CHOICE" > "$CC_CHOICE_FILE"
  log "choice: $CC_CHOICE"
}

install_uv() {
  have_uv && { log "uv present"; return; }
  say "Installing uv into $UV_INSTALL_DIR ..."
  command -v curl >/dev/null 2>&1 || fail "the tool 'curl' is missing." "install curl (for example: sudo apt install curl), then start again."
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$UV_INSTALL_DIR" UV_NO_MODIFY_PATH=1 sh >> "$CC_LOG" 2>&1 \
    || fail "uv could not be downloaded."
  have_uv || fail "uv was not found after installing."
}

install_python() {
  have_python && { log "python 3.12 present"; return; }
  say "Installing Python 3.12 for ClaimComposer only ..."
  "$UV" python install 3.12 >> "$CC_LOG" 2>&1 || fail "Python 3.12 could not be installed."
}

sync_env() {
  if have_env && [ "$CC_ROOT/.venv/.synced" -nt "$CC_ROOT/uv.lock" ] 2>/dev/null; then log "environment up to date"; return; fi
  say "Installing the app's packages ..."
  (cd "$CC_ROOT" && "$UV" sync --frozen --no-dev --python 3.12 >> "$CC_LOG" 2>&1) || fail "the app's packages could not be installed."
  touch "$CC_ROOT/.venv/.synced"
}

install_ollama() {
  have_ollama && { log "ollama present"; return 0; }
  say "Installing Ollama (optional local AI) ..."
  if [ "$(uname -s)" = "Darwin" ]; then
    if command -v brew >/dev/null 2>&1; then
      brew install ollama >> "$CC_LOG" 2>&1 || return 1
    else
      local zip="$CC_TOOLS/Ollama-darwin.zip"
      curl -fL --progress-bar -o "$zip" https://ollama.com/download/Ollama-darwin.zip || return 1
      mkdir -p "$HOME/Applications" && unzip -oq "$zip" -d "$HOME/Applications" >> "$CC_LOG" 2>&1 || return 1
      [ -x "$HOME/Applications/Ollama.app/Contents/Resources/ollama" ] && export PATH="$HOME/Applications/Ollama.app/Contents/Resources:$PATH"
    fi
  else
    say "The official Ollama installer may ask for your password (sudo)."
    curl -fsSL https://ollama.com/install.sh | sh 2>&1 | tee -a "$CC_LOG" || return 1
  fi
  have_ollama
}

start_ollama() {
  ollama_up && return 0
  say "Starting Ollama ..."
  "$(ollama_bin)" serve >> "$CC_LOG_DIR/ollama.log" 2>&1 &
  OLLAMA_PID=$!
  for _ in $(seq 1 30); do ollama_up && return 0; sleep 1; done
  return 1
}

pull_model() {
  local model
  model="$("$CC_ROOT/.venv/bin/python" -m app.cli choose-model 2>>"$CC_LOG")" || model="qwen3.5:4b"
  if [ -f "$CC_USERDATA/settings.json" ] && grep -q '"chat_model"' "$CC_USERDATA/settings.json"; then
    model="$("$CC_ROOT/.venv/bin/python" -c 'import json;print(json.load(open("userdata/settings.json"))["chat_model"])' 2>/dev/null || echo "$model")"
  fi
  if model_present "$model"; then log "model $model present"; else
    say "Downloading the language model $model (this can take a while; progress below) ..."
    "$(ollama_bin)" pull "$model" || return 1
  fi
  (cd "$CC_ROOT" && "$CC_ROOT/.venv/bin/python" -m app.cli set-model "$model" >> "$CC_LOG" 2>&1)
  say "Checking that $model answers in the required JSON format ..."
  if ! (cd "$CC_ROOT" && "$CC_ROOT/.venv/bin/python" -m app.cli verify-model "$model" >> "$CC_LOG" 2>&1); then
    say "The model did not pass the JSON test. ClaimComposer will use template mode."
    (cd "$CC_ROOT" && "$CC_ROOT/.venv/bin/python" -m app.cli set-ai off >> "$CC_LOG" 2>&1)
  fi
}

setup_ai() {
  if [ "${CC_CHOICE:-template}" != "ai" ]; then
    (cd "$CC_ROOT" && "$CC_ROOT/.venv/bin/python" -m app.cli set-ai off >> "$CC_LOG" 2>&1); return; fi
  if ! install_ollama; then say "Ollama could not be installed. ClaimComposer will run in template mode."; return; fi
  if ! start_ollama; then say "Ollama did not start. ClaimComposer will run in template mode."; return; fi
  pull_model || say "The model could not be downloaded. ClaimComposer will run in template mode."
}

cc_setup() {
  log "---- setup started in $CC_ROOT ($(uname -a))"
  ask_first_run
  install_uv
  install_python
  sync_env
  setup_ai
  log "setup finished"
}

cleanup() {
  [ -n "${SERVER_PID:-}" ] && kill "$SERVER_PID" 2>/dev/null
  [ -n "${OLLAMA_PID:-}" ] && kill "$OLLAMA_PID" 2>/dev/null
  log "launcher closed"
}

cc_run() {
  # Start the server and open the app window. Closing this window stops the server.
  trap cleanup EXIT INT TERM HUP
  say ""
  say "Starting ClaimComposer ... (keep this window open; close it to stop the app)"
  (cd "$CC_ROOT" && exec "$CC_ROOT/.venv/bin/python" -m app.main --open) &
  SERVER_PID=$!
  wait "$SERVER_PID"
}
