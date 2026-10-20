# MoneyPrinterPro

> **Nguồn:** bản tuỳ biến dựa trên dự án gốc **MoneyPrinterTurbo** của Harry –
> https://github.com/harry0703/MoneyPrinterTurbo (giấy phép MIT, xem `LICENSE`).
> Bản này không kết nối tới kho gốc: không tự cập nhật, không kiểm tra phiên bản.

Tạo video ngắn tự động (kịch bản, lồng tiếng, phụ đề, tư liệu, nhạc nền) và ảnh GIF có chữ,
điều khiển qua WebUI hoặc bot Telegram, rồi lên lịch đăng Facebook Reels, TikTok, YouTube Shorts.

## Thành phần

| Thành phần | Chạy bằng | Ghi chú |
| --- | --- | --- |
| WebUI | `start.bat` / `webui.bat` / `webui.sh` | Hai chế độ: **Tạo nhanh** (giống bot) và **Tuỳ chỉnh chi tiết** |
| Bot Telegram | `telegram_bot.bat` / `python telegram_bot.py` | `start.bat` tự mở bot nếu đã có `bot_token` |
| Tạo hàng loạt từ file | `python telegram_batch.py` | Gửi kết quả qua Telegram, chạy tiếp được khi bị ngắt |
| API | `api.bat` / `python main.py` | http://127.0.0.1:8080/docs |
| CLI | `python cli.py --help` | Tạo video không cần trình duyệt |

WebUI (chế độ Tạo nhanh) và bot dùng chung một phần xử lý (`app/services/quick_create.py`), chung thư
mục thành phẩm và chung lịch đăng bài.

## Yêu cầu

- Windows 10 trở lên. Bản portable đã kèm Python 3.11 (`lib/python`) và FFmpeg (`lib/ffmpeg`).
  Chạy từ mã nguồn (Windows/macOS/Linux) cần Python 3.11+ và FFmpeg.
- Đường dẫn thư mục **không dấu, không khoảng trắng, không ký tự đặc biệt**
  (ví dụ `D:\MoneyPrinterPro`).
- Khuyến nghị CPU 4–8 nhân, RAM 8 GB. GPU không bắt buộc.
- Google Chrome hoặc Microsoft Edge (chỉ cần khi đăng bài lên mạng xã hội).
- Tài khoản/khoá API:

| Dịch vụ | Bắt buộc | Dùng cho |
| --- | --- | --- |
| Một nhà cung cấp LLM (OpenAI, Gemini, DeepSeek, Moonshot, Ollama...) | Có | Kịch bản, từ khoá, nội dung đăng bài, câu hỏi bổ sung, chủ đề con |
| Pexels hoặc Pixabay | Có (trừ khi dùng ảnh/video của bạn) | Tư liệu video. Ảnh GIF có chữ cần **Pixabay** |
| Edge TTS | Không cần khoá | Giọng đọc mặc định, miễn phí |
| Telegram bot token (@BotFather) | Chỉ khi dùng bot | Bot và thông báo kết quả đăng bài |

## Cài đặt

### Bản portable Windows

```
MoneyPrinterTurbo-Portable-Windows\
├─ lib\               Python 3.11, FFmpeg, Git đi kèm
├─ MoneyPrinterTurbo\ mã nguồn (repo này)
├─ start.bat          mở WebUI (+ bot Telegram nếu đã cấu hình)
├─ telegram_bot.bat   chỉ mở bot
├─ api.bat            mở API
└─ update.bat         cài/cập nhật thư viện Python (không tải mã nguồn mới)
```

1. Đặt thư mục vào một đường dẫn không dấu, không khoảng trắng.
2. Chạy `update.bat` một lần để cài đủ thư viện trong `requirements.txt`
   (gồm `pyTelegramBotAPI` và `playwright`).
3. Chạy `start.bat`. Lần đầu, `config.toml` được tạo từ `config.example.toml`.
4. Mở http://127.0.0.1:8501 (nếu cổng bận, `start.bat` tự chọn cổng 8502–8599 và in ra địa chỉ),
   vào **Cài đặt** nhập khoá LLM và khoá Pexels/Pixabay.
5. Muốn dùng bot: điền mục `[telegram]` trong `config.toml` (xem bên dưới) rồi chạy lại `start.bat`.

### Chạy từ mã nguồn

