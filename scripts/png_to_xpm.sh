#!/usr/bin/env bash
# Convert every PNG dropped into assets/ to the XPM format the game
# loads. Draw your icons as PNGs (transparent background), drop them in
# assets/, then run this script.
#
# Needs ImageMagick (`convert`): sudo apt-get install imagemagick
set -e
cd "$(dirname "$0")/../assets"
shopt -s nullglob
found=0
for png in *.png; do
    xpm="${png%.png}.xpm"
    convert "$png" "$xpm"
    echo "converted $png -> $xpm"
    found=1
done
[ "$found" = 1 ] || echo "No .png files in assets/ to convert."
