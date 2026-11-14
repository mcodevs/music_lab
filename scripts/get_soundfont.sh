#!/bin/sh
# Download the FluidR3_GM General MIDI SoundFont into soundfonts/ (not stored in git: 148 MB > GitHub's 100 MB limit).
#
# Source: official Debian package fluid-soundfont-gm 3.1-6 (MIT licence), ~120 MB download.
# The .sf2 is extracted from the .deb with macOS's built-in bsdtar and checked by SHA-256.
#
# usage: sh scripts/get_soundfont.sh            # download if missing or damaged
#        sh scripts/get_soundfont.sh --force    # download again even if the file is fine
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
DEST="$ROOT/soundfonts/FluidR3_GM.sf2"
URL="https://deb.debian.org/debian/pool/main/f/fluid-soundfont/fluid-soundfont-gm_3.1-6_all.deb"
SHA256="74594e8f4250680adf590507a306655a299935343583256f3b722c48a1bc1cb0"
SF2_IN_DEB="./usr/share/sounds/sf2/FluidR3_GM.sf2"

sha_of() { shasum -a 256 "$1" | cut -d' ' -f1; }

if [ "${1:-}" != "--force" ] && [ -f "$DEST" ]; then
    if [ "$(sha_of "$DEST")" = "$SHA256" ]; then
        echo "OK: $DEST already present (checksum matches), nothing to do."
        exit 0
    fi
    echo "warning: $DEST exists but its checksum does not match; downloading a fresh copy."
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM

echo "downloading $URL (~120 MB)..."
curl -fL --retry 3 --retry-delay 5 -C - -o "$TMP/pkg.deb" "$URL"

# A .deb is an ar archive holding data.tar.{xz,zst,gz}; bsdtar (macOS tar) reads both layers.
DATA=$(tar -tf "$TMP/pkg.deb" | grep '^data\.tar' | head -n 1)
[ -n "$DATA" ] || { echo "error: no data.tar inside the package" >&2; exit 1; }
tar -xOf "$TMP/pkg.deb" "$DATA" > "$TMP/$DATA"
tar -xOf "$TMP/$DATA" "$SF2_IN_DEB" > "$TMP/FluidR3_GM.sf2"

GOT=$(sha_of "$TMP/FluidR3_GM.sf2")
if [ "$GOT" != "$SHA256" ]; then
    echo "error: checksum mismatch (got $GOT, expected $SHA256); file not installed." >&2
    exit 1
fi

mkdir -p "$ROOT/soundfonts"
mv "$TMP/FluidR3_GM.sf2" "$DEST"
echo "installed $DEST ($(du -h "$DEST" | cut -f1)), checksum OK."