```shell
git clone https://github.com/vitbau246/MoneyPrinterPro.git
cd MoneyPrinterPro
python3.11 -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Dùng `requirements.txt` (không dùng `uv sync`): bot Telegram và phần đăng bài cần `pyTelegramBotAPI`
và `playwright`, chỉ có trong file này. Playwright điều khiển Chrome/Edge có sẵn nên **không** cần
`playwright install`.

```shell
webui.bat                 # Windows (hoặc: sh webui.sh)
python telegram_bot.py    # bot Telegram, chạy ở cửa sổ khác
python main.py            # API, nếu cần
```

Nếu báo không tìm thấy FFmpeg, cài FFmpeg rồi đặt `ffmpeg_path` trong `[app]` của `config.toml`.

### Docker (tuỳ chọn)

```shell
cp config.example.toml config.toml
docker compose up --build
```

WebUI ở http://127.0.0.1:8501, API ở http://127.0.0.1:8080/docs. Docker chỉ chạy WebUI và API,
không gồm bot Telegram và phần đăng bài.

## Cấu hình

Mọi thiết lập nằm trong `config.toml` (đã có trong `.gitignore`, **không commit** vì chứa token và
khoá API). Phần lớn chỉnh được trong WebUI → **Cài đặt**; giọng đọc, phụ đề, nhạc nền, nguồn video
chỉnh ở chế độ **Tuỳ chỉnh chi tiết** và được bot dùng chung (bot đọc lại `config.toml` trước mỗi
yêu cầu, không cần khởi động lại).

| Khoá | Ý nghĩa |
| --- | --- |
| `[app] llm_provider`, `<provider>_api_key`, `<provider>_model_name` | LLM viết kịch bản, ví dụ `llm_provider = "openai"`, `openai_model_name = "..."` |
| `[app] video_source`, `pexels_api_keys`, `pixabay_api_keys` | Nguồn tư liệu video |
| `[app] subtitle_provider` | `edge` (mặc định, nhanh) hoặc `whisper` (chính xác hơn, tải mô hình ~3 GB) |
| `[app] edge_tts_proxies` | Danh sách proxy thử lần lượt cho Edge TTS |
| `[app] cover_intro_seconds` | Số giây ảnh bìa ghép ở đầu video, `0` để tắt |
| `[app] ffmpeg_path` | Đường dẫn `ffmpeg.exe` nếu không tự tìm thấy |
| `[app] listen_host`, `api_key` | Mở API ra mạng LAN thì phải đặt cả hai |
| `[proxy] http`, `https` | Proxy tải tư liệu (Pexels, Pixabay...) |

Bot Telegram và đăng bài:

```toml
[telegram]
bot_token = "123456:ABC..."        # hoặc biến môi trường TELEGRAM_BOT_TOKEN
allowed_user_ids = [123456789]     # người được dùng bot; người khác bấm "Gửi yêu cầu cấp quyền"
admin_user_ids = []                # trống = các user trong allowed_user_ids
proxy = "http://10.0.0.1:8800"     # proxy riêng cho api.telegram.org (tuỳ chọn)
high_model = "gpt-6.1-sol"         # model cho yêu cầu có #high (chỉ với llm_provider = "openai")
default_language = "vi-VN"         # hoặc "en-US" (lời đọc tiếng Anh, phụ đề tiếng Việt)
default_duration = 0               # giây (15–180); 0 = mặc định của từng loại nội dung
# voices = { "en-US" = "en-US-GuyNeural-Male" }

[social]
proxy = "http://10.0.0.1:8800"     # proxy cho Chrome đăng bài; trống = proxy hệ thống
# browser_path = ""                # trống = tự tìm Chrome, rồi Edge
# cdp_port = 9333
# profile_dir = ""                 # trống = storage/social/browser_profile
```

Các khoá `high_model`, `default_language`, `default_duration`, `voices` áp dụng cho cả bot và chế độ
Tạo nhanh trên web. Trong mạng có proxy chặn Telegram, Pixabay hay Edge TTS, đặt proxy dùng được
cho `[telegram] proxy`, `[proxy]`, `edge_tts_proxies` và `[social] proxy`.

## Sử dụng

### Loại nội dung và tuỳ chọn

| Lệnh bot | Loại nội dung |
| --- | --- |
| `/kienthuc` | Kiến thức / sự thật thú vị |
| `/dongluc` | Động lực / triết lý sống |
| `/chualanh` | Chữa lành / thư giãn |
| `/meo` | Mẹo / hướng dẫn nhanh |
| `/tintuc` | Tin tức / tóm tắt (dán nội dung bài báo gốc) |
| `/sanpham` | Giới thiệu sản phẩm (bắt buộc gửi kèm ảnh/video) |
| `/diadiem` | Khám phá địa điểm (có thể gửi kèm ảnh/video) |

Tuỳ chọn gõ kèm nội dung, dùng được cả trên bot lẫn ô nội dung của web:

| Tuỳ chọn | Ý nghĩa |
| --- | --- |
| `#45s`, `#2p` | Thời lượng (15 giây – 3 phút) |
| `#doc`, `#ngang`, `#vuong` | Khung hình 9:16 (mặc định), 16:9, 1:1 |
| `#vi`, `#en` | Ngôn ngữ lời đọc |
| `#gif` | Ảnh GIF có chữ từ clip Pixabay thay cho video (không dùng với `/sanpham`) |
| `#high` | Dùng model AI mạnh hơn (`[telegram].high_model`) |
| `#dang`, `#khongdang` | Lên lịch / không đăng mạng xã hội sau khi tạo |
| `#15` | Số mục khi tạo hàng loạt |

