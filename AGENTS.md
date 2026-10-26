# AGENTS.md - aaPanel Camera Manager Plugin

Tài liệu quy chuẩn kiến trúc và nguyên tắc phát triển cho dự án **aaPanel Camera Manager Plugin**.

---

## 1. Mục tiêu dự án
Xây dựng Plugin aaPanel (`Third-party Plug-ins`) để:
- Thu trực tiếp luồng camera RTSP và ghi thẳng thành các đoạn video **MP4 hoàn chỉnh** (mặc định 180s - 3 phút, dung lượng ~25-40 MB).
- Không cắt vụn thành hàng nghìn file `.ts` (bỏ hoàn toàn cơ chế motion PRE/POST cũ để tiết kiệm I/O ổ đĩa và CPU).
- Tự động đẩy từng đoạn video MP4 lên Telegram Bot (an toàn tuyệt đối dưới hạn mức 50 MB của Telegram Bot API).
- Sau khi gửi Telegram thành công: xóa ngay lập tức file video trên VPS để chống tràn ổ cứng.
- Đóng gói cài đặt đơn giản bằng nút **Import plugins** trên aaPanel ở bất kỳ VPS nào.

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
    ├── camera-buffer-run.sh               <-- ffmpeg ghi trực tiếp stream sang MP4 (segment)
    ├── camera-cleanup.sh                  <-- Dọn dẹp định kỳ (timer 3 phút)
    └── cleanup-and-archive.py             <-- Logic gửi MP4 lên Telegram và xóa tức thì
```

---

## 3. Quy tắc cốt lõi khi lập trình (Coding Rules)

### 3.1. Phân định ranh giới DEV và PRODUCTION
- Không sửa file trực tiếp trong `/www/server/panel/plugin/camera_manager`.
- Mọi chỉnh sửa được thực hiện ở `/root/dev/aapanel-camera-manager`, sau đó chạy `./build.sh` và `bash install.sh update`.

### 3.2. Không dùng TS nhỏ lẻ, ghi trực tiếp MP4
- FFMPEG ghi trực tiếp sang container `.mp4` bằng `-f segment -segment_time <seconds>`.
- Audio mặc định encode `aac 64k` để tương thích trên thiết bị di động Telegram.
- File MP4 đã hoàn tất được gửi lên Telegram và xóa ngay lập tức (`os.remove`).

### 3.3. Giới hạn dung lượng Telegram
- Khống chế dung lượng file tối đa không vượt quá 48 MB (ngưỡng an toàn của hạn mức 50 MB Telegram Bot API).
