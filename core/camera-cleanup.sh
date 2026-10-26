#!/usr/bin/env bash
set -Eeuo pipefail

CAMERA_ROOT="${CAMERA_ROOT:-/tmp/video/cameras}"

if [[ -d "$CAMERA_ROOT" ]]; then
  # 1. Ban cac file MP4 hoan tat len Telegram va xoa ngay sau khi gui thanh cong
  if [[ -x /opt/camera/cleanup-and-archive.py ]]; then
    python3 /opt/camera/cleanup-and-archive.py
  fi

  # 2. Xoa cac file rac cu hoac file .ts cu con ton dong
  find "$CAMERA_ROOT" -path '*/buffer/*.ts' -type f -delete 2>/dev/null || true
  find "$CAMERA_ROOT" -path '*/buffer/*.mp4' -type f -mmin +30 -delete 2>/dev/null || true
  find "$CAMERA_ROOT" -path '*/output/*.mp4' -type f -mmin +60 -delete 2>/dev/null || true
  find "$CAMERA_ROOT" -path '*/work/*' -mindepth 3 -maxdepth 3 -type d -mmin +60 -exec rm -rf -- {} + 2>/dev/null || true
fi
