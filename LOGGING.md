# Nhật ký Camera Manager (v1.0.5)

- Mở **Nhật ký** trên thanh công cụ hoặc **Log** tại từng camera.
- Bốn nhóm: Stream / Camera, Telegram, Dọn lưu trữ, Hoạt động plugin. Lọc camera, mức độ, từ/đến theo giờ trình duyệt; mặc định 200 dòng mới nhất, tối đa 1000 dòng.
- Tự cập nhật 5 giây là tùy chọn, tự dừng khi đóng cửa sổ. Sao chép/tải chỉ xuất những dòng đã lọc đang xem, đã che mật khẩu RTSP và bot token.
- `get_log_ui` trả component cố định `ui/logs.html`, không nhận đường dẫn tùy ý; không phụ thuộc CDN hay thư viện mới.

## Lưu trữ và giới hạn

Log tại `/var/log/camera_manager/events.jsonl`, cùng `.1`, `.2`, `.3`. Mỗi file tối đa 5 MiB; tổng nội dung log tối đa **20 MiB cho toàn plugin**, không phải cho từng camera. Khi đầy, tự xóa bản cũ nhất. `.lock` rỗng dùng khóa liên tiến trình. Metadata filesystem không nằm trong giới hạn nội dung 20 MiB. Không cam kết giữ đủ số ngày nếu lượng sự kiện nhiều.

Thư mục `root:www` mode `2770`, file log/lock `660`. Không cung cấp URL public để tải file log thô. API chạy qua cơ chế đăng nhập plugin aaPanel hiện có.

FFmpeg stderr được đọc bởi helper và gom cảnh báo lặp trong từng cửa sổ 30 giây; tối đa 11 mẫu cảnh báo riêng và một nhóm tổng hợp mỗi cửa sổ. Trạng thái bắt đầu/kết thúc ghi riêng. Thời lượng MP4 được kiểm tra khi uploader xét file hoàn tất: cảnh báo nếu dưới 80% thời lượng cấu hình. Đoạn ngắn do restart cũng có thể tạo cảnh báo; xem thao tác dịch vụ liền trước để phân biệt.

Giới hạn này chỉ áp dụng log mới của plugin, **không giới hạn/xóa journal hệ thống đã tồn tại**. Không sửa cấu hình journald toàn VPS. Nâng cấp helper cần restart dịch vụ camera đang chạy một lần để chuyển stderr sang bộ gom log; aaPanel không cần restart.

## Giữ nguyên chính sách video hiện tại

- Telegram trả `ok=true`: log gửi thành công, xóa file rồi log `telegram_success` với `telegram_sent=true`.
- Gửi lỗi: giữ file cho lần quét tiếp theo; log lỗi curl/API, thời gian gửi và `retry_after` nếu Telegram trả về.
- File vượt 48 MiB: hiện xóa mà chưa gửi, ghi `upload_oversize`, `telegram_sent=false`.
- Chưa cấu hình Telegram: file hoàn tất quá 10 phút bị xóa, ghi `no_telegram_config_10m`, `telegram_sent=false`.
- Dọn định kỳ: buffer MP4 quá 30 phút, output quá 60 phút, TS/work cũ được ghi lý do tương ứng. `telegram_sent=null` nghĩa là không có xác nhận đã gửi, không được hiểu là gửi thành công.
- Dọn thủ công ghi từng file và tổng dung lượng thu hồi. Cài đặt/cập nhật plugin ghi bắt đầu/hoàn tất; thay đổi cấu hình chỉ ghi tên trường, không ghi giá trị bí mật.

Log bắt đầu được thu sau nâng cấp; không nhập lại lịch sử từ journald để tránh đưa bí mật cũ vào log mới.
