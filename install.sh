#!/usr/bin/env bash
PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin:~/bin
export PATH
set -e

PLUGIN_DIR="/www/server/panel/plugin/camera_manager"
CAMERA_DIR="/opt/camera"
CAMERA_ROOT="/tmp/video/cameras"

Deploy_Camera_Core() {
    local stage name
    install -d -m 750 -o root -g www "$CAMERA_DIR/tmp"
    stage=$(mktemp -d "$CAMERA_DIR/tmp/update.XXXXXX")
    for name in camera-buffer-run.sh camera-cleanup.sh cleanup-and-archive.py; do
        install -m 750 -o root -g www "$PLUGIN_DIR/core/$name" "$stage/$name"
    done
    install -m 640 -o root -g www "$PLUGIN_DIR/core/camera_manager_log.py" "$stage/camera_manager_log.py"
    for name in camera_manager_log.py camera-buffer-run.sh camera-cleanup.sh cleanup-and-archive.py; do
        mv -- "$stage/$name" "$CAMERA_DIR/$name"
    done
    rmdir "$stage"
    rmdir "$CAMERA_DIR/tmp" 2>/dev/null || true

    # Đảm bảo icon của plugin luôn được đồng bộ sang thư mục static icon của aaPanel
    local static_ico="/www/server/panel/BTPanel/static/img/soft_ico/ico-camera_manager.png"
    if [ -f "$PLUGIN_DIR/icon.png" ]; then
        install -m 644 -o root -g www "$PLUGIN_DIR/icon.png" "$static_ico"
    fi
}

Setup_Camera_Logging() {
    install -d -m 2770 -o root -g www /var/log/camera_manager
    Deploy_Camera_Core
}

Log_Plugin_Action() {
    PYTHONPATH="$CAMERA_DIR" python3 -B -c 'import json, sys; from camera_manager_log import write_event; version = json.load(open(sys.argv[2]))["versions"]; write_event("plugin", "info", "", sys.argv[1], "Cài đặt/cập nhật Camera Manager", version=version)' "$1" "$PLUGIN_DIR/info.json"
}

Install_Camera_Manager() {
    echo "===================================================="
    echo "Dang cai dat Camera Manager Plugin cho aaPanel..."
    echo "===================================================="

    if ! command -v ffmpeg &> /dev/null; then
        echo "Cai dat ffmpeg..."
        apt-get update -y && apt-get install -y ffmpeg
    fi

    mkdir -p "$CAMERA_DIR"
    mkdir -p "$CAMERA_ROOT"
    chown -R root:www "$CAMERA_DIR"
    chmod -R 750 "$CAMERA_DIR"
    chown -R www:www "$CAMERA_ROOT"
    chmod -R 775 "$CAMERA_ROOT"
    Setup_Camera_Logging
    Log_Plugin_Action install_started

    if [ ! -f /etc/systemd/system/camera-buffer@.service ]; then
        cat << 'SVC' > /etc/systemd/system/camera-buffer@.service
[Unit]
Description=Camera RTSP rolling buffer - %i
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=TZ=Asia/Ho_Chi_Minh
Environment=CAMERA_ENV=/opt/camera/%i.env
ExecStart=/opt/camera/camera-buffer-run.sh
Restart=always
RestartSec=5
User=www
Group=www
UMask=0002

[Install]
WantedBy=multi-user.target
SVC
        systemctl daemon-reload
    fi

    if [ ! -f /etc/systemd/system/camera-cleanup.timer ]; then
        cat << 'TMR' > /etc/systemd/system/camera-cleanup.timer
[Unit]
Description=Run camera cleanup every 3 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=3min
AccuracySec=10s
Unit=camera-cleanup.service

[Install]
WantedBy=timers.target
TMR
        cat << 'CSVC' > /etc/systemd/system/camera-cleanup.service
[Unit]
Description=Clean old camera buffer and send to Telegram

[Service]
Type=oneshot
ExecStart=/opt/camera/camera-cleanup.sh
CSVC
        systemctl daemon-reload
        systemctl enable --now camera-cleanup.timer
    fi

    Log_Plugin_Action install_completed
    echo "Cai dat Camera Manager Plugin thanh cong!"
}

Update_Camera_Manager() {
    echo "Dang cap nhat Camera Manager Plugin..."
    Setup_Camera_Logging
    Log_Plugin_Action update_started
    Log_Plugin_Action update_completed
    echo "Cap nhat hoan tat!"
}

Uninstall_Camera_Manager() {
    echo "Go bo Camera Manager Plugin..."
    rm -rf "$PLUGIN_DIR"
    echo "Go bo hoan tat!"
}

action=$1
if [ "${action}" == 'install' ]; then
    Install_Camera_Manager
elif [ "${action}" == 'update' ]; then
    Update_Camera_Manager
elif [ "${action}" == 'uninstall' ]; then
    Uninstall_Camera_Manager
fi
