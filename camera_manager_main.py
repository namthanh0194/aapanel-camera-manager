#!/usr/bin/env python3
# coding: utf-8
import os
import sys
import glob
import json
import time
import subprocess
import re
import shutil

panelPath = "/www/server/panel"
os.chdir(panelPath)
sys.path.insert(0, panelPath + "/class")
import public

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "core"))
from camera_manager_log import read_events, remove_logged, write_event
from camera_manager_delivery import finish_delivery
from camera_manager_storage import archive_lock, file_in_use, video_closed

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
            mp4_count = len(glob.glob(os.path.join(buf_dir, "*.mp4"))) if os.path.isdir(buf_dir) else 0

            cameras.append({
                "id": cam_id,
                "rtsp_url": cfg.get("RTSP_URL", ""),
                "audio_mode": cfg.get("CAMERA_AUDIO_MODE", "aac"),
                "audio_bitrate": cfg.get("CAMERA_AUDIO_BITRATE", "64k"),
                "audio_rate": cfg.get("CAMERA_AUDIO_RATE", "44100"),
                "segment_time": cfg.get("SEGMENT_TIME", "180"),
                "telegram_bot_token": cfg.get("TELEGRAM_BOT_TOKEN", ""),
                "telegram_chat_id": cfg.get("TELEGRAM_CHAT_ID", ""),
                "status": status_info.get("status", "unknown"),
                "enabled": status_info.get("enabled", False),
                "buffer_count": mp4_count
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

        segment_time = getattr(get, "segment_time", "180").strip() or "180"

        env_path = os.path.join(CONFIG_DIR, f"{cam_id}.env")
        previous = self._load_camera_env(env_path)
        lines = [
            f"CAMERA_ID={cam_id}",
            f"RTSP_URL={rtsp_url}",
            f"CAMERA_BASE_DIR={CAMERA_ROOT}/{cam_id}",
            f"SEGMENT_TIME={segment_time}",
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

        # Tạo thư mục con buffer
        buf_d = os.path.join(CAMERA_ROOT, cam_id, "buffer")
        os.makedirs(buf_d, exist_ok=True)
        public.ExecShell(f"chown -R www:www '{CAMERA_ROOT}/{cam_id}' && chmod -R 775 '{CAMERA_ROOT}/{cam_id}'")

        # Reload service nếu service đang chạy
        svc = f"camera-buffer@{cam_id}.service"
        active_check = public.ExecShell(f"systemctl is-active '{svc}'")[0].strip()
        if active_check == "active":
            public.ExecShell(f"systemctl restart '{svc}'")

        changed = [line.split("=", 1)[0] for line in lines if previous.get(line.split("=", 1)[0]) != line.split("=", 1)[1]]
        for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            if key in previous and not any(line.startswith(key + "=") for line in lines):
                changed.append(key)
        write_event("plugin", "info", cam_id, "camera_saved", "Đã cập nhật cấu hình camera" if previous else "Đã thêm camera", changed_fields=changed, restarted=active_check == "active")
        return public.returnMsg(True, "Lưu cấu hình camera thành công")

    # 3. API: Xóa camera
    def delete_camera(self, get):
        cam_id = getattr(get, "id", "").strip()
        if not re.fullmatch(r"[a-z0-9_]+", cam_id):
            return public.returnMsg(False, "Chưa chọn camera để xóa")

        svc = f"camera-buffer@{cam_id}.service"
        public.ExecShell(f"systemctl stop '{svc}'")
        public.ExecShell(f"systemctl disable '{svc}'")

        env_file = os.path.join(CONFIG_DIR, f"{cam_id}.env")
        if os.path.exists(env_file):
            os.remove(env_file)

        write_event("plugin", "info", cam_id, "camera_deleted", "Đã xóa cấu hình camera; video không bị xóa bởi thao tác này")
        return public.returnMsg(True, f"Đã xóa camera {cam_id}")

    # 4. API: Điều khiển dịch vụ camera (start, stop, restart)
    def control_service(self, get):
        cam_id = getattr(get, "id", "").strip()
        action = getattr(get, "act", "").strip()
        if not re.fullmatch(r"[a-z0-9_]+", cam_id) or action not in ["start", "stop", "restart"]:
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
        expected_status = "inactive" if action == "stop" else "active"
        write_event("plugin", "info" if status_info.get("status") == expected_status else "error", cam_id,
                    "service_control", "Thao tác dịch vụ camera", action=action, result=status_info.get("status"))
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

    # 6. API: Kích hoạt gửi Telegram thủ công ngay lập tức
    def trigger_archive(self, get):
        try:
            cmd = ["python3", "-B", "/opt/camera/cleanup-and-archive.py"]
            subprocess.Popen(cmd)
            write_event("plugin", "info", "", "archive_requested", "Người dùng kích hoạt quét và gửi Telegram")
            return public.returnMsg(True, "Đã kích hoạt quét và gửi video lên Telegram")
        except Exception as e:
            write_event("plugin", "error", "", "archive_failed", "Không kích hoạt được gửi Telegram", error=str(e))
            return public.returnMsg(False, f"Lỗi: {e}")

    def get_logs(self, get):
        try:
            return json.dumps(read_events(
                camera=str(getattr(get, "camera", "all")), category=str(getattr(get, "category", "all")),
                level=str(getattr(get, "level", "all")), since=getattr(get, "since", 0),
                until=getattr(get, "until", 0), limit=getattr(get, "limit", 200)
            ), ensure_ascii=False)
        except (ValueError, TypeError, OSError) as error:
            return json.dumps({"status": False, "msg": str(error), "entries": []}, ensure_ascii=False)

    def get_log_ui(self, get):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "logs.html")
        with open(path, "r", encoding="utf-8") as source:
            return json.dumps({"status": True, "html": source.read()}, ensure_ascii=False)

    # 7. API: Quét kiểm tra trạng thái lưu trữ & rác
    def get_storage_status(self, get):
        result = {
            "disk": {},
            "cameras": [],
            "total_size_mb": 0.0,
            "total_files": 0,
            "total_trash_files": 0
        }
        
        # Thống kê phân vùng /tmp
        try:
            disk_stat = shutil.disk_usage(CAMERA_ROOT if os.path.exists(CAMERA_ROOT) else "/tmp")
            result["disk"] = {
                "total_gb": round(disk_stat.total / (1024**3), 2),
                "used_gb": round(disk_stat.used / (1024**3), 2),
                "free_gb": round(disk_stat.free / (1024**3), 2),
                "used_percent": round((disk_stat.used / disk_stat.total) * 100, 1)
            }
        except Exception:
            result["disk"] = {"total_gb": 0, "used_gb": 0, "free_gb": 0, "used_percent": 0}

        if not os.path.exists(CAMERA_ROOT):
            return json.dumps(result, ensure_ascii=False)

        all_cam_dirs = sorted([d for d in os.listdir(CAMERA_ROOT) if os.path.isdir(os.path.join(CAMERA_ROOT, d))])
        for cam_id in all_cam_dirs:
            cam_path = os.path.join(CAMERA_ROOT, cam_id)
            buf_path = os.path.join(cam_path, "buffer")
            cam_size = 0
            file_count = 0
            trash_count = 0
            mp4_count = 0

            # Quét toàn bộ thư mục của camera
            for root, dirs, files in os.walk(cam_path):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        sz = os.path.getsize(fp)
                        cam_size += sz
                        file_count += 1
                        # File rác: file đuôi .ts cũ, file 0 byte, file tạm trong work/output cũ
                        if f.endswith(".ts") or sz == 0 or "work" in root or "output" in root:
                            trash_count += 1
                        elif f.endswith(".mp4"):
                            mp4_count += 1
                    except OSError:
                        pass

            cam_size_mb = round(cam_size / (1024 * 1024), 2)
            result["total_size_mb"] += cam_size_mb
            result["total_files"] += file_count
            result["total_trash_files"] += trash_count

            result["cameras"].append({
                "id": cam_id,
                "size_mb": cam_size_mb,
                "file_count": file_count,
                "mp4_count": mp4_count,
                "trash_count": trash_count
            })

        result["total_size_mb"] = round(result["total_size_mb"], 2)
        return json.dumps(result, ensure_ascii=False)

    # 8. API: Dọn dẹp rác / xóa bộ đệm lưu trữ
    def clean_storage(self, get):
        with archive_lock(CAMERA_ROOT) as acquired:
            if not acquired:
                return json.dumps({"status": False, "msg": "Đang gửi/dọn video; vui lòng thử lại sau"}, ensure_ascii=False)
            return self._clean_storage_locked(get)

    def _clean_storage_locked(self, get):
        cam_id = getattr(get, "id", "all").strip()
        mode = getattr(get, "mode", "trash_only").strip() # trash_only hoặc all_buffer
        if (cam_id != "all" and not re.fullmatch(r"[a-z0-9_]+", cam_id)) or mode not in ("trash_only", "all_buffer"):
            return json.dumps({"status": False, "msg": "Tham số dọn lưu trữ không hợp lệ"}, ensure_ascii=False)
        write_event("plugin", "warning", "" if cam_id == "all" else cam_id, "storage_cleanup_requested", "Người dùng yêu cầu dọn lưu trữ", mode=mode)
        
        deleted_count = 0
        freed_bytes = 0

        target_cams = []
        if cam_id == "all" or not cam_id:
            if os.path.exists(CAMERA_ROOT):
                target_cams = [d for d in os.listdir(CAMERA_ROOT) if os.path.isdir(os.path.join(CAMERA_ROOT, d))]
        else:
            p = os.path.join(CAMERA_ROOT, cam_id)
            if os.path.isdir(p):
                target_cams = [cam_id]

        for cid in target_cams:
            cam_dir = os.path.join(CAMERA_ROOT, cid)
            buf_dir = os.path.join(cam_dir, "buffer")

            # 1. Xóa các thư mục thừa nếu có (work, output)
            for sub in ["work", "output"]:
                sub_p = os.path.join(cam_dir, sub)
                if os.path.exists(sub_p):
                    try:
                        for root, dirs, files in os.walk(sub_p, topdown=False):
                            for f in files:
                                fp = os.path.join(root, f)
                                if file_in_use(fp):
                                    continue
                                freed_bytes += remove_logged(fp, cid, "manual_legacy_cleanup")
                                deleted_count += 1
                            for d in dirs: os.rmdir(os.path.join(root, d))
                        os.rmdir(sub_p)
                    except Exception as error:
                        write_event("storage", "error", cid, "delete_failed", "Không dọn được thư mục cũ", file=sub_p, error=str(error))

            if not os.path.isdir(buf_dir):
                continue

            # 2. Xóa các file .ts rác hoặc file 0 bytes
            for f in os.listdir(buf_dir):
                fp = os.path.join(buf_dir, f)
                if not os.path.isfile(fp): continue
                try:
                    sz = os.path.getsize(fp)
                    if (f.endswith(".ts") or sz == 0) and video_closed(fp):
                        freed_bytes += remove_logged(fp, cid, "manual_trash_cleanup")
                        deleted_count += 1
                except OSError as error:
                    write_event("storage", "error", cid, "delete_failed", "Không xóa được file rác", file=fp, error=str(error))

            # 3. Nếu chọn dọn sạch toàn bộ buffer (all_buffer):
            # Xóa các file mp4 đã quay xong (giữ lại file mp4 mới nhất đang được ffmpeg mở ghi)
            if mode == "all_buffer":
                mp4_files = sorted(glob.glob(os.path.join(buf_dir, "*.mp4")))
                for old_mp4 in mp4_files:
                    try:
                        if not video_closed(old_mp4):
                            continue
                        freed_bytes += remove_logged(old_mp4, cid, "manual_buffer_cleanup", False)
                        deleted_count += 1
                        finish_delivery(old_mp4, cid)
                    except OSError as error:
                        write_event("storage", "error", cid, "delete_failed", "Không xóa được video", file=old_mp4, error=str(error))

        freed_mb = round(freed_bytes / (1024 * 1024), 2)
        write_event("storage", "info", "" if cam_id == "all" else cam_id, "cleanup_completed", "Hoàn tất dọn lưu trữ thủ công", deleted_count=deleted_count, freed_bytes=freed_bytes, mode=mode)
        return json.dumps({
            "status": True,
            "msg": f"Đã dọn dẹp {deleted_count} file, giải phóng {freed_mb} MB dung lượng!"
        }, ensure_ascii=False)

    # 9. API: Kiểm tra phiên bản và cập nhật từ GitHub
    @staticmethod
    def _parse_version(v_str):
        clean = re.sub(r'[^0-9.]', '', str(v_str)).strip('.')
        parts = []
        for p in clean.split('.'):
            try:
                parts.append(int(p))
            except ValueError:
                parts.append(0)
        return tuple(parts)

    def check_update(self, get):
        plugin_info_path = "/www/server/panel/plugin/camera_manager/info.json"
        current_version = "1.0.0"
        if os.path.exists(plugin_info_path):
            try:
                current_version = json.loads(public.ReadFile(plugin_info_path)).get("versions", "1.0.0")
            except Exception:
                pass

        latest_version = current_version
        has_update = False
        update_url = "https://raw.githubusercontent.com/namthanh0194/aapanel-camera-manager/main/info.json"
        try:
            import urllib.request
            req = urllib.request.Request(
                update_url,
                headers={
                    "User-Agent": "aaPanel-Camera-Manager",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache"
                }
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                remote_info = json.loads(resp.read().decode('utf-8'))
                latest_version = remote_info.get("versions", current_version)
                if self._parse_version(latest_version) > self._parse_version(current_version):
                    has_update = True
        except Exception as error:
            return json.dumps({
                "status": False,
                "current_version": current_version,
                "has_update": False,
                "latest_version": current_version,
                "msg": f"Không thể kết nối máy chủ cập nhật GitHub: {error}"
            }, ensure_ascii=False)

        if has_update:
            msg = f"Đã có phiên bản mới v{latest_version} (phiên bản hiện tại: v{current_version})!"
        else:
            msg = f"Bạn đang sử dụng phiên bản mới nhất v{current_version}"

        return json.dumps({
            "status": True,
            "current_version": current_version,
            "has_update": has_update,
            "latest_version": latest_version,
            "msg": msg
        }, ensure_ascii=False)

    def apply_update(self, get):
        import urllib.request
        import zipfile
        import io
        import shutil
        import tempfile

        plugin_dir = "/www/server/panel/plugin/camera_manager"
        archive_url = "https://github.com/namthanh0194/aapanel-camera-manager/archive/refs/heads/main.zip"

        write_event("plugin", "info", "", "update_download_started", "Bắt đầu tải bản cập nhật từ GitHub...")
        try:
            req = urllib.request.Request(archive_url, headers={"User-Agent": "aaPanel-Camera-Manager"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                archive_bytes = resp.read()

            with tempfile.TemporaryDirectory(prefix="cam_up_") as temp_dir:
                with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zip_file:
                    zip_file.extractall(temp_dir)

                extracted_roots = [
                    os.path.join(temp_dir, d) for d in os.listdir(temp_dir)
                    if os.path.isdir(os.path.join(temp_dir, d))
                ]
                if not extracted_roots:
                    raise ValueError("Gói cập nhật giải nén không hợp lệ")

                source_dir = extracted_roots[0]
                for item in os.listdir(source_dir):
                    if item in [".git", "dist", "tmp", ".gitignore"]:
                        continue
                    src_item = os.path.join(source_dir, item)
                    dst_item = os.path.join(plugin_dir, item)
                    if os.path.isdir(src_item):
                        shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src_item, dst_item)

            public.ExecShell(f"bash '{plugin_dir}/install.sh' update")
            write_event("plugin", "info", "", "update_success", "Cập nhật plugin thành công qua giao diện")
            return json.dumps({"status": True, "msg": "Cập nhật plugin thành công!"}, ensure_ascii=False)
        except Exception as error:
            write_event("plugin", "error", "", "update_failed", f"Cập nhật thất bại: {error}")
            return json.dumps({"status": False, "msg": f"Cập nhật plugin thất bại: {error}"}, ensure_ascii=False)
