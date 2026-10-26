#!/usr/bin/env bash
set -Eeuo pipefail

CAMERA_ROOT="${CAMERA_ROOT:-/tmp/video/cameras}"

if [[ -d "$CAMERA_ROOT" ]]; then
  # 1. Ghép các file buffer cũ hơn 10 phút thành MP4, gửi Telegram, sau đó xóa file MP4 và các file TS
  if [[ -x /opt/camera/cleanup-and-archive.py ]]; then
    python3 /opt/camera/cleanup-and-archive.py
  fi

  # 2. Xóa các file rác hoặc sót lại nếu có
  find "$CAMERA_ROOT" -path '*/buffer/*.ts' -type f -mmin +20 -delete 2>/dev/null || true
  find "$CAMERA_ROOT" -path '*/output/*.mp4' -type f -mmin +60 -delete 2>/dev/null || true
  find "$CAMERA_ROOT" -path '*/work/*' -mindepth 3 -maxdepth 3 -type d -mmin +60 -exec rm -rf -- {} + 2>/dev/null || true
fi
