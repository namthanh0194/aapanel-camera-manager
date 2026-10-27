#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="$SCRIPT_DIR/dist"
mkdir -p "$DIST_DIR"

ZIP_NAME="camera_manager.zip"
echo "Dang dong goi plugin sang $DIST_DIR/$ZIP_NAME..."

cd "$SCRIPT_DIR"
rm -f "$DIST_DIR/$ZIP_NAME"
zip -r "$DIST_DIR/$ZIP_NAME" \
    info.json \
    DELIVERY.md \
    camera_manager_main.py \
    index.html \
    install.sh \
    upgrade.sh \
    icon.png \
    ui/ \
    core/ \
    -x "*.git*" "*__pycache__*" "*.DS_Store*"

echo "Dong goi thanh cong: $DIST_DIR/$ZIP_NAME ($(du -h "$DIST_DIR/$ZIP_NAME" | cut -f1))"
