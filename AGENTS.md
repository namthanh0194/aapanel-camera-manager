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
├── ui/logs.html                           <-- Component nhật ký, tải qua API get_log_ui (không thêm asset global)
├── DELIVERY.md                            <-- MP4 trực tiếp, cứu hộ quá dung lượng, retry và bảo vệ ổ đĩa
├── install.sh                             <-- Script cài đặt, cập nhật, gỡ bỏ cho aaPanel
├── upgrade.sh                             <-- Kịch bản nâng cấp phiên bản
├── icon.png                               <-- Icon hiển thị trên App Store aaPanel
├── build.sh                               <-- Kịch bản đóng gói release camera_manager.zip
├── .gitignore                             <-- Bỏ qua file tạm, cache, release zip
└── core/                                  <-- Scripts lõi hệ thống camera
    ├── camera-buffer-run.sh               <-- ffmpeg ghi trực tiếp stream sang MP4 (segment)
    ├── camera-cleanup.sh                  <-- Dọn dẹp định kỳ (timer 3 phút)
    ├── cleanup-and-archive.py             <-- Logic gửi MP4 lên Telegram và xóa tức thì
    ├── camera_manager_log.py             <-- Log JSONL, che bí mật, xoay vòng và API đọc log
    ├── camera_manager_delivery.py        <-- Gửi thẳng MP4; fallback MP4-only, biên nhận và retry
    ├── camera_manager_probe.py           <-- Đánh dấu MP4 thiếu moov đã xác nhận; giữ gốc, bỏ probe lặp
    └── camera_manager_storage.py         <-- Khóa gửi/dọn, kiểm tra file mở, giám sát dung lượng recorder
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
- 48 MB = 48.000.000 byte. Chỉ cứu hộ MP4 vượt ngưỡng bằng stream-copy các phần MP4; không dùng TS hoặc chia lại đường đi bình thường.
- Không gửi/xóa file đang mở hoặc probe thất bại. Không xóa video chờ gửi theo tuổi; gốc cứu hộ chỉ xóa khi mọi phần có biên nhận Telegram được lưu bền vững.
- Chỉ giữ marker thiếu moov sau hai lần kiểm tra file đã đóng, không đổi, cách nhau tối thiểu 60 giây; không đánh dấu vĩnh viễn lỗi timeout/quyền. Marker nằm trong `.delivery/<file>/probe.json`, mất hiệu lực khi chữ ký file thay đổi; tuyệt đối không xóa video vì marker này.
- Stop/Restart dùng drop-in `KillMode=mixed` để guard chuyển tín hiệu đóng MP4 tới FFmpeg; không gửi đồng thời tín hiệu dừng ban đầu tới toàn nhóm recorder/logger.
- Timer, nút gửi và dọn thủ công phải dùng chung khóa uploader. Giữ retry/backoff và biên nhận trong `buffer/.delivery/`; không lưu bí mật.
- Bảo vệ dung lượng bằng tạm ngưng/tiếp tục recorder ở ngưỡng 1/1,25 GiB trống, không dùng tự xóa file chưa gửi làm cách chống đầy ổ.

### 3.4. Nhật ký có giới hạn
- Nhật ký riêng tại `/var/log/camera_manager/`, dùng chung toàn bộ camera và nhóm log, tối đa 20 MiB (file hiện tại 5 MiB + 3 bản xoay vòng).
- Dùng `camera_manager_log.write_event`; luôn che RTSP credentials và Telegram token trước khi ghi và khi trả API. Không ghi cấu hình nhạy cảm vào audit.
- Khóa `flock` bảo vệ ghi/xoay vòng giữa tiến trình root và www. Thư mục log `root:www` mode `2770`; file log/lock mode `660`.
- FFmpeg stderr đi qua bộ gom cảnh báo 30 giây, không nhân bản toàn bộ lỗi sang journald. Không sửa cấu hình journald toàn VPS hay tự xóa log hệ thống cũ.
- Mọi xóa video cần ghi lý do, dung lượng và trạng thái xác nhận Telegram (`true`, `false`, `null` khi chưa biết). Chính sách gửi/xóa an toàn được mô tả trong `DELIVERY.md`; tác vụ chỉ chỉnh log không được tự thay đổi chính sách này.
- UI nhật ký dùng module riêng `ui/logs.html`; controller và index chỉ nối API/nút mở, tránh nhồi thêm màn hình vào file đã dài.
- Các kiểm tra, fixture và artifact DEV đặt trong `tmp/` (đã gitignore), không đóng gói/deploy.
- Installer stage lõi trong `/opt/camera/tmp/` rồi rename cùng filesystem để không ghi đè inode script bash đang chạy; xóa staging rỗng sau cập nhật. Helper mode `640`, các script thực thi mode `750`, owner `root:www`.
