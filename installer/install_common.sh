#!/usr/bin/env bash
# Copy the app to the install folder, leaving out environments, tools, logs and user data.
cc_copy_app() {
  local src="$1" dest="$2"
  mkdir -p "$dest"
  if [ "$src" = "$dest" ]; then return; fi
  ( cd "$src" && tar --exclude=./.venv --exclude=./.tools --exclude=./logs --exclude=./userdata --exclude=./.git \
      --exclude=./dist --exclude='*/__pycache__' --exclude=./.pytest_cache -cf - . ) | ( cd "$dest" && tar -xf - )
  chmod +x "$dest"/*.sh "$dest"/*.command 2>/dev/null || true
  echo "Copied ClaimComposer to $dest"
}
