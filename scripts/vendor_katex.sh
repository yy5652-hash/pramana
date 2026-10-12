#!/bin/sh
# Vendors KaTeX (MIT licence) into web/vendor/katex so the app renders maths with no network access.
set -eu
VERSION=0.16.11
BASE="https://cdn.jsdelivr.net/npm/katex@${VERSION}/dist"
DEST="$(dirname "$0")/../web/vendor/katex"
mkdir -p "$DEST/fonts"
curl -fsSL "$BASE/katex.min.js" -o "$DEST/katex.min.js"
curl -fsSL "$BASE/katex.min.css" -o "$DEST/katex.min.css"
for font in $(grep -o 'fonts/[A-Za-z0-9_-]*\.woff2' "$DEST/katex.min.css" | sort -u); do
  curl -fsSL "$BASE/$font" -o "$DEST/$font"
done
echo "KaTeX ${VERSION}: $(ls "$DEST/fonts" | wc -l | tr -d ' ') fonts"