Ví dụ: `/meo 5 mẹo ngủ ngon #90s #ngang`, `/dongluc Kiên trì mỗi ngày #gif`.

### WebUI

- **Tạo nhanh**: tab *Tạo một mục*, *Tạo hàng loạt* (AI đề xuất chủ đề con, sửa trực tiếp hoặc góp
  ý rồi duyệt), *Thư viện thành phẩm*, *Đăng bài*; cột phải là hàng đợi và kết quả.
- **Tuỳ chỉnh chi tiết**: biểu mẫu đầy đủ (LLM, nguồn tư liệu, giọng đọc, phụ đề, nhạc nền...).
  Lựa chọn chế độ được nhớ cho lần sau.

### Bot Telegram

| Lệnh | Việc |
| --- | --- |
| `/<loại> <nội dung>` | Tạo một video/ảnh GIF; gửi ảnh hoặc album với caption `/sanpham ...` để dùng ảnh riêng |
| `/hangloat <loại> <chủ đề> [#số lượng] [#gif]` | AI đề xuất chủ đề con, duyệt / đề xuất lại / nhắn góp ý, rồi tạo lần lượt |
| `/dunghangloat` | Dừng loạt sau mục đang tạo |
| `/thoiluong`, `/ngonngu` | Thời lượng và ngôn ngữ mặc định của bạn |
| `/trangthai` | Hàng đợi |
| `/dangnhap`, `/dang`, `/lichdang`, `/tudongdang` | Đăng mạng xã hội (xem dưới) |
| `/nguoidung`, `/thuhoi <user_id>` | Admin: quản lý người dùng |

Chỉ chạy **một** bot cho mỗi token (bot chạy trùng sẽ tự thoát). Log ở `storage/logs/telegram_bot.log`.

### Đăng Facebook Reels, TikTok, YouTube Shorts

Đăng bằng Chrome/Edge với một profile riêng, điều khiển qua CDP (Playwright).

1. **Đăng nhập lần đầu**: WebUI → Tạo nhanh → *Đăng bài* → **Mở trình duyệt để đăng nhập**
   (hoặc `/dangnhap` trên bot). Đăng nhập Facebook, TikTok, YouTube Studio trong cửa sổ đó; phiên
   đăng nhập được giữ trong `storage/social/browser_profile`.
   - Facebook: muốn đăng lên một Trang thì chuyển sang hồ sơ của Trang đó.
   - YouTube: chọn đúng kênh trong YouTube Studio.
2. **Xác nhận trang/kênh**: bấm *Kiểm tra đăng nhập & xác nhận trang/kênh* (hoặc `/dangnhap kiemtra`).
   Tài khoản đang đăng nhập (Trang/hồ sơ Facebook, @username TikTok, kênh YouTube) được lưu ở
   `storage/social/accounts.json`. Trước mỗi lần đăng, chương trình so tài khoản trong trình duyệt
   với tài khoản đã xác nhận; chưa xác nhận hoặc khác tài khoản thì **không đăng** và báo lỗi.
   Đổi tài khoản đăng bài: chuyển tài khoản trong trình duyệt rồi kiểm tra lại.
3. **Chạy thử** trước khi đăng thật: tick *Chạy thử* trên web hoặc `/dang 105 ngay #thu` – điền xong
   tiêu đề/mô tả nhưng không bấm Đăng, tab để mở cho bạn xem.
4. **Lên lịch**:
   - Web: chọn video trong thư viện, nền tảng, thời điểm (khung giờ trống kế tiếp / ngay / giờ cụ thể).
   - Bot: `/dang <số video> [fb tt yt] [ngay | 20:00 | 21/10 20:00] [#thu]`, ví dụ `/dang 105-110 tt yt`.
   - Xem, đăng ngay, huỷ: danh sách *Lịch đăng* trên web hoặc `/lichdang`.
