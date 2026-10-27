#!/usr/bin/env python3
# coding: utf-8
import glob
import os

from camera_manager_delivery import deliver_video, destination_ready, finish_delivery, send_telegram_video
from camera_manager_log import inspect_video, remove_logged, write_event
from camera_manager_storage import archive_lock, file_identity, video_closed

CAMERA_ROOT = os.environ.get("CAMERA_ROOT", "/tmp/video/cameras")
CONFIG_DIR = os.environ.get("CAMERA_CONFIG_DIR", "/opt/camera")


def load_env(env_path):
    config = {}
    if not os.path.exists(env_path):
        return config
    with open(env_path, "r", encoding="utf-8", errors="ignore") as source:
        for line in source:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                config[key.strip()] = value.strip().strip("\"'")
    return config


def process_camera(cam_dir):
    camera_id = os.path.basename(cam_dir)
    env_cfg = load_env(os.path.join(CONFIG_DIR, f"{camera_id}.env"))
    buffer_dir = os.path.join(cam_dir, "buffer")
    if not os.path.isdir(buffer_dir) or os.path.islink(cam_dir) or os.path.islink(buffer_dir):
        return
    bot_token = env_cfg.get("TELEGRAM_BOT_TOKEN")
    chat_id = env_cfg.get("TELEGRAM_CHAT_ID")
    for video in sorted(glob.glob(os.path.join(buffer_dir, "*.mp4"))):
        try:
            if bot_token and chat_id and not destination_ready(buffer_dir, bot_token, chat_id):
                break
            if not video_closed(video):
                continue
            if not bot_token or not chat_id:
                write_event("telegram", "warning", camera_id, "not_configured", "Chưa cấu hình Telegram; giữ nguyên MP4 đã hoàn tất", file=os.path.basename(video))
                continue
            identity = file_identity(video)
            duration = inspect_video(video, camera_id, env_cfg.get("SEGMENT_TIME", "180"))
            if duration is None or duration <= 0:
                continue
            if not video_closed(video) or file_identity(video) != identity:
                continue
            success = deliver_video(video, camera_id, bot_token, chat_id, duration, sender=send_telegram_video)
            if success and video_closed(video) and file_identity(video) == identity:
                remove_logged(video, camera_id, "telegram_success", True)
                finish_delivery(video, camera_id)
        except Exception as error:
            write_event("telegram", "error", camera_id, "processing_failed", "Lỗi xử lý video; không xóa MP4 chưa xác nhận gửi", file=os.path.basename(video), error=str(error))


def main():
    if not os.path.isdir(CAMERA_ROOT):
        return
    with archive_lock(CAMERA_ROOT) as acquired:
        if not acquired:
            write_event("plugin", "info", "", "archive_busy", "Đã có tiến trình gửi/dọn đang chạy; bỏ qua lượt trùng")
            return
        for entry in sorted(os.listdir(CAMERA_ROOT)):
            cam_dir = os.path.join(CAMERA_ROOT, entry)
            if os.path.isdir(cam_dir) and not entry.startswith("."):
                process_camera(cam_dir)


if __name__ == "__main__":
    main()
