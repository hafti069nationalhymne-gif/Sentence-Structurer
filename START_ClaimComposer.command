#!/usr/bin/env bash
# ClaimComposer for macOS: double-click this file in Finder to set up once and start the app.
CC_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export CC_ROOT
# Files downloaded from the internet are quarantined; clear the flag for this folder only.
xattr -dr com.apple.quarantine "$CC_ROOT" 2>/dev/null || true
# shellcheck source=installer/common.sh
. "$CC_ROOT/installer/common.sh"
cc_setup
cc_run
