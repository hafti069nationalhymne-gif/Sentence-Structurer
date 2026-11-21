#!/usr/bin/env bash
# Removes the ClaimComposer installation for this user on macOS.
set -u
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${CC_INSTALL_DIR:-$HOME/Applications/ClaimComposer}"
. "$SRC/installer/uninstall_common.sh"
cc_uninstall "$DEST" "$HOME/Applications/ClaimComposer.app" "$HOME/Desktop/ClaimComposer"
