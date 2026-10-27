import glob
import hashlib
import json
import os
import shutil
import subprocess
import time

from camera_manager_log import inspect_video, remove_logged, write_event
from camera_manager_storage import MIN_FREE_BYTES, file_identity, save_state, shared_directory, video_closed

MAX_UPLOAD_BYTES = 48_000_000


def destination_identity(bot_token, chat_id):
    return hashlib.sha256((bot_token + "\0" + str(chat_id)).encode()).hexdigest()


def destination_ready(buffer_dir, bot_token, chat_id):
    path = os.path.join(buffer_dir, ".delivery", "retry.json")
    if not os.path.isfile(path):
        return True
    with open(path) as source:
        state = json.load(source)
    return state.get("destination") != destination_identity(bot_token, chat_id) or time.time() >= state.get("next_retry", 0)


def send_telegram_video(bot_token, chat_id, video_path, caption, camera_id=""):
    command = ["curl", "-sS", "--connect-timeout", "20", "--max-time", "300",
               "--form-string", f"chat_id={chat_id}", "-F", f"video=@{video_path}",
               "--form-string", f"caption={caption}", f"https://api.telegram.org/bot{bot_token}/sendVideo"]
    started = time.monotonic()
    filename = os.path.basename(video_path)
    write_event("telegram", "info", camera_id, "upload_started", "Bắt đầu gửi video lên Telegram", file=filename, bytes=os.path.getsize(video_path))
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=320)
        if result.returncode:
            write_event("telegram", "error", camera_id, "upload_failed", "Gửi thất bại; giữ video để thử lại, chưa biết Telegram đã nhận hay chưa", file=filename, elapsed_seconds=round(time.monotonic() - started, 2), error=result.stderr, exit_code=result.returncode)
            return {"ok": False}
        data = json.loads(result.stdout)
        message_id = data.get("result", {}).get("message_id") if isinstance(data.get("result"), dict) else None
        if data.get("ok") is True and isinstance(message_id, int) and not isinstance(message_id, bool):
            write_event("telegram", "info", camera_id, "upload_success", "Telegram xác nhận gửi thành công", file=filename, elapsed_seconds=round(time.monotonic() - started, 2), message_id=message_id)
            return {"ok": True, "message_id": message_id}
        parameters = data.get("parameters") or {}
        retry_after = max(0, int(parameters.get("retry_after", 0)))
        write_event("telegram", "error", camera_id, "upload_rejected", "Telegram chưa xác nhận thành công; giữ file để thử lại", file=filename, elapsed_seconds=round(time.monotonic() - started, 2), error=data.get("description", "Phản hồi thiếu message_id"), error_code=data.get("error_code"), retry_after=retry_after)
        return {"ok": False, "retry_after": retry_after}
    except (OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired) as error:
        write_event("telegram", "error", camera_id, "upload_failed", "Không xác minh được kết quả gửi; giữ video để thử lại", file=filename, elapsed_seconds=round(time.monotonic() - started, 2), error=str(error))
        return {"ok": False}


def delivery_directory(video_path):
    return os.path.join(os.path.dirname(video_path), ".delivery", os.path.basename(video_path))


def finish_delivery(video_path, camera_id):
    directory = delivery_directory(video_path)
    if not os.path.isdir(directory):
        return
    for part in glob.glob(os.path.join(directory, "part_*.mp4")):
        remove_logged(part, camera_id, "fallback_artifact_cleanup", None)
    for name in ("state.json",):
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            os.unlink(path)
    os.rmdir(directory)


def prepare_fallback(video_path, directory, duration, camera_id):
    size = os.path.getsize(video_path)
    for old_part in glob.glob(os.path.join(directory, "part_*.mp4")):
        remove_logged(old_part, camera_id, "fallback_rebuild", False)
    if shutil.disk_usage(directory).free < MIN_FREE_BYTES + size * 2:
        raise ValueError("Không đủ dung lượng dự phòng để cứu hộ; giữ MP4 gốc")
    segment_time = max(0.25, duration * 40_000_000 / size)
    for _attempt in range(6):
        for old_part in glob.glob(os.path.join(directory, "part_*.mp4")):
            remove_logged(old_part, camera_id, "fallback_rebuild", False)
        command = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-i", video_path,
                   "-map", "0:v:0", "-map", "0:a?", "-c", "copy", "-f", "segment",
                   "-segment_time", str(segment_time), "-reset_timestamps", "1",
                   "-segment_format_options", "movflags=+faststart", os.path.join(directory, "part_%04d.mp4")]
        result = subprocess.run(command, capture_output=True, text=True, timeout=300)
        if result.returncode:
            raise ValueError(result.stderr or "FFmpeg không tạo được phần MP4 cứu hộ")
        paths = sorted(glob.glob(os.path.join(directory, "part_*.mp4")))
        if not paths or len(paths) > 128:
            raise ValueError("Số phần cứu hộ không hợp lệ; giữ MP4 gốc")
        sizes = [os.path.getsize(path) for path in paths]
        if min(sizes) <= 0:
            raise ValueError("Phần cứu hộ rỗng; giữ MP4 gốc")
        if max(sizes) > MAX_UPLOAD_BYTES:
            segment_time /= 2
            continue
        parts = []
        for path, part_size in zip(paths, sizes):
            part_duration = inspect_video(path, camera_id, 0)
            if part_duration is None or part_duration <= 0:
                raise ValueError("Phần cứu hộ chưa phải MP4 hoàn chỉnh; giữ MP4 gốc")
            parts.append({"name": os.path.basename(path), "identity": file_identity(path), "bytes": part_size, "duration": part_duration})
        if sum(part["duration"] for part in parts) < duration - max(2, duration * 0.01):
            raise ValueError("Cứu hộ thiếu thời lượng; giữ MP4 gốc")
        write_event("telegram", "warning", camera_id, "fallback_ready", "Video vượt 48 MB; đã tạo các phần MP4 cứu hộ, giữ nguyên bản gốc", file=os.path.basename(video_path), parts=len(parts), bytes=size)
        return parts
    raise ValueError("Không thể chia dưới 48 MB bằng stream copy; giữ MP4 gốc, không tự encode lại")


