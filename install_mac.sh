#!/bin/bash
# Install (symlink) the Zortrax plugin into the newest Cura config folder on macOS.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)/plugins/ZortraxM"
BASE="$HOME/Library/Application Support/cura"
VER=$(ls "$BASE" 2>/dev/null | grep -E '^[0-9]+\.[0-9]+$' | sort -V | tail -1)
if [ -z "$VER" ]; then echo "Start Cura once first so it creates $BASE/<version>"; exit 1; fi
mkdir -p "$BASE/$VER/plugins"
rm -rf "$BASE/$VER/plugins/ZortraxM"
ln -s "$SRC" "$BASE/$VER/plugins/ZortraxM"
echo "Linked $SRC -> $BASE/$VER/plugins/ZortraxM. Restart Cura, then add a printer: Zortrax > Zortrax M200 Plus."
