#!/usr/bin/env bash
# Removes the ClaimComposer installation for this user on Linux.
set -u
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${CC_INSTALL_DIR:-$HOME/.local/share/claimcomposer}"
. "$SRC/installer/uninstall_common.sh"
DESK="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
cc_uninstall "$DEST" "$HOME/.local/share/applications/claimcomposer.desktop" "$DESK/ClaimComposer.desktop"
