# Ghi MP4 và gửi Telegram an toàn — v1.1.0

## Đường đi bình thường

Camera → FFmpeg → một MP4 cho mỗi đoạn cấu hình → Telegram → xóa MP4 khi có xác nhận `ok=true` và `message_id`.

Giữ nguyên `-f segment -segment_time`, video stream-copy và AAC như trước. Không tạo TS, không chia nhỏ hoặc encode lại video bình thường. Bản gốc tối đa **48.000.000 byte** được gửi thẳng; 48 MB ở đây là hệ thập phân, không phải 48 MiB.

## Cứu hộ khi file vượt 48 MB

- Chỉ xử lý MP4 đã đóng, có video và thời lượng đọc được bằng ffprobe. Không lấy file đang mở ghi, kể cả khi mtime đã cũ.
- Tạo các phần MP4 bằng stream-copy trong `buffer/.delivery/<tên-file-gốc.mp4>/`, không tạo TS. Kiểm tra từng phần có dung lượng thực tế không vượt 48.000.000 byte, thời lượng hợp lệ, và tổng thời lượng không bị thiếu đáng kể.
- Chia theo keyframe nên thời lượng các phần không nhất thiết bằng nhau. Nếu một GOP quá lớn không thể chia dưới ngưỡng bằng copy, giữ bản gốc và báo lỗi; không tự chuyển sang encode nặng CPU.
- Mỗi phần có số thứ tự trong caption. Sau khi Telegram xác nhận, lưu biên nhận bền vững rồi xóa phần tạm. Chỉ xóa bản gốc khi **tất cả** phần được xác nhận; sau đó dọn thư mục trạng thái.
- Nếu phần thứ hai lỗi, lần sau tiếp tục phần đó, không gửi lại phần đã có biên nhận. Lỗi tạo phần cứu hộ không dẫn tới xóa bản gốc.

## Retry, khóa và file đang ghi

- Timer và nút gửi thủ công dùng chung khóa `CAMERA_ROOT/.archive.lock`. Dọn thủ công cũng cần khóa này; không chạy chồng với uploader.
- Trước khi probe/gửi/xóa: kiểm tra file không phải symlink, không được tiến trình mở, và không thay đổi inode/dung lượng/mtime sau khi probe. File mới đóng được chờ tối thiểu 30 giây.
- `buffer/.delivery/<tên-file>/state.json` lưu chữ ký file, danh sách phần, message ID đã nhận, số lần lỗi và thời điểm thử tiếp. Không lưu token, mật khẩu hoặc RTSP URL. File state ghi qua temp + fsync + rename; quyền `660`, thư mục `2770`, group theo thư mục cha để root/www dùng chung.
- Timeout/curl lỗi, Telegram 504, phản hồi không hợp lệ hoặc thiếu biên nhận: giữ file. Backoff bắt đầu 60 giây, tăng đến 1.920 giây; nếu Telegram trả `retry_after` dài hơn thì tôn trọng. Timer 3 phút là nhịp xét lại, không cam kết retry đúng từng giây.
- Network timeout có thể xảy ra sau khi Telegram đã nhận nhưng trước khi VPS nhận phản hồi. Bot API không cung cấp khóa idempotency cho sendVideo; retry trường hợp này **có thể tạo video trùng**. Không tuyên bố chống trùng tuyệt đối; chỉ bỏ gửi lại các phần đã có biên nhận lưu thành công.
- Biên nhận gắn với hash đích Telegram (bot + chat), không lưu token. Thay bot/chat khi đang gửi dở: giữ gốc, báo cần kiểm tra thay vì ghép biên nhận giữa hai đích. Lỗi mạng/API đặt thời gian chờ chung cho camera; lỗi cứu hộ cục bộ không chặn các MP4 bình thường phía sau, để vẫn giải phóng được dung lượng.
- Lỗi chuẩn bị cứu hộ cục bộ chờ cố định 60 giây, không tăng bộ đếm backoff mạng.

## Bảo vệ ổ đĩa và giữ file chờ gửi

- Bỏ xóa MP4 chỉ vì quá 30/60 phút và bỏ xóa video chưa cấu hình Telegram sau 10 phút. File lỗi ffprobe được giữ, không upload hoặc coi là rác tự động.
- Không tự xóa `work/output` cũ theo tuổi. Dọn thủ công vẫn là thao tác có chủ đích, có cảnh báo và log; không dọn file đang mở hoặc lúc uploader giữ khóa.
- Tiến trình giám sát recorder kiểm tra dung lượng mỗi 5 giây. Dưới **1 GiB trống**: yêu cầu FFmpeg đóng MP4 và tạm ngưng ghi; không xóa hàng đợi. Đủ **1,25 GiB trống**: tự ghi lại. Cứu hộ cần thêm dung lượng dự phòng trước khi tạo bản chia.
- Đây là ngưỡng bảo vệ, không phải hạn ngạch riêng cho camera hoặc cam kết ổ đĩa không bao giờ đầy: tác vụ khác trên VPS và tốc độ ghi giữa hai lần kiểm tra vẫn có thể tiêu thụ dung lượng. Khi tạm ngưng, có khoảng trống ghi hình; xem log `recording_paused_disk` / `recording_resumed_disk`.

## Cài đặt và cập nhật

`build.sh` đóng gói hai helper mới cùng core hiện có. Installer stage và rename các module trước khi thay entrypoint, giữ helper `root:www 640`, script `root:www 750`. Installer tự restart lần lượt recorder đang chạy và xác minh tiến trình guard trước khi báo cập nhật hoàn tất; không bật camera đang dừng, không thay đổi RTSP URL, thời lượng đoạn, audio hoặc Telegram của camera. Restart có thể tạo một MP4 ngắn tại ranh giới cập nhật.

Các cảnh báo kết nối RTSP và lỗi codec vẫn phải được theo dõi riêng; retry uploader không sửa được camera đang tắt hay mạng tới Telegram bị gián đoạn.
