import json
import os
import time

from camera_manager_delivery import delivery_directory
from camera_manager_log import write_event
from camera_manager_storage import file_identity, save_state, shared_directory, video_closed

PROBE_CONFIRM_SECONDS = 60


def inspect_pending_video(path, camera, expected, inspector):
    if not video_closed(path):
        return None
    identity = file_identity(path)
    directory = delivery_directory(path)
    marker = os.path.join(directory, "probe.json")
    for parent in (os.path.dirname(directory), directory):
        if os.path.lexists(parent):
            shared_directory(parent)
    if os.path.islink(marker):
        raise ValueError("Trạng thái kiểm tra video không được là symlink")
    state = {}
    if os.path.isfile(marker):
        with open(marker) as source:
            state = json.load(source)
        if state.get("identity") != identity or state.get("reason") != "missing_moov":
            state = {}
    if state.get("confirmed") is True or time.time() < state.get("next_probe", 0):
        return None

    failure = {}
    duration = inspector(path, camera, expected, failure_details=failure)
    if not video_closed(path) or file_identity(path) != identity:
        return None
    if duration is not None or failure.get("reason") != "missing_moov":
        if os.path.isfile(marker):
            os.unlink(marker)
        return duration

    confirmed = bool(state)
    shared_directory(os.path.dirname(directory))
    shared_directory(directory)
    save_state(marker, {
        "identity": identity,
        "reason": "missing_moov",
        "confirmed": confirmed,
        "next_probe": time.time() + PROBE_CONFIRM_SECONDS,
    })
    if confirmed:
        write_event("stream", "warning", camera, "video_probe_held",
                    "MP4 thiếu moov qua hai lần kiểm tra; giữ nguyên file, ngừng quét lại cho đến khi file thay đổi",
                    file=os.path.basename(path), bytes=identity[2])
    return None
