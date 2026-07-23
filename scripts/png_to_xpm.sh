#!/usr/bin/env bash
# Convert every PNG dropped into assets/sprites/ to the XPM format the
# game loads. Draw/find your icons as PNGs (transparent background),
# drop them in assets/sprites/, then run this script.
#
# Needs ImageMagick (`convert`): sudo apt-get install imagemagick
set -e
cd "$(dirname "$0")/../assets/sprites"
shopt -s nullglob
found=0
for png in *.png; do
    xpm="${png%.png}.xpm"
    convert "$png" "$xpm"
    echo "converted $png -> $xpm"
    found=1
done
[ "$found" = 1 ] || echo "No .png files in assets/sprites/ to convert."
