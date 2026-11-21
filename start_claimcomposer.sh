#!/usr/bin/env bash
# ClaimComposer for Linux: double-click (or run) this file to set up once and start the app.
CC_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export CC_ROOT
# Re-open in a terminal when started from a file manager without one.
if [ ! -t 0 ] && [ -z "${CC_IN_TERMINAL:-}" ]; then
  export CC_IN_TERMINAL=1
  for term in x-terminal-emulator gnome-terminal konsole xfce4-terminal xterm; do
    if command -v "$term" >/dev/null 2>&1; then
      case "$term" in
        gnome-terminal) exec gnome-terminal -- bash "$CC_ROOT/start_claimcomposer.sh" ;;
        *) exec "$term" -e bash "$CC_ROOT/start_claimcomposer.sh" ;;
      esac
    fi
  done
fi
# shellcheck source=installer/common.sh
. "$CC_ROOT/installer/common.sh"
cc_setup
cc_run
