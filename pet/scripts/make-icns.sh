#!/usr/bin/env bash
# make-icns.sh — generate packaging/AppIcon.icns from the character PNG using
# only macOS built-ins (sips + iconutil), so CI and a clean checkout need no
# extra tooling. iconutil requires a fully-populated .iconset dir with the
# exact Apple naming; we render every slot from one source and hand it off.
set -euo pipefail

# Resolve our own location so this works from any cwd (invoked by make-app.sh,
# CI, or a shell wherever the caller happens to be).
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PET_DIR="$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"

SRC="$PET_DIR/Sources/ViduraPetKit/Resources/cat-content.png"
OUT="$PET_DIR/packaging/AppIcon.icns"

# Source is 384x384 pixel art. The 512@2x=1024 slot upscales past native, so
# sips interpolation softens the crisp pixels — acceptable for v0; revisit with
# a native 1024 export (or nearest-neighbour scaling) if the icon looks mushy.
ICONSET="$(mktemp -d)/AppIcon.iconset"
mkdir -p "$ICONSET"
# Clean up the temp iconset even if a render step fails midway.
trap 'rm -rf "$(dirname -- "$ICONSET")"' EXIT

mkdir -p "$(dirname -- "$OUT")"

# Each entry: "<pixel-size> <iconset-filename>". Retina (@2x) files are just the
# double-resolution render under the logical-size name Apple expects.
render() {
  local px="$1" name="$2"
  # -z is height then width; square art so both equal px. -s format png keeps
  # everything PNG regardless of the source's stored format.
  sips -z "$px" "$px" "$SRC" --out "$ICONSET/$name" >/dev/null
}

render 16   icon_16x16.png
render 32   icon_16x16@2x.png
render 32   icon_32x32.png
render 64   icon_32x32@2x.png
render 128  icon_128x128.png
render 256  icon_128x128@2x.png
render 256  icon_256x256.png
render 512  icon_256x256@2x.png
render 512  icon_512x512.png
render 1024 icon_512x512@2x.png

# iconutil packs the .iconset into a multi-resolution .icns.
iconutil -c icns "$ICONSET" -o "$OUT"

echo "$OUT"
