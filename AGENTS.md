# AGENTS.md - aaPanel Camera Manager Plugin

Tài liệu quy chuẩn kiến trúc và nguyên tắc phát triển cho dự án **aaPanel Camera Manager Plugin**.

---

## 1. Mục tiêu dự án
Xây dựng một Plugin chuẩn của aaPanel (`Third-party Plug-ins`) để:
- Quản lý tập trung các luồng camera RTSP (thêm, sửa, xóa, cấu hình tham số video/audio).
- Điều khiển tiến trình ghi rolling buffer (dịch vụ `camera-buffer@<camera_id>.service`).
- Tự động ghép nối video và gửi lưu trữ lên Telegram khi dọn dẹp bộ đệm định kỳ.
- Dễ dàng triển khai trên nhiều VPS khác nhau thông qua nút **Import plugins** của aaPanel hoặc cập nhật tự động từ GitHub Releases.

---

## 2. Cấu trúc thư mục dự án

```text
/root/dev/aapanel-camera-manager/          <-- Thư mục phát triển (DEV)
├── AGENTS.md                              <-- Tài liệu cấu trúc & Quy tắc lập trình
├── info.json                              <-- Khai báo metadata chuẩn aaPanel
├── camera_manager_main.py                 <-- Controller Python xử lý API của plugin
├── index.html                             <-- Giao diện Web tích hợp trong aaPanel
├── install.sh                             <-- Script cài đặt, cập nhật, gỡ bỏ cho aaPanel
├── upgrade.sh                             <-- Kịch bản nâng cấp phiên bản
├── icon.png                               <-- Icon hiển thị trên App Store aaPanel
├── build.sh                               <-- Kịch bản đóng gói release camera_manager.zip
├── .gitignore                             <-- Bỏ qua file tạm, cache, release zip
└── core/                                  <-- Scripts lõi hệ thống camera
    ├── camera-buffer-run.sh               <-- Tiến trình ffmpeg ghi rolling buffer .ts
    ├── camera-cleanup.sh                  <-- Script gọi định kỳ bởi systemd timer
    └── cleanup-and-archive.py             <-- Logic ghép TS sang MP4 và upload Telegram
```

---

## 3. Quy tắc cốt lõi khi lập trình (Coding Rules)

### 3.1. Phân định ranh giới DEV và PRODUCTION
- **Không bao giờ code trực tiếp** bên trong `/www/server/panel/plugin/camera_manager`.
- Mọi chỉnh sửa, commit Git phải diễn ra tại `/root/dev/aapanel-camera-manager`.
- Triển khai sang production thông qua việc đồng bộ hoặc chạy `install.sh update / build.sh`.

### 3.2. Bảo toàn dữ liệu & Cấu hình camera
- Quá trình cài đặt mới (`install`), nâng cấp (`upgrade`), hoặc cập nhật (`update`) **tuyệt đối không được ghi đè, xóa hoặc làm mất** các file cấu hình `.env` của camera tại `/opt/camera/*.env`.
- Dữ liệu video tạm trong `/tmp/video/cameras/` phải được duy trì, không xóa nhầm khi update plugin.

### 3.3. Tương thích chuẩn aaPanel Plugin Architecture
- `info.json` phải tuân theo đúng schema của aaPanel (`name`, `title`, `versions`, `checks`, `author`, `display`,...).
- Class Python chính trong `camera_manager_main.py` phải là class `camera_manager_main`. Mọi method public nhận tham số `get` (chứa input parameters từ aaPanel frontend) và trả về dữ liệu JSON qua `public.return_json(...)` hoặc dictionary chuẩn.
- Giao diện `index.html` cần tương thích với bộ thư viện CSS/JS có sẵn của aaPanel (layui, jQuery, font-awesome) và giao diện Dark/Light mode của panel.

### 3.4. Xử lý an toàn với FFMPEG & Telegram
- Khống chế dung lượng từng video ghép không vượt quá ngưỡng an toàn **40 MB** để tránh lỗi `413 Request Entity Too Large` của Telegram Bot API.
- Luôn xóa file MP4 và TS tạm ngay sau khi thực hiện xong lệnh gửi Telegram để tránh đầy bộ nhớ `/tmp`.
- Kiểm tra tính hợp lệ của camera ID (chỉ cho phép ký tự chữ cái, số và dấu gạch dưới `_`) để ngăn chặn các lỗ hổng path traversal hoặc command injection.

### 3.5. Cơ chế Versioning & Auto Update
- Mỗi khi phát hành tính năng mới, phải tăng version trong `info.json` theo chuẩn Semantic Versioning (`x.y.z`).
- Bản cập nhật được đóng gói thành file `.zip` sạch (không chứa file `.git`, `__pycache__`, file rác).
