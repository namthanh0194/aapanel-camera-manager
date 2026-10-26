#!/usr/bin/env python3
# coding: utf-8
import os
import sys
import glob
import json
import time
import subprocess
import re

# Thêm panel path
panelPath = "/www/server/panel"
os.chdir(panelPath)
sys.path.insert(0, panelPath + "/class")
import public

CONFIG_DIR = "/opt/camera"
CAMERA_ROOT = "/tmp/video/cameras"

class camera_manager_main:
    def __init__(self):
        self.__setup_directories()

    def __setup_directories(self):
        if not os.path.exists(CONFIG_DIR):
            os.makedirs(CONFIG_DIR, exist_ok=True)
            public.ExecShell(f"chown -R root:www '{CONFIG_DIR}' && chmod -R 750 '{CONFIG_DIR}'")
        if not os.path.exists(CAMERA_ROOT):
            os.makedirs(CAMERA_ROOT, exist_ok=True)
            public.ExecShell(f"chown -R www:www '{CAMERA_ROOT}' && chmod -R 775 '{CAMERA_ROOT}'")

    def _get_service_status(self, camera_id):
        svc = f"camera-buffer@{camera_id}.service"
        try:
            active_out = public.ExecShell(f"systemctl is-active '{svc}'")[0].strip()
            enabled_out = public.ExecShell(f"systemctl is-enabled '{svc}'")[0].strip()
            return {"status": active_out, "enabled": (enabled_out == "enabled")}
        except Exception as e:
            return {"status": "unknown", "enabled": False, "error": str(e)}

    def _load_camera_env(self, env_path):
        cfg = {}
        if not os.path.exists(env_path):
            return cfg
        with open(env_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip().strip("\"'")
        return cfg

    # 1. API: Danh sách camera
    def get_camera_list(self, get):
        cameras = []
        files = sorted(glob.glob(os.path.join(CONFIG_DIR, "*.env")))
        for f in files:
            fname = os.path.basename(f)
            if fname.startswith("camera.env.example") or ".bak" in fname:
                continue
            cam_id = fname[:-4]
            cfg = self._load_camera_env(f)
            status_info = self._get_service_status(cam_id)

            buf_dir = os.path.join(CAMERA_ROOT, cam_id, "buffer")
            ts_count = len(glob.glob(os.path.join(buf_dir, "*.ts"))) if os.path.isdir(buf_dir) else 0

            cameras.append({
                "id": cam_id,
                "rtsp_url": cfg.get("RTSP_URL", ""),
                "audio_mode": cfg.get("CAMERA_AUDIO_MODE", "aac"),
                "audio_bitrate": cfg.get("CAMERA_AUDIO_BITRATE", "64k"),
                "audio_rate": cfg.get("CAMERA_AUDIO_RATE", "44100"),
                "pre_seconds": cfg.get("PRE_SECONDS", "15"),
                "post_seconds": cfg.get("POST_SECONDS", "45"),
                "target_seconds": cfg.get("TARGET_SECONDS", "60"),
                "telegram_bot_token": cfg.get("TELEGRAM_BOT_TOKEN", ""),
                "telegram_chat_id": cfg.get("TELEGRAM_CHAT_ID", ""),
                "status": status_info.get("status", "unknown"),
                "enabled": status_info.get("enabled", False),
                "buffer_count": ts_count
            })
        return json.dumps(cameras, ensure_ascii=False)

    # 2. API: Lưu hoặc chỉnh sửa camera
    def save_camera(self, get):
        cam_id = getattr(get, "id", "").strip().lower()
        if not cam_id or not re.match(r"^[a-z0-9_]+$", cam_id):
            return public.returnMsg(False, "Mã camera không hợp lệ (chỉ gồm chữ thường không dấu, số và dấu gạch dưới)")

        rtsp_url = getattr(get, "rtsp_url", "").strip()
        if not rtsp_url:
            return public.returnMsg(False, "RTSP URL không được để trống")

        env_path = os.path.join(CONFIG_DIR, f"{cam_id}.env")
        lines = [
            f"CAMERA_ID={cam_id}",
            f"RTSP_URL={rtsp_url}",
            f"CAMERA_BASE_DIR={CAMERA_ROOT}/{cam_id}",
            f"TARGET_SECONDS={getattr(get, 'target_seconds', '60')}",
            f"PRE_SECONDS={getattr(get, 'pre_seconds', '15')}",
            f"POST_SECONDS={getattr(get, 'post_seconds', '45')}",
            f"CAMERA_AUDIO_MODE={getattr(get, 'audio_mode', 'aac')}",
            f"CAMERA_AUDIO_BITRATE={getattr(get, 'audio_bitrate', '64k')}",
            f"CAMERA_AUDIO_RATE={getattr(get, 'audio_rate', '44100')}",
        ]
        bot_token = getattr(get, "telegram_bot_token", "").strip()
        chat_id = getattr(get, "telegram_chat_id", "").strip()
        if bot_token:
            lines.append(f"TELEGRAM_BOT_TOKEN={bot_token}")
        if chat_id:
            lines.append(f"TELEGRAM_CHAT_ID={chat_id}")

        with open(env_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        public.ExecShell(f"chown root:www '{env_path}' && chmod 640 '{env_path}'")

        # Tạo thư mục con
        for sub in ["buffer", "output", "work"]:
            d = os.path.join(CAMERA_ROOT, cam_id, sub)
            os.makedirs(d, exist_ok=True)
        public.ExecShell(f"chown -R www:www '{CAMERA_ROOT}/{cam_id}' && chmod -R 775 '{CAMERA_ROOT}/{cam_id}'")

        # Tự động reload service nếu service đang chạy
        svc = f"camera-buffer@{cam_id}.service"
        active_check = public.ExecShell(f"systemctl is-active '{svc}'")[0].strip()
        if active_check == "active":
            public.ExecShell(f"systemctl restart '{svc}'")

        return public.returnMsg(True, "Lưu cấu hình camera thành công")

    # 3. API: Xóa camera
    def delete_camera(self, get):
        cam_id = getattr(get, "id", "").strip()
        if not cam_id:
            return public.returnMsg(False, "Chưa chọn camera để xóa")

        svc = f"camera-buffer@{cam_id}.service"
        public.ExecShell(f"systemctl stop '{svc}'")
        public.ExecShell(f"systemctl disable '{svc}'")

        env_file = os.path.join(CONFIG_DIR, f"{cam_id}.env")
        if os.path.exists(env_file):
            os.remove(env_file)

        return public.returnMsg(True, f"Đã xóa camera {cam_id}")

    # 4. API: Điều khiển dịch vụ camera (start, stop, restart)
    def control_service(self, get):
        cam_id = getattr(get, "id", "").strip()
        action = getattr(get, "act", "").strip()
        if not cam_id or action not in ["start", "stop", "restart"]:
            return public.returnMsg(False, "Tham số điều khiển không hợp lệ")

        svc = f"camera-buffer@{cam_id}.service"
        if action == "start":
            public.ExecShell(f"systemctl enable --now '{svc}'")
        elif action == "stop":
            public.ExecShell(f"systemctl stop '{svc}'")
            public.ExecShell(f"systemctl disable '{svc}'")
        elif action == "restart":
            public.ExecShell(f"systemctl restart '{svc}'")

        status_info = self._get_service_status(cam_id)
        return json.dumps({"status": True, "msg": f"Đã thực hiện {action} camera {cam_id}", "info": status_info}, ensure_ascii=False)

    # 5. API: Kiểm tra kết nối RTSP (Test stream)
    def test_rtsp(self, get):
        rtsp_url = getattr(get, "rtsp_url", "").strip()
        if not rtsp_url:
            return json.dumps({"ok": False, "error": "Chưa nhập RTSP URL"}, ensure_ascii=False)

        cmd = [
            "ffprobe", "-v", "error",
            "-rtsp_transport", "tcp",
            "-stimeout", "4000000",
            "-i", rtsp_url,
            "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate",
            "-of", "json"
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=6)
            if res.returncode == 0:
                data = json.loads(res.stdout)
                return json.dumps({"ok": True, "info": data}, ensure_ascii=False)
            else:
                return json.dumps({"ok": False, "error": res.stderr.strip() or "Không thể kết nối luồng RTSP"}, ensure_ascii=False)
        except subprocess.TimeoutExpired:
            return json.dumps({"ok": False, "error": "Timeout kết nối (quá 6s)"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    # 6. API: Kiểm tra và cập nhật từ GitHub
    def check_update(self, get):
        plugin_info_path = "/www/server/panel/plugin/camera_manager/info.json"
        current_version = "1.0.1"
        if os.path.exists(plugin_info_path):
            try:
                current_version = json.loads(public.ReadFile(plugin_info_path)).get("versions", "1.0.0")
            except Exception:
                pass

        return json.dumps({
            "current_version": current_version,
            "has_update": False,
            "latest_version": current_version,
            "msg": f"Đang sử dụng phiên bản mới nhất v{current_version}"
        }, ensure_ascii=False)
