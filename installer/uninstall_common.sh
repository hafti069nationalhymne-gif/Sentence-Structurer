#!/usr/bin/env bash
# Shared uninstall steps: remove the app folder, then ask separately about the AI model.
cc_uninstall() {
  local dest="$1"; shift
  echo "This removes ClaimComposer from $dest, its shortcuts and its local data (tickets and reviews)."
  read -r -p "Remove ClaimComposer? [y/N] " a || a=""
  case "$a" in y|Y|yes|j|J) ;; *) echo "Nothing was removed."; return 0 ;; esac
  local model=""
  if [ -f "$dest/userdata/settings.json" ]; then
    model="$(sed -n 's/.*"chat_model": *"\([^"]*\)".*/\1/p' "$dest/userdata/settings.json" | head -1)"
  fi
  for f in "$@"; do rm -rf -- "$f"; done
  case "$dest" in
    */claimcomposer|*/ClaimComposer) rm -rf -- "$dest" ;;
    *) echo "Unexpected install folder '$dest'; not removed." ;;
  esac
  echo "ClaimComposer was removed."
  if command -v ollama >/dev/null 2>&1 && [ -n "$model" ]; then
    read -r -p "Also remove the AI model $model from Ollama (frees several GB)? [y/N] " b || b=""
    case "$b" in y|Y|yes|j|J) ollama rm "$model" && echo "Model removed." ;; *) echo "The model was kept." ;; esac
    echo "Ollama itself stays installed; remove it with your system's usual tools if you no longer need it."
  fi
}
