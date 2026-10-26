#!/usr/bin/env bash
PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin:~/bin
export PATH
set -e

PLUGIN_DIR="/www/server/panel/plugin/camera_manager"
CAMERA_DIR="/opt/camera"
CAMERA_ROOT="/tmp/video/cameras"

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

    if [ -d "$PLUGIN_DIR/core" ]; then
        cp "$PLUGIN_DIR/core/camera-buffer-run.sh" "$CAMERA_DIR/"
        cp "$PLUGIN_DIR/core/camera-cleanup.sh" "$CAMERA_DIR/"
        cp "$PLUGIN_DIR/core/cleanup-and-archive.py" "$CAMERA_DIR/"
        chmod +x "$CAMERA_DIR"/*.sh "$CAMERA_DIR"/*.py 2>/dev/null || true
    fi

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

    echo "Cai dat Camera Manager Plugin thanh cong!"
}

Update_Camera_Manager() {
    echo "Dang cap nhat Camera Manager Plugin..."
    if [ -d "$PLUGIN_DIR/core" ]; then
        cp "$PLUGIN_DIR/core/camera-buffer-run.sh" "$CAMERA_DIR/"
        cp "$PLUGIN_DIR/core/camera-cleanup.sh" "$CAMERA_DIR/"
        cp "$PLUGIN_DIR/core/cleanup-and-archive.py" "$CAMERA_DIR/"
        chmod +x "$CAMERA_DIR"/*.sh "$CAMERA_DIR"/*.py 2>/dev/null || true
    fi
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
