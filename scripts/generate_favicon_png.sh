#!/bin/bash
# Generate PNG favicon from SVG using ImageMagick or similar
# Requires: imagemagick (brew install imagemagick)

if ! command -v convert &> /dev/null; then
    echo "ImageMagick not found. Install with: brew install imagemagick"
    exit 1
fi

# Generate multiple sizes for browser compatibility
convert -background none webapp/static/favicon.svg -resize 16x16 webapp/static/favicon-16x16.png
convert -background none webapp/static/favicon.svg -resize 32x32 webapp/static/favicon-32x32.png
convert -background none webapp/static/favicon.svg -resize 48x48 webapp/static/favicon-48x48.png

# Generate .ico file (multi-resolution)
convert webapp/static/favicon-16x16.png webapp/static/favicon-32x32.png webapp/static/favicon-48x48.png webapp/static/favicon.ico

echo "✅ Favicon generated:"
echo "  - favicon.ico (multi-resolution)"
echo "  - favicon-16x16.png"
echo "  - favicon-32x32.png"
echo "  - favicon-48x48.png"
