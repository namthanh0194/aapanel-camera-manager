#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE="${CAMERA_ENV:-/opt/camera/san.env}"
if [[ ! -r "$ENV_FILE" ]]; then
  echo "Missing env file: $ENV_FILE" >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

: "${RTSP_URL:?RTSP_URL is required}"
: "${CAMERA_ID:?CAMERA_ID is required}"

CAMERA_BASE_DIR="${CAMERA_BASE_DIR:-${CAMERA_ROOT:-/tmp/video/cameras}/$CAMERA_ID}"
CAMERA_BUFFER_DIR="${CAMERA_BUFFER_DIR:-$CAMERA_BASE_DIR/buffer}"
SEGMENT_TIME="${SEGMENT_TIME:-180}"  # Mac dinh 180s (3 phut)

mkdir -p "$CAMERA_BUFFER_DIR"

audio_args=(-c:a copy)
if [[ "${CAMERA_AUDIO_MODE:-aac}" == "aac" ]]; then
  audio_args=(-c:a aac -b:a "${CAMERA_AUDIO_BITRATE:-64k}" -ar "${CAMERA_AUDIO_RATE:-44100}")
fi

exec ffmpeg \
  -hide_banner \
  -loglevel warning \
  -rtsp_transport tcp \
  -stimeout 10000000 \
  -fflags +genpts \
  -i "$RTSP_URL" \
  -map 0:v:0 \
  -map 0:a? \
  -c:v copy \
  "${audio_args[@]}" \
  -f segment \
  -segment_time "$SEGMENT_TIME" \
  -reset_timestamps 1 \
  -strftime 1 \
  "$CAMERA_BUFFER_DIR/%Y%m%d_%H%M%S.mp4"
