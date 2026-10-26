#!/usr/bin/env bash
set -Eeuo pipefail

CAMERA_ROOT="${CAMERA_ROOT:-/tmp/video/cameras}"
LOG_HELPER="$(dirname "${BASH_SOURCE[0]}")/camera_manager_log.py"

if [[ -d "$CAMERA_ROOT" ]]; then
  # 1. Ban cac file MP4 hoan tat len Telegram va xoa ngay sau khi gui thanh cong
  if [[ -x /opt/camera/cleanup-and-archive.py ]]; then
    python3 -B /opt/camera/cleanup-and-archive.py
  fi

  # 2. Xoa cac file rac cu hoac file .ts cu con ton dong
  find "$CAMERA_ROOT" -path '*/buffer/*.ts' -type f -print0 2>/dev/null | python3 -B "$LOG_HELPER" delete "$CAMERA_ROOT" legacy_ts || true
  find "$CAMERA_ROOT" -path '*/buffer/*.mp4' -type f -mmin +30 -print0 2>/dev/null | python3 -B "$LOG_HELPER" delete "$CAMERA_ROOT" buffer_retention_30m || true
  find "$CAMERA_ROOT" -path '*/output/*.mp4' -type f -mmin +60 -print0 2>/dev/null | python3 -B "$LOG_HELPER" delete "$CAMERA_ROOT" output_retention_60m || true
  find "$CAMERA_ROOT" -path '*/work/*' -mindepth 3 -maxdepth 3 -type d -mmin +60 -print0 2>/dev/null | python3 -B "$LOG_HELPER" delete "$CAMERA_ROOT" work_retention_60m || true
fi
