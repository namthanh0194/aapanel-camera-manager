import contextlib
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from camera_manager_log import write_event

MIN_FREE_BYTES = 1024 * 1024 * 1024
RESUME_FREE_BYTES = MIN_FREE_BYTES + 256 * 1024 * 1024


def shared_directory(path):
    try:
        os.mkdir(path, 0o2770)
    except FileExistsError:
        if os.path.islink(path) or not os.path.isdir(path):
            raise ValueError("Thư mục trạng thái không hợp lệ")
        return
    os.chown(path, -1, os.stat(os.path.dirname(path)).st_gid)
    os.chmod(path, 0o2770)


def save_state(path, state):
    directory = os.path.dirname(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".state-", dir=directory)
    try:
        os.fchown(descriptor, -1, os.stat(directory).st_gid)
        os.fchmod(descriptor, 0o660)
        with os.fdopen(descriptor, "w") as output:
            json.dump(state, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def archive_lock(root):
    path = os.path.join(root, ".archive.lock")
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o660)
    except FileExistsError:
        descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    else:
        os.fchown(descriptor, -1, os.stat(root).st_gid)
        os.fchmod(descriptor, 0o660)
    with os.fdopen(descriptor, "r+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            try:
                yield True
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def file_identity(path):
    info = os.stat(path, follow_symlinks=False)
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def file_in_use(path):
    identity = file_identity(path)
    parent = os.path.realpath(os.path.dirname(path)) + os.sep
    with os.scandir("/proc") as processes:
        for process in processes:
            if not process.name.isdigit():
                continue
            try:
                descriptors = os.listdir(process.path + "/fd")
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                continue
            for descriptor in descriptors:
                candidate = process.path + "/fd/" + descriptor
                try:
                    if os.readlink(candidate).startswith(parent):
                        info = os.stat(candidate)
                        if [info.st_dev, info.st_ino] == identity[:2]:
                            return True
                except (FileNotFoundError, PermissionError, ProcessLookupError):
                    continue
    return False


def video_closed(path, minimum_age=30):
    return (not os.path.islink(path) and os.path.isfile(path)
            and time.time() - os.path.getmtime(path) >= minimum_age and not file_in_use(path))


def record_with_space_guard(command, buffer_dir, camera):
    stopping = False
    process = None

    def stop(signum, frame):
        nonlocal stopping
        stopping = True
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGINT)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    paused = False
    while not stopping:
        if shutil.disk_usage(buffer_dir).free < RESUME_FREE_BYTES:
            if not paused:
                write_event("storage", "error", camera, "recording_paused_disk", "Tạm ngưng ghi để bảo vệ ổ đĩa; giữ nguyên video chờ gửi", reserve_bytes=MIN_FREE_BYTES)
                paused = True
            time.sleep(5)
            continue
        if paused:
            write_event("storage", "info", camera, "recording_resumed_disk", "Đã đủ dung lượng; tiếp tục ghi MP4")
            paused = False
        process = subprocess.Popen(command)
        while process.poll() is None and not stopping:
            if shutil.disk_usage(buffer_dir).free < MIN_FREE_BYTES:
                write_event("storage", "error", camera, "recording_paused_disk", "Đóng MP4 và tạm ngưng ghi do dung lượng thấp; không xóa video chưa gửi", reserve_bytes=MIN_FREE_BYTES)
                paused = True
                process.send_signal(signal.SIGINT)
                break
            time.sleep(5)
        try:
            result = process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            result = process.wait()
            write_event("stream", "error", camera, "recorder_stop_timeout", "FFmpeg không đóng file kịp; giữ file để kiểm tra")
        if stopping or not paused:
            return result
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 4 or sys.argv[1] != "record":
        raise SystemExit(2)
    raise SystemExit(record_with_space_guard(sys.argv[2:], os.environ["CAMERA_BUFFER_DIR"], os.environ["CAMERA_ID"]))
