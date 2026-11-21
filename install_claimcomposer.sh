#!/usr/bin/env bash
# Installs ClaimComposer for this user on Linux: ~/.local/share/claimcomposer, a menu entry and a desktop shortcut.
set -u
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${CC_INSTALL_DIR:-$HOME/.local/share/claimcomposer}"
. "$SRC/installer/install_common.sh"
cc_copy_app "$SRC" "$DEST"
export CC_ROOT="$DEST"
. "$DEST/installer/common.sh"
cc_setup
APPS="$HOME/.local/share/applications"; mkdir -p "$APPS"
ENTRY="[Desktop Entry]
Type=Application
Name=ClaimComposer
Comment=Regulation-based environmental claims (research prototype)
Exec=bash \"$DEST/start_claimcomposer.sh\"
Icon=$DEST/installer/icon.png
Terminal=true
Categories=Office;"
printf '%s\n' "$ENTRY" > "$APPS/claimcomposer.desktop"
DESK="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$DESK" ]; then
  printf '%s\n' "$ENTRY" > "$DESK/ClaimComposer.desktop"; chmod +x "$DESK/ClaimComposer.desktop"
  command -v gio >/dev/null 2>&1 && gio set "$DESK/ClaimComposer.desktop" metadata::trusted true 2>/dev/null || true
fi
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" >/dev/null 2>&1 || true
say "ClaimComposer is installed in $DEST. Start it from the menu or the desktop shortcut."
