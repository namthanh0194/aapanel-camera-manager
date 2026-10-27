# Nhật ký Camera Manager (v1.0.9)

- Mở **Nhật ký** trên thanh công cụ hoặc **Log** tại từng camera.
- Bốn nhóm: Stream / Camera, Telegram, Dọn lưu trữ, Hoạt động plugin. Lọc camera, mức độ, từ/đến theo giờ trình duyệt; mặc định 200 dòng mới nhất, tối đa 1000 dòng.
- Tự cập nhật 5 giây là tùy chọn, tự dừng khi đóng cửa sổ. Sao chép/tải chỉ xuất những dòng đã lọc đang xem, đã che mật khẩu RTSP và bot token.
- `get_log_ui` trả component cố định `ui/logs.html`, không nhận đường dẫn tùy ý; không phụ thuộc CDN hay thư viện mới.

## Lưu trữ và giới hạn

Log tại `/var/log/camera_manager/events.jsonl`, cùng `.1`, `.2`, `.3`. Mỗi file tối đa 5 MiB; tổng nội dung log tối đa **20 MiB cho toàn plugin**, không phải cho từng camera. Khi đầy, tự xóa bản cũ nhất. `.lock` rỗng dùng khóa liên tiến trình. Metadata filesystem không nằm trong giới hạn nội dung 20 MiB. Không cam kết giữ đủ số ngày nếu lượng sự kiện nhiều.

Thư mục `root:www` mode `2770`, file log/lock `660`. Không cung cấp URL public để tải file log thô. API chạy qua cơ chế đăng nhập plugin aaPanel hiện có.

FFmpeg stderr được đọc bởi helper và gom cảnh báo lặp trong từng cửa sổ 30 giây; tối đa 11 mẫu cảnh báo riêng và một nhóm tổng hợp mỗi cửa sổ. Trạng thái bắt đầu/kết thúc ghi riêng. Thời lượng MP4 được kiểm tra khi uploader xét file hoàn tất: cảnh báo nếu dưới 80% thời lượng cấu hình. Đoạn ngắn do restart cũng có thể tạo cảnh báo; xem thao tác dịch vụ liền trước để phân biệt.

Giới hạn này chỉ áp dụng log mới của plugin, **không giới hạn/xóa journal hệ thống đã tồn tại**. Không sửa cấu hình journald toàn VPS. Nâng cấp helper cần restart dịch vụ camera đang chạy một lần để chuyển stderr sang bộ gom log; aaPanel không cần restart.

## Chính sách video an toàn

- Telegram trả `ok=true`: log gửi thành công, xóa file rồi log `telegram_success` với `telegram_sent=true`.
- Gửi lỗi: giữ file cho lần quét tiếp theo; log lỗi curl/API, thời gian gửi và `retry_after` nếu Telegram trả về.
- File vượt 48.000.000 byte: cứu hộ bằng các phần MP4 stream-copy, log `fallback_ready` / `fallback_failed`; không tạo TS. Giữ bản gốc đến khi mọi phần được xác nhận gửi. Xem `DELIVERY.md`.
- `upload_retry_scheduled` ghi số lần lỗi và thời gian chờ; giữ biên nhận từng phần để tiếp tục sau restart. Không thể loại trừ gửi trùng khi phản hồi mạng bị mất trước khi nhận/lưu biên nhận.
- Chưa cấu hình Telegram, probe lỗi hoặc file đang ghi: không tự xóa. Không xóa buffer/output/work chỉ theo tuổi nữa. Các lý do xóa cũ trong lịch sử không phản ánh chính sách mới.
- Dưới 1 GiB trống, log `recording_paused_disk`: đóng MP4 và tạm ngưng ghi để giữ hàng đợi; đủ 1,25 GiB thì log `recording_resumed_disk` và ghi lại. `telegram_sent=null` không phải xác nhận gửi thành công.
- Dọn thủ công ghi từng file và tổng dung lượng thu hồi. Cài đặt/cập nhật plugin ghi bắt đầu/hoàn tất; thay đổi cấu hình chỉ ghi tên trường, không ghi giá trị bí mật.

Log bắt đầu được thu sau nâng cấp; không nhập lại lịch sử từ journald để tránh đưa bí mật cũ vào log mới.
