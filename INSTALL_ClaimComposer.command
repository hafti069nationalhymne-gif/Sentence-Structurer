#!/usr/bin/env bash
# Installs ClaimComposer for this user on macOS: ~/Applications/ClaimComposer, an app in ~/Applications and a Desktop alias.
set -u
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
xattr -dr com.apple.quarantine "$SRC" 2>/dev/null || true
DEST="${CC_INSTALL_DIR:-$HOME/Applications/ClaimComposer}"
. "$SRC/installer/install_common.sh"
cc_copy_app "$SRC" "$DEST"
export CC_ROOT="$DEST"
. "$DEST/installer/common.sh"
cc_setup
APP="$HOME/Applications/ClaimComposer.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cat > "$APP/Contents/MacOS/ClaimComposer" <<EOS
#!/bin/bash
open -a Terminal "$DEST/START_ClaimComposer.command"
EOS
chmod +x "$APP/Contents/MacOS/ClaimComposer"
cat > "$APP/Contents/Info.plist" <<EOS
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>ClaimComposer</string>
<key>CFBundleExecutable</key><string>ClaimComposer</string>
<key>CFBundleIdentifier</key><string>local.claimcomposer</string>
<key>CFBundleIconFile</key><string>icon</string>
<key>CFBundlePackageType</key><string>APPL</string>
</dict></plist>
EOS
if command -v sips >/dev/null 2>&1 && command -v iconutil >/dev/null 2>&1; then
  SET="$CC_TOOLS/icon.iconset"; mkdir -p "$SET"
  for s in 16 32 128 256 512; do sips -z $s $s "$DEST/installer/icon.png" --out "$SET/icon_${s}x${s}.png" >/dev/null 2>&1; done
  iconutil -c icns "$SET" -o "$APP/Contents/Resources/icon.icns" 2>/dev/null || true
fi
ln -sfn "$APP" "$HOME/Desktop/ClaimComposer" 2>/dev/null || true
say "ClaimComposer is installed. Start it from Applications or the Desktop alias."
