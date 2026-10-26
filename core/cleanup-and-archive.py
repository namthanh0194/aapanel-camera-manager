#!/usr/bin/env python3
# coding: utf-8
import os
import sys
import glob
import time
import subprocess
import json
from datetime import datetime

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

def send_telegram_video(bot_token, chat_id, video_path, caption):
    cmd = [
        "curl", "-s", "-S",
        "--connect-timeout", "30",
        "--max-time", "180",
        "-F", f"chat_id={chat_id}",
        "-F", f"video=@{video_path}",
        "-F", f"caption={caption}",
        f"https://api.telegram.org/bot{bot_token}/sendVideo"
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        print(f"[ERROR] curl failed: {res.stderr}", file=sys.stderr)
        return False
    try:
        data = json.loads(res.stdout)
        if data.get("ok"):
            return True
        else:
            print(f"[ERROR] Telegram API error: {data.get('description')}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"[ERROR] Failed to parse Telegram response: {e}\nOutput: {res.stdout}", file=sys.stderr)
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

    print(f"[{camera_id}] Tim thay {len(ready_files)} video MP4 san sang xu ly.")

    for f in ready_files:
        try:
            fsize = os.path.getsize(f)
            if fsize == 0:
                os.remove(f)
                continue

            fname = os.path.splitext(os.path.basename(f))[0]
            try:
                t = datetime.strptime(fname, "%Y%m%d_%H%M%S").strftime("%H:%M:%S %d/%m/%Y")
                caption = f"📹 [Camera: {camera_id}]\n⏱ Thời gian: {t}"
            except Exception:
                caption = f"📹 [Camera: {camera_id}]\n⏱ Video: {fname}"

            # Neu khong co Telegram config -> chi giu lai file gan nhat hoac xoa file cu
            if not bot_token or not chat_id:
                if (now - os.path.getmtime(f)) > 600:
                    os.remove(f)
                continue

            # Kiem tra dung luong vuot nguong 48MB Telegram
            if fsize > MAX_UPLOAD_BYTES:
                print(f"[{camera_id}] File {f} vuot qua 48MB ({fsize} bytes), bo qua.", file=sys.stderr)
                os.remove(f)
                continue

            # Ban len Telegram
            print(f"[{camera_id}] Dang gui {os.path.basename(f)} ({round(fsize/1024/1024, 2)} MB) len Telegram...")
            success = send_telegram_video(bot_token, chat_id, f, caption)

            # Gui thanh cong -> XOA LUON FILE MP4
            if success:
                print(f"[{camera_id}] Gui thanh cong. Xoa file {os.path.basename(f)}")
                os.remove(f)
            else:
                print(f"[{camera_id}] Gui that bai, giu lai file de thu lai sau.", file=sys.stderr)

        except Exception as e:
            print(f"[{camera_id}] Loi xu ly file {f}: {e}", file=sys.stderr)

    # Don dep file .ts cu neu con ton dong tu he thong truoc
    old_ts_files = glob.glob(os.path.join(buffer_dir, "*.ts"))
    for ts_f in old_ts_files:
        try: os.remove(ts_f)
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
