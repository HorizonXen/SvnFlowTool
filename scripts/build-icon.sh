#!/bin/zsh
set -euo pipefail
ICON_PROJECT_DIR="${0:A:h:h}"
ICON_SOURCE="$ICON_PROJECT_DIR/Resources/Brand/SvnFlow-icon-v3.png"
ICON_SET="$ICON_PROJECT_DIR/.build/branding/AppIcon.iconset"
mkdir -p "$ICON_SET"
for ICON_SIZE in 16 32 128 256 512; do
    sips -z "$ICON_SIZE" "$ICON_SIZE" "$ICON_SOURCE" --out "$ICON_SET/icon_${ICON_SIZE}x${ICON_SIZE}.png" >/dev/null
    ICON_RETINA_SIZE=$((ICON_SIZE * 2))
    sips -z "$ICON_RETINA_SIZE" "$ICON_RETINA_SIZE" "$ICON_SOURCE" --out "$ICON_SET/icon_${ICON_SIZE}x${ICON_SIZE}@2x.png" >/dev/null
done
iconutil -c icns "$ICON_SET" -o "$ICON_PROJECT_DIR/Resources/Brand/SvnFlow-v3.icns"
