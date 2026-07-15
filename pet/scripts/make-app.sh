#!/usr/bin/env bash
# make-app.sh — assemble Vidura.app around the release ViduraPet binary.
#
# SwiftPM cannot emit a .app, so we build the bare executable and hand-assemble
# the bundle: binary + resource bundle (the character PNGs) + icon + Info.plist.
# Idempotent (blows away the old dist app first) and runnable from any cwd.
#
# Usage: make-app.sh [VERSION]   (VERSION defaults to "dev")
set -euo pipefail

VERSION="${1:-dev}"

# Resolve our own dir so paths hold regardless of caller cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PET="$(cd "$SCRIPT_DIR/.." && pwd)"           # .../vidura/pet
ROOT="$(cd "$PET/.." && pwd)"                 # .../vidura

BUILD="$PET/.build/release"
PACKAGING="$PET/packaging"
ICNS="$PACKAGING/AppIcon.icns"
APP="$PET/dist/Vidura.app"

# 1. Build the release binary + its SwiftPM resource bundle.
swift build -c release --package-path "$PET"

# 2. Ensure the app icon exists; make-icns.sh (sibling) generates it if not.
if [[ ! -f "$ICNS" ]]; then
	"$SCRIPT_DIR/make-icns.sh"
fi

# 3. Assemble fresh — rm -rf keeps re-runs from inheriting stale files.
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# Executable (chmod +x defensively; copy can drop the bit on some filesystems).
cp "$BUILD/ViduraPet" "$APP/Contents/MacOS/ViduraPet"
chmod +x "$APP/Contents/MacOS/ViduraPet"

# The resource bundle carries the character art loaded via Bundle.module.
# Without it the pet renders blank, so fail loudly rather than ship broken.
BUNDLE="$BUILD/ViduraPet_ViduraPetKit.bundle"
if [[ ! -d "$BUNDLE" ]]; then
	echo "error: missing resource bundle $BUNDLE (character art won't load)" >&2
	echo "       run 'swift build -c release' first, or check the target's resources." >&2
	exit 1
fi
cp -R "$BUNDLE" "$APP/Contents/Resources/"

# Icon.
cp "$ICNS" "$APP/Contents/Resources/AppIcon.icns"

# Info.plist from the committed template, with the version baked in.
# '#' delimiter avoids clashing with any '/' in a version string.
sed "s#__VERSION__#$VERSION#g" "$PACKAGING/Info.plist" > "$APP/Contents/Info.plist"

# 4. Report the assembled bundle.
echo "$APP"
