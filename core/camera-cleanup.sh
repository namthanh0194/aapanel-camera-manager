#!/usr/bin/env bash
set -Eeuo pipefail

CAMERA_ROOT="${CAMERA_ROOT:-/tmp/video/cameras}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -d "$CAMERA_ROOT" ]]; then
  if [[ -f "$SCRIPT_DIR/cleanup-and-archive.py" ]]; then
    python3 -B "$SCRIPT_DIR/cleanup-and-archive.py"
  fi
fi