def schedule_retry(state_path, state, camera_id, filename, retry_after=0, local=False):
    if not local:
        state["attempts"] = min(int(state.get("attempts", 0)) + 1, 100)
    delay = 60 if local else max(60 * 2 ** min(state["attempts"] - 1, 5), int(retry_after))
    state["next_retry"] = time.time() + delay
    save_state(state_path, state)
    write_event("telegram", "warning", camera_id, "upload_retry_scheduled", "Giữ video, chờ đến lần thử lại", file=filename, retry_after=delay, attempts=state["attempts"])


def deliver_video(video_path, camera_id, bot_token, chat_id, duration, sender=send_telegram_video):
    parent = os.path.join(os.path.dirname(video_path), ".delivery")
    shared_directory(parent)
    directory = delivery_directory(video_path)
    shared_directory(directory)
    state_path = os.path.join(directory, "state.json")
    identity = file_identity(video_path)
    destination = destination_identity(bot_token, chat_id)
    state = {"identity": identity, "destination": destination, "sent": {}, "attempts": 0, "next_retry": 0}
    if os.path.isfile(state_path):
        with open(state_path) as source:
            state = json.load(source)
        if state.get("identity") != identity:
            raise ValueError("MP4 gốc đã thay đổi sau khi lập hàng đợi; giữ file để kiểm tra")
        if state.get("destination") != destination:
            raise ValueError("Đã thay đổi đích Telegram; không dùng lại biên nhận cũ hoặc xóa MP4 gốc")
    if time.time() < state.get("next_retry", 0):
        return False
    if not destination_ready(os.path.dirname(video_path), bot_token, chat_id):
        return False
    if not video_closed(video_path) or file_identity(video_path) != identity:
        return False
    try:
        if "parts" not in state:
            if identity[2] > MAX_UPLOAD_BYTES:
                state["parts"] = prepare_fallback(video_path, directory, duration, camera_id)
            else:
                state["parts"] = [{"name": "source", "identity": identity, "bytes": identity[2]}]
            save_state(state_path, state)
        filename = os.path.basename(video_path)
        for index, part in enumerate(state["parts"], start=1):
            name = part["name"]
            if name in state["sent"]:
                continue
            path = video_path if name == "source" else os.path.join(directory, name)
            if (os.path.basename(name) != name or not video_closed(path, minimum_age=0)
                    or file_identity(path) != part["identity"] or part["bytes"] > MAX_UPLOAD_BYTES):
                raise ValueError("Video thay đổi/đang mở hoặc phần cứu hộ không hợp lệ; không gửi/xóa")
            caption = f"📹 [Camera: {camera_id}]\n⏱ Video: {filename}"
            if name != "source":
                caption += f"\nCứu hộ: phần {index}/{len(state['parts'])}"
            result = sender(bot_token, chat_id, path, caption, camera_id)
            if not result.get("ok"):
                schedule_retry(state_path, state, camera_id, filename, result.get("retry_after", 0))
                save_state(os.path.join(parent, "retry.json"), {"destination": destination, "next_retry": state["next_retry"]})
                return False
            message_id = result.get("message_id")
            if not isinstance(message_id, int) or isinstance(message_id, bool):
                raise ValueError("Thiếu biên nhận Telegram; không xóa video")
            state["sent"][name] = message_id
            state["attempts"] = 0
            state["next_retry"] = 0
            save_state(state_path, state)
            if name != "source":
                remove_logged(path, camera_id, "telegram_success", True)
        return video_closed(video_path) and file_identity(video_path) == identity
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        write_event("telegram", "error", camera_id, "fallback_failed" if identity[2] > MAX_UPLOAD_BYTES else "processing_failed", "Chưa hoàn tất gửi video; giữ nguyên MP4 gốc", file=os.path.basename(video_path), error=str(error))
        schedule_retry(state_path, state, camera_id, os.path.basename(video_path), local=True)
        return False
