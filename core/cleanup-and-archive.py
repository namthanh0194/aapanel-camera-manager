#!/usr/bin/env python3
# coding: utf-8
import os
import glob
import time
import subprocess
import json
from datetime import datetime
from camera_manager_log import inspect_video, remove_logged, write_event

CAMERA_ROOT = os.environ.get("CAMERA_ROOT", "/tmp/video/cameras")
MAX_UPLOAD_BYTES = 48 * 1024 * 1024  # 48MB max for Telegram 50MB limit

def load_env(env_path):
    config = {}
    if not os.path.exists(env_path):
        return config
    with open(env_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                config[k.strip()] = v.strip().strip("\"'")
    return config

def send_telegram_video(bot_token, chat_id, video_path, caption, camera_id=""):
    cmd = [
        "curl", "-s", "-S",
        "--connect-timeout", "30",
        "--max-time", "180",
        "-F", f"chat_id={chat_id}",
        "-F", f"video=@{video_path}",
        "-F", f"caption={caption}",
        f"https://api.telegram.org/bot{bot_token}/sendVideo"
    ]
    started = time.monotonic()
    filename = os.path.basename(video_path)
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except OSError as error:
        write_event("telegram", "error", camera_id, "upload_failed", "Không chạy được lệnh gửi Telegram; giữ file để thử lại", file=filename, error=str(error))
        return False
    elapsed = round(time.monotonic() - started, 2)
    if res.returncode != 0:
        write_event("telegram", "error", camera_id, "upload_failed", "Gửi thất bại; giữ file để thử lại", file=filename, elapsed_seconds=elapsed, error=res.stderr, exit_code=res.returncode)
        return False
    try:
        data = json.loads(res.stdout)
        if data.get("ok"):
            write_event("telegram", "info", camera_id, "upload_success", "Telegram xác nhận gửi thành công", file=filename, elapsed_seconds=elapsed, message_id=data.get("result", {}).get("message_id"))
            return True
        else:
            write_event("telegram", "error", camera_id, "upload_failed", "Telegram từ chối; giữ file để thử lại", file=filename, elapsed_seconds=elapsed, error=data.get("description"), error_code=data.get("error_code"), retry_after=data.get("parameters", {}).get("retry_after"))
            return False
    except Exception as e:
        write_event("telegram", "error", camera_id, "upload_failed", "Phản hồi Telegram không hợp lệ; giữ file để thử lại", file=filename, elapsed_seconds=elapsed, error=str(e))
        return False

def process_camera(camera_dir):
    camera_id = os.path.basename(camera_dir)
    buffer_dir = os.path.join(camera_dir, "buffer")
    if not os.path.isdir(buffer_dir):
        return

    env_path = f"/opt/camera/{camera_id}.env"
    env_cfg = load_env(env_path)
    bot_token = env_cfg.get("TELEGRAM_BOT_TOKEN")
    chat_id = env_cfg.get("TELEGRAM_CHAT_ID")

    # Lay tat ca file .mp4 sap xep theo thoi gian
    mp4_files = sorted(glob.glob(os.path.join(buffer_dir, "*.mp4")))
    if not mp4_files:
        return

    # File cuoi cung thuong dang duoc ffmpeg ghi -> chi xu ly cac file da ghi xong (tu file ap chot tro ve truoc)
    # Neu chi co 1 file thi kiem tra neu da ngung ghi > 10 giay thi moi xu ly
    now = time.time()
    ready_files = []
    
    if len(mp4_files) > 1:
        ready_files = mp4_files[:-1]
    else:
        # Chi co 1 file duy nhat (vi du khi camera dung quay)
        single_f = mp4_files[0]
        if (now - os.path.getmtime(single_f)) > 15:
            ready_files = [single_f]

    if not ready_files:
        return

    for f in ready_files:
        try:
            fsize = os.path.getsize(f)
            if fsize == 0:
                remove_logged(f, camera_id, "empty_file")
                continue

            duration = inspect_video(f, camera_id, env_cfg.get("SEGMENT_TIME", "180"))

            fname = os.path.splitext(os.path.basename(f))[0]
            try:
                t = datetime.strptime(fname, "%Y%m%d_%H%M%S").strftime("%H:%M:%S %d/%m/%Y")
                caption = f"📹 [Camera: {camera_id}]\n⏱ Thời gian: {t}"
            except Exception:
                caption = f"📹 [Camera: {camera_id}]\n⏱ Video: {fname}"

            # Neu khong co Telegram config -> chi giu lai file gan nhat hoac xoa file cu
            if not bot_token or not chat_id:
                if (now - os.path.getmtime(f)) > 600:
                    remove_logged(f, camera_id, "no_telegram_config_10m", False)
                else:
                    write_event("telegram", "warning", camera_id, "not_configured", "Chưa cấu hình Telegram; hiện giữ file, chính sách cũ xóa sau 10 phút", file=os.path.basename(f))
                continue

            # Kiem tra dung luong vuot nguong 48MB Telegram
            if fsize > MAX_UPLOAD_BYTES:
                write_event("telegram", "error", camera_id, "upload_oversize", "Không gửi được: video vượt ngưỡng 48 MiB; xóa theo chính sách hiện tại", file=os.path.basename(f), bytes=fsize)
                remove_logged(f, camera_id, "upload_oversize", False)
                continue

            # Ban len Telegram
            write_event("telegram", "info", camera_id, "upload_started", "Bắt đầu gửi video lên Telegram", file=os.path.basename(f), bytes=fsize, duration_seconds=duration)
            success = send_telegram_video(bot_token, chat_id, f, caption, camera_id)

            # Gui thanh cong -> XOA LUON FILE MP4
            if success:
                remove_logged(f, camera_id, "telegram_success", True)

        except Exception as e:
            write_event("telegram", "error", camera_id, "processing_failed", "Lỗi xử lý video", file=os.path.basename(f), error=str(e))

    # Don dep file .ts cu neu con ton dong tu he thong truoc
    old_ts_files = glob.glob(os.path.join(buffer_dir, "*.ts"))
    for ts_f in old_ts_files:
        try: remove_logged(ts_f, camera_id, "legacy_ts")
        except OSError: pass

def main():
    if not os.path.isdir(CAMERA_ROOT):
        return
    for entry in os.listdir(CAMERA_ROOT):
        cam_dir = os.path.join(CAMERA_ROOT, entry)
        if os.path.isdir(cam_dir):
            process_camera(cam_dir)

if __name__ == "__main__":
    main()
