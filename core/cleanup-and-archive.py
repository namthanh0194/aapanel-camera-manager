#!/usr/bin/env python3
import os
import sys
import glob
import time
import subprocess
import json
import urllib.request
import urllib.error
from datetime import datetime

CAMERA_ROOT = os.environ.get("CAMERA_ROOT", "/tmp/video/cameras")
MAX_BATCH_BYTES = 40 * 1024 * 1024  # 40MB max per batch for Telegram 50MB limit
MIN_AGE_MINUTES = 10  # Files older than 10 minutes

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

    # Find .ts files older than MIN_AGE_MINUTES
    now = time.time()
    ts_files = sorted(glob.glob(os.path.join(buffer_dir, "*.ts")))
    expired_files = []
    for f in ts_files:
        try:
            mtime = os.path.getmtime(f)
            size = os.path.getsize(f)
            if (now - mtime) >= (MIN_AGE_MINUTES * 60) and size > 0:
                expired_files.append(f)
        except OSError:
            pass

    if not expired_files:
        return

    print(f"[{camera_id}] Found {len(expired_files)} expired .ts files.")

    # If no telegram credentials, just delete them
    if not bot_token or not chat_id:
        print(f"[{camera_id}] No Telegram config found, deleting expired files directly.")
        for f in expired_files:
            try:
                os.remove(f)
            except OSError:
                pass
        return

    # Group into batches (< MAX_BATCH_BYTES)
    batches = []
    current_batch = []
    current_size = 0

    for f in expired_files:
        fsize = os.path.getsize(f)
        if current_size + fsize > MAX_BATCH_BYTES and current_batch:
            batches.append(current_batch)
            current_batch = [f]
            current_size = fsize
        else:
            current_batch.append(f)
            current_size += fsize

    if current_batch:
        batches.append(current_batch)

    # Process each batch
    for b_idx, batch in enumerate(batches):
        start_name = os.path.splitext(os.path.basename(batch[0]))[0]
        end_name = os.path.splitext(os.path.basename(batch[-1]))[0]

        temp_ts = os.path.join(camera_dir, f"concat_{b_idx}_{start_name}.ts")
        temp_mp4 = os.path.join(camera_dir, f"archive_{start_name}_{end_name}.mp4")

        try:
            # 1. Concat binary TS
            with open(temp_ts, "wb") as out_ts:
                for bf in batch:
                    with open(bf, "rb") as in_ts:
                        out_ts.write(in_ts.read())

            # 2. Remux to MP4
            cmd_remux = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", temp_ts,
                "-c", "copy",
                "-movflags", "+faststart",
                temp_mp4
            ]
            remux_res = subprocess.run(cmd_remux)
            if remux_res.returncode != 0:
                print(f"[{camera_id}] Remux failed for batch {b_idx}", file=sys.stderr)
                continue

            # Format caption time
            try:
                t1 = datetime.strptime(start_name, "%Y%m%d_%H%M%S").strftime("%H:%M:%S %d/%m/%Y")
                t2 = datetime.strptime(end_name, "%Y%m%d_%H%M%S").strftime("%H:%M:%S %d/%m/%Y")
                caption = f"📹 [Camera: {camera_id}]\n⏱ Video lưu trữ: {t1} - {t2}"
            except Exception:
                caption = f"📹 [Camera: {camera_id}]\n⏱ {start_name} -> {end_name}"

            # 3. Send to Telegram
            print(f"[{camera_id}] Sending batch {b_idx+1}/{len(batches)} ({os.path.getsize(temp_mp4)} bytes) to Telegram...")
            success = send_telegram_video(bot_token, chat_id, temp_mp4, caption)

            # 4. Remove temporary merged MP4 and TS
            if os.path.exists(temp_mp4):
                os.remove(temp_mp4)
            if os.path.exists(temp_ts):
                os.remove(temp_ts)

            # 5. Delete source TS files only if sent successfully
            if success:
                print(f"[{camera_id}] Successfully sent batch {b_idx+1}. Deleting {len(batch)} source .ts files.")
                for bf in batch:
                    try:
                        os.remove(bf)
                    except OSError:
                        pass
            else:
                print(f"[{camera_id}] Telegram send failed for batch {b_idx+1}, keeping source .ts files.")

        except Exception as e:
            print(f"[{camera_id}] Error processing batch {b_idx}: {e}", file=sys.stderr)
            if os.path.exists(temp_mp4):
                try: os.remove(temp_mp4)
                except OSError: pass
            if os.path.exists(temp_ts):
                try: os.remove(temp_ts)
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
