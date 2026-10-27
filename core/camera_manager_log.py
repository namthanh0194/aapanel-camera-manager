import fcntl
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

LOG_DIR = "/var/log/camera_manager"
MAX_BYTES = 5 * 1024 * 1024
BACKUPS = 3
CATEGORIES = ("stream", "telegram", "storage", "plugin")
LEVELS = ("info", "warning", "error")
_write_warning = False


def _open_shared(path, flags):
    try:
        descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o660)
    except FileExistsError:
        return os.open(path, flags)
    os.fchmod(descriptor, 0o660)
    return descriptor


def redact(value):
    text = str(value)
    text = re.sub(r"(?i)(rtsps?://)[^\s/]*@", r"\1***@", text)
    text = re.sub(r"(?i)(https?://api\.telegram\.org/bot)[^/\s]+", r"\1***", text)
    text = re.sub(r"\b\d{5,}:[A-Za-z0-9_-]{15,}\b", "***", text)
    text = re.sub(r"(?i)((?:telegram_bot_token|password|passwd|token)\s*[=:]\s*)[^\s,;]+", r"\1***", text)
    return text[:2000]


def _safe_details(value):
    if isinstance(value, dict):
        return {redact(key): ("***" if re.search(r"(?i)token|password|passwd", str(key)) else _safe_details(item)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_details(item) for item in value[:30]]
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return redact(value)


def write_event(category, level, camera, event, message, **details):
    global _write_warning
    try:
        record = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "timestamp": time.time(), "category": category, "level": level,
            "camera": redact(camera)[:80], "event": redact(event)[:80],
            "message": redact(message), "details": _safe_details(details)
        }
        payload = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        if len(payload) > min(8192, MAX_BYTES):
            record["details"] = {"truncated": True}
            while len(payload) > min(8192, MAX_BYTES):
                record["message"] = record["message"][:len(record["message"]) // 2]
                payload = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
                if not record["message"] and len(payload) > MAX_BYTES:
                    return
        with os.fdopen(_open_shared(os.path.join(LOG_DIR, ".lock"), os.O_WRONLY | os.O_APPEND), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = os.path.join(LOG_DIR, "events.jsonl")
            if os.path.exists(path) and os.path.getsize(path) + len(payload) > MAX_BYTES:
                oldest = path + "." + str(BACKUPS)
                if os.path.exists(oldest):
                    os.remove(oldest)
                for index in range(BACKUPS - 1, 0, -1):
                    if os.path.exists(path + "." + str(index)):
                        os.replace(path + "." + str(index), path + "." + str(index + 1))
                os.replace(path, path + ".1")
            descriptor = _open_shared(path, os.O_WRONLY | os.O_APPEND)
            with os.fdopen(descriptor, "ab") as output:
                output.write(payload)
    except (OSError, ValueError, TypeError):
        if not _write_warning:
            sys.stderr.write("Camera Manager: cannot write log; check log directory permissions and free space.\n")
            _write_warning = True


def read_events(camera="all", category="all", level="all", since=0, until=0, limit=200):
    if camera != "all" and not re.fullmatch(r"[a-z0-9_]{1,80}", camera):
        raise ValueError("Mã camera không hợp lệ")
    if category not in ("all",) + CATEGORIES or level not in ("all",) + LEVELS:
        raise ValueError("Bộ lọc nhật ký không hợp lệ")
    limit = int(limit)
    since, until = float(since), float(until)
    if not 1 <= limit <= 1000 or not all(math.isfinite(item) and item >= 0 for item in (since, until)) or (until and since > until):
        raise ValueError("Giới hạn 1–1000 dòng; khoảng thời gian không hợp lệ")
    chunks = []
    used_bytes = 0
    if os.path.isdir(LOG_DIR):
        with os.fdopen(_open_shared(os.path.join(LOG_DIR, ".lock"), os.O_WRONLY | os.O_APPEND), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            for suffix in [""] + ["." + str(index) for index in range(1, BACKUPS + 1)]:
                path = os.path.join(LOG_DIR, "events.jsonl" + suffix)
                if os.path.isfile(path):
                    with open(path, "rb") as source:
                        chunk = source.read(MAX_BYTES)
                    used_bytes += os.path.getsize(path)
                    chunks.append(chunk)
    entries = []
    for chunk in chunks:
        for line in reversed(chunk.decode("utf-8", errors="replace").splitlines()):
            try:
                entry = json.loads(line)
                timestamp = float(entry["timestamp"])
                if camera != "all" and entry.get("camera") != camera:
                    continue
                if category != "all" and entry.get("category") != category:
                    continue
                if level != "all" and entry.get("level") != level:
                    continue
                if timestamp < since or (until and timestamp > until):
                    continue
                entries.append(_safe_details(entry))
            except (ValueError, KeyError, TypeError):
                continue
            if len(entries) > limit:
                break
        if len(entries) > limit:
            break
    return {"status": True, "entries": entries[:limit], "truncated": len(entries) > limit,
            "storage": {"path": LOG_DIR, "used_bytes": used_bytes, "max_bytes": MAX_BYTES * (BACKUPS + 1),
                        "file_bytes": MAX_BYTES, "files": len(chunks)}}


def remove_logged(path, camera, reason, telegram_sent=None):
    size = os.path.getsize(path)
    os.remove(path)
    write_event("storage", "info" if telegram_sent is True else "warning", camera, "file_deleted",
                "Đã xóa file", file=os.path.basename(path), bytes=size, reason=reason, telegram_sent=telegram_sent)
    return size


def inspect_video(path, camera, expected):
    try:
        response = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                                   "-of", "json", path], capture_output=True, text=True, timeout=5)
        if response.returncode:
            raise ValueError(redact(response.stderr))
        data = json.loads(response.stdout)
        duration = round(float(data["format"]["duration"]), 2)
        expected = float(expected)
        if not math.isfinite(duration) or duration <= 0 or not any(stream.get("codec_type") == "video" for stream in data.get("streams", [])):
            raise ValueError("Thời lượng không hợp lệ")
        short = expected > 0 and duration < expected * 0.8
        write_event("stream", "warning" if short else "info", camera, "video_ready",
                    "Video ngắn hơn cấu hình" if short else "Video hoàn tất, sẵn sàng xử lý",
                    file=os.path.basename(path), duration_seconds=duration, configured_seconds=expected,
                    bytes=os.path.getsize(path))
        return duration
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        write_event("stream", "error", camera, "video_probe_failed", "Không đọc được thời lượng video",
                    file=os.path.basename(path), error=str(error))
        return None


def consume_stream(source, camera):
    buckets = {}
    started = time.monotonic()

    def flush():
        for item in buckets.values():
            if item["repeated"]:
                write_event("stream", item["level"], camera, "ffmpeg_repeated", item["message"], repeated=item["repeated"])
        buckets.clear()

    write_event("stream", "info", camera, "stream_started", "Bắt đầu tiến trình ghi RTSP")
    for line in source:
        if time.monotonic() - started >= 30:
            flush()
            started = time.monotonic()
        message = redact(line.strip())
        if not message:
            continue
        # Bỏ qua các cảnh báo tự đồng bộ timestamp vô hại của FFmpeg muxer để tránh làm rác log
        if re.search(r"(?i)non-monotonous DTS|Queue input is backward in time|Last message repeated \d+ times", message):
            continue
        key = re.sub(r"0x[0-9a-f]+|[-+]?\d+(?:\.\d+)?", "#", message)
        if key in buckets:
            buckets[key]["repeated"] += 1
            continue
        level = "error" if re.search(r"(?i)error|failed|refused|timed out|invalid data|permission denied|no route|connection reset", message) else "warning"
        if len(buckets) >= 12:
            buckets["overflow"]["repeated"] += 1
            continue
        if "overflow" not in buckets:
            buckets["overflow"] = {"level": "warning", "message": "Các cảnh báo FFmpeg khác", "repeated": 0}
        buckets[key] = {"level": level, "message": message, "repeated": 0}
        write_event("stream", level, camera, "ffmpeg", message)
    flush()
    write_event("stream", "info", camera, "stream_ended", "Tiến trình ghi RTSP đã kết thúc; xem lỗi hoặc thao tác dừng/restart liền trước")


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "stream":
        consume_stream(sys.stdin, sys.argv[2])
    elif len(sys.argv) == 4 and sys.argv[1] == "delete":
        root = os.path.realpath(sys.argv[2])
        reason = sys.argv[3]
        for raw_path in sys.stdin.buffer.read().split(b"\0"):
            if not raw_path:
                continue
            path = os.fsdecode(raw_path)
            relative = os.path.relpath(os.path.abspath(path), root)
            if relative.startswith("../") or relative == ".":
                continue
            camera = relative.split(os.sep)[0]
            try:
                if os.path.isdir(path) and not os.path.islink(path):
                    for directory, subdirs, files in os.walk(path):
                        for filename in files:
                            remove_logged(os.path.join(directory, filename), camera, reason)
                    shutil.rmtree(path)
                else:
                    remove_logged(path, camera, reason)
            except OSError as error:
                write_event("storage", "error", camera, "delete_failed", "Không xóa được file/thư mục", file=path, error=str(error))


if __name__ == "__main__":
    main()