5. **Tự động đăng video mới**: mục *Đăng tự động & khung giờ* trên web hoặc
   `/tudongdang bat 8:00 12:00 19:30 fb tt yt`. Mỗi video vào một khung giờ còn trống.

Nội dung tự điền khi đăng: tiêu đề, mô tả kèm hashtag (Facebook, TikTok dùng tiêu đề + mô tả) và thẻ
YouTube. Video mới tạo được AI viết sẵn các phần này ngay khi tạo (lưu ở
`storage/social/captions.json`). Video cũ chưa có thì AI tự viết từ lời thoại (`.txt`) trước khi
đăng; trên web có nút *✨ Viết bằng AI* để tạo và sửa trước.

Kết quả đăng được báo qua Telegram. Lỗi được thử lại 1 lần sau 10 phút; ảnh chụp màn hình lỗi ở
`storage/social/screenshots`. Lỗi xảy ra sau khi đã bấm Đăng thì không thử lại (bài có thể đã lên,
thử lại sẽ thành bài trùng): bot báo ⚠️ để bạn kiểm tra trên trang. Web và bot dùng chung lịch, mỗi lúc chỉ một bên thực hiện đăng. Máy
phải bật và WebUI hoặc bot phải đang chạy đến giờ đăng.

### Tạo hàng loạt từ file

```shell
python telegram_batch.py --preset dongluc --topics storage/batch/dongluc.txt [--gif] [--high] [--dang]
```

Mỗi dòng của file là một chủ đề (dòng trống và dòng bắt đầu bằng `#` bị bỏ qua). Tiến độ lưu ở
`<file>.progress.json`, chạy lại lệnh để tiếp tục; tạo file `<file>.stop` để dừng sau mục đang chạy.
Các file `telegram_batch_*.bat` ở thư mục portable là ví dụ sẵn.

## Thư mục dữ liệu

| Đường dẫn | Nội dung |
| --- | --- |
| `storage/output/video` | Thành phẩm `#NNN Tiêu đề.mp4` + ảnh bìa `.jpg` + lời thoại `.txt` |
| `storage/output/gif` | Ảnh GIF `#NNN Câu chữ.gif` + bản `.mp4` + lời diễn giải `.txt` |
| `storage/social` | Lịch đăng, thiết lập đăng tự động, nội dung đăng bài, profile trình duyệt, ảnh lỗi |
| `storage/tasks` | Thư mục tạm của từng lần tạo (xoá sau khi đã lưu thành phẩm) |
| `storage/logs` | Log của bot |
| `storage/telegram_*.json` | Thiết lập theo người dùng và danh sách được cấp quyền của bot |

`storage/` nằm trong `.gitignore`; sao lưu riêng nếu cần.

## Kiểm thử

```shell
python -m unittest discover -s test -t .
```

Bộ test tự dùng `config.toml` và `storage` tạm, không đụng tới cấu hình và dữ liệu thật. Không chạy
trực tiếp `python test/services/test_x.py` (bỏ qua bước cô lập).

## Xử lý sự cố

- **`No ffmpeg exe could be found`**: đặt `ffmpeg_path = "C:\\path\\to\\ffmpeg.exe"` trong `[app]`.
- **Tải mô hình Whisper thất bại** (khi `subtitle_provider = "whisper"`): tải
  `Systran/faster-whisper-large-v3` từ Hugging Face, đặt vào `models/whisper-large-v3/`
  (có `config.json`, `model.bin`, `tokenizer.json`...). Có thể dùng mô hình nhỏ hơn bằng
  `[whisper] model_size = "large-v3-turbo"`.
- **Bot không trả lời**: kiểm tra `bot_token`, `[telegram] proxy`, và chỉ có một tiến trình bot.
  Lỗi kết nối chỉ hiện ở cửa sổ console của bot.
- **Đăng bài báo "Chưa đăng nhập"**: chạy lại bước đăng nhập lần đầu. Lỗi khác: xem ảnh trong
  `storage/social/screenshots`. Nếu trình duyệt đăng bài không mở được cổng điều khiển, đóng các cửa
  sổ Chrome đang dùng profile `storage/social/browser_profile` rồi thử lại.
- **WebUI trống**: dùng Chrome hoặc Edge.

## Giấy phép

MIT – xem [`LICENSE`](LICENSE). Mã nguồn gốc © 2024 Harry, dự án MoneyPrinterTurbo
(https://github.com/harry0703/MoneyPrinterTurbo).
