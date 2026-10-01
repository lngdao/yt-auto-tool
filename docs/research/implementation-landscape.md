# Nghiên cứu lựa chọn triển khai

Ngày nghiên cứu: 2026-09-28  
Phạm vi: lấy tư liệu, phụ đề, render video, thumbnail OCR, đóng gói cho Windows/macOS và so sánh tốc độ xuất.

## Kết luận ngắn

- Workflow video phù hợp với `yt-dlp` lấy audio-only/thumbnail/subtitle và FFmpeg ghép video nền, scale/crop, burn caption, rồi mã hóa đầu ra. Các công cụ này cung cấp API tiến độ để theo dõi từng job.[yt-dlp README](https://github.com/yt-dlp/yt-dlp/blob/master/README.md) · [FFmpeg CLI documentation](https://ffmpeg.org/ffmpeg.html) · [FFmpeg filters documentation](https://ffmpeg.org/ffmpeg-filters.html)
- Với subtitle, chọn track thủ công trước, sau đó thử track tự tạo theo ngôn ngữ đã cấu hình; Whisper là fallback tùy chọn khi YouTube không có track phù hợp. Đây là chính sách của ứng dụng: yt-dlp cho phép lấy và phân biệt hai loại track, nhưng không tự quyết định chính sách dự phòng theo yêu cầu sản phẩm.[yt-dlp subtitle options](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#subtitle-options) · [YouTube extractor source](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_video.py) · [OpenAI Whisper](https://github.com/openai/whisper)
- Thumbnail tự động nên tải và OCR **ảnh thumbnail YouTube**, cho người dùng sửa text OCR, rồi vẽ lại text trên preset nền/font được phân bổ cho job. Nếu thay toàn bộ nền solid/gradient thì không cần xóa chữ khỏi ảnh gốc bằng inpainting; giữ ảnh gốc làm asset tham chiếu và dùng chế độ manual khi OCR không đáng tin hoặc thumbnail có artwork cần giữ.[yt-dlp thumbnail options](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#thumbnail-options) · [Tesseract OCR output](https://github.com/tesseract-ocr/tesseract/blob/main/doc/tesseract.1.asc)
- Do cần hộp thoại chọn file, dùng các chương trình phụ và hướng đến cả Windows/macOS, **Tauri v2 + giao diện React/TypeScript** là hướng hợp lý hơn để đóng gói bản desktop. Có thể bắt đầu bằng local web trong lúc phát triển, nhưng cần một local worker; Tauri có API chính thức cho native dialog, filesystem scope và sidecar trên cả Windows lẫn macOS.[Tauri dialog](https://v2.tauri.app/plugin/dialog/) · [Tauri shell](https://v2.tauri.app/plugin/shell/) · [Tauri sidecars](https://v2.tauri.app/develop/sidecar/)
- Không có tài liệu chính thức nào kết luận FFmpeg luôn nhanh hơn Media Encoder hoặc ngược lại. Cả hai có đường dùng hardware encoding tùy máy/thiết lập; cần benchmark cùng clip và cùng cấu hình đầu ra trên máy mục tiêu.[Adobe export settings](https://helpx.adobe.com/media-encoder/desktop/encoding-and-exporting/export-settings-reference.html) · [FFmpeg VideoToolbox encoder source](https://ffmpeg.org/doxygen/8.0/videotoolboxenc_8c_source.html) · [FFmpeg benchmark options](https://ffmpeg.org/ffmpeg.html)

## 1. Tải audio, thumbnail và subtitle

### Audio

yt-dlp có format selector `bestaudio`/`ba` để tải format chỉ có audio. Nếu cần chuyển file sang định dạng audio khác, tùy chọn `-x` (`--extract-audio`) cần `ffmpeg` và `ffprobe`; tài liệu nêu các output format gồm AAC, M4A, MP3, Opus và WAV.[yt-dlp format selection](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#format-selection) · [yt-dlp post-processing options](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#post-processing-options)

**Khuyến nghị:** dùng audio-only selector làm mặc định vì video hình YouTube không tham gia thành phẩm. Chỉ chuyển audio khi cần chuẩn hóa codec/container cho MP4 cuối; lưu nguyên audio tải về để retry render mà không tải lại URL.

### Subtitle và thứ tự fallback

yt-dlp có các tùy chọn riêng để tải subtitle do người đăng cung cấp (`--write-subs`) và subtitle tự tạo (`--write-auto-subs`), liệt kê track (`--list-subs`), giới hạn ngôn ngữ (`--sub-langs`) và chọn định dạng ưu tiên (`--sub-format`). yt-dlp cũng có thể convert phụ đề giữa ASS, LRC, SRT và VTT.[yt-dlp subtitle options](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#subtitle-options) · [yt-dlp subtitle conversion options](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#post-processing-options)

Trong metadata của YouTube extractor, yt-dlp giữ `subtitles` và `automatic_captions` thành hai tập riêng; API cho phép lấy metadata trước khi tải bằng `extract_info(..., download=False)`. Vì vậy worker có thể kiểm tra track trước, rồi áp dụng thứ tự ưu tiên theo cấu hình kênh thay vì tải video đầy đủ để thử.[YouTube extractor source](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_video.py) · [yt-dlp embedding/API examples](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#embedding-yt-dlp)

Thứ tự đề xuất: (1) track thủ công khớp ngôn ngữ ưu tiên, (2) track tự tạo khớp ngôn ngữ ưu tiên, (3) Whisper tùy chọn nếu bật, (4) chuyển job sang cần xử lý nếu không có track. Hiển thị subtitle nhận được và ngôn ngữ trên từng job để người dùng xác nhận. Thứ tự này là quyết định sản phẩm; các cờ yt-dlp cho phép tải từng loại, nhưng không phải một cơ chế bảo đảm track luôn tồn tại hoặc chất lượng luôn đạt yêu cầu.[yt-dlp subtitle options](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#subtitle-options)

Whisper nhận đường dẫn audio để transcribe, trả kết quả theo các segment, và có thể chạy như thư viện Python hoặc CLI. Nó phù hợp làm fallback có thể tắt; đặc tả vẫn nên yêu cầu preview/sửa transcript vì kết quả nhận dạng là text do mô hình suy ra, không phải track subtitle đã được tác giả cung cấp.[OpenAI Whisper README](https://github.com/openai/whisper/blob/main/README.md) · [Whisper transcription implementation](https://github.com/openai/whisper/blob/main/whisper/transcribe.py)

### Lưu và theo dõi asset

`--write-thumbnail` tải ảnh thumbnail ra file và mặc định tắt; do đó cả chế độ manual lẫn auto có thể chủ động yêu cầu ảnh nguồn, còn chế độ skip có thể không tạo job thumbnail. yt-dlp hỗ trợ đường dẫn/output template riêng cho thumbnail và subtitle.[yt-dlp thumbnail options](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#thumbnail-options) · [yt-dlp output paths and templates](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#output-template)

**Khuyến nghị:** giữ file thumbnail tải về làm ảnh nguồn bất biến. Chế độ manual chỉ đưa ảnh đó vào thư mục job, không thay đổi hoặc tạo ảnh mới; chế độ skip không tải; chế độ auto tải ảnh, OCR, cho sửa nội dung, rồi xuất biến thể mới.

## 2. Thumbnail từ ảnh nguồn: OCR, preset và xử lý lỗi

### Pipeline đề xuất

1. Tải thumbnail YouTube bằng yt-dlp.
2. Chạy Tesseract với ngôn ngữ OCR cấu hình theo kênh; đầu ra TSV/hOCR chứa từ nhận dạng, tọa độ bounding box và confidence. Tesseract cho phép chọn nhiều ngôn ngữ và mặc định dùng `eng` nếu không truyền ngôn ngữ.[Tesseract manual](https://github.com/tesseract-ocr/tesseract/blob/main/doc/tesseract.1.asc) · [Tesseract TSV documentation](https://github.com/tesseract-ocr/tessdoc/blob/main/Command-Line-Usage.md#tsv-output)
3. Ghép từ thành các dòng, đặt text vào editor đơn giản để người dùng sửa lỗi OCR, line break và thứ tự dòng.
4. Gán preset thumbnail cho job theo pool đã chọn ở cấp toàn cục, nhóm kênh, kênh hoặc override job; preset gồm nền solid/gradient, font, màu, outline/shadow, căn lề và bố cục.
5. Render PNG từ template SVG; preview ảnh cạnh ảnh nguồn và cho phép xuất lại sau khi sửa.

Tesseract nhận dạng ký tự và hộp chữ, nhưng không khôi phục chắc chắn thiết kế typography gốc hoặc biết ý nghĩa/ưu tiên của từng dòng. Vì vậy UI nên dùng text OCR làm dữ liệu khởi đầu, không tự coi đó là bản thumbnail đã đúng.[Tesseract manual](https://github.com/tesseract-ocr/tesseract/blob/main/doc/tesseract.1.asc) · [Tesseract iterator API](https://github.com/tesseract-ocr/tesseract/blob/main/include/tesseract/ltrresultiterator.h)

### Có nên inpaint ảnh gốc?

Nếu preset thay toàn bộ background, hãy vẽ nền preset mới và đè text OCR đã sửa lên; không cần xóa chữ cũ khỏi ảnh nguồn. Cách này tránh để lại viền/halo của chữ cũ và không cần tái tạo gradient gốc. Đây là khuyến nghị dựa trên workflow đã mô tả.

Nếu cần giữ nguyên artwork/ảnh nền nguồn rồi chỉ thay chữ, OpenCV `inpaint` có thể lấp vùng được đánh dấu bằng mask dựa trên lân cận vùng đó; API có phương pháp Navier–Stokes và Telea. Theo giới hạn của phương pháp này, nền có texture, artwork chạy xuyên qua chữ hoặc vùng chữ lớn có thể tái tạo không đúng; nếu ảnh chỉ là màu trơn/gradient thì phương án render nền sạch mới thường dễ kiểm soát hơn. Đánh giá chất lượng trên ảnh thật vẫn cần review.[OpenCV inpaint API](https://docs.opencv.org/4.5.2/d7/d8b/group__photo__inpaint.html)

**Review bắt buộc trước export** khi OCR không ra text, confidence thấp, text bị cắt/che/đè nhiều dòng, OCR trả thứ tự dòng khó hiểu, hoặc source thumbnail có logo/artwork mà preset nền mới sẽ loại bỏ. Tesseract xuất confidence trên từng từ; ngưỡng tự chấp nhận cần hiệu chỉnh bằng một tập thumbnail đại diện, không có ngưỡng chung được tài liệu bảo đảm.[Tesseract TSV documentation](https://github.com/tesseract-ocr/tessdoc/blob/main/Command-Line-Usage.md#tsv-output)

### Thư viện render

[resvg-js](https://github.com/thx/resvg-js) chuyển SVG thành PNG, hỗ trợ system/custom fonts và ví dụ nạp font từ file. Đây là lựa chọn phù hợp để SVG template làm định dạng preset chuẩn và xuất PNG; README cũng mô tả browser/WASM build nếu muốn thử dùng cùng mô hình SVG cho preview.[resvg-js README](https://github.com/thx/resvg-js)

[Sharp](https://sharp.pixelplumbing.com/) nhận SVG và hỗ trợ resize/crop/composite ảnh; nên xem là thư viện xử lý raster bổ sung, không phải editor/preset workflow. Recommendation: bắt đầu với SVG + resvg-js; thêm Sharp khi cần ghép/crop/resize ảnh raster.[Sharp constructor](https://sharp.pixelplumbing.com/api-constructor/) · [Sharp output](https://sharp.pixelplumbing.com/api-output/) · [Sharp composite](https://sharp.pixelplumbing.com/api-composite/)

Không thư viện nào trong hai thư viện trên tự cung cấp UI quản lý pool preset, OCR, phân bổ preset theo job hoặc luồng review; các phần đó thuộc ứng dụng.[resvg-js README](https://github.com/thx/resvg-js) · [Sharp API docs](https://sharp.pixelplumbing.com/)

## 3. Pipeline FFmpeg

FFmpeg CLI có `-stream_loop -1` để loop input video vô hạn. `-shortest` kết thúc encode khi output stream ngắn nhất kết thúc; nếu video nền được loop vô hạn và audio hữu hạn, đây là cơ chế phù hợp để output theo thời lượng audio. Dùng `-map` tường minh để chọn hình từ input nền và audio từ input audio, tránh auto-selection chọn nhầm stream khi thêm input.[FFmpeg input options](https://ffmpeg.org/ffmpeg.html) · [FFmpeg stream mapping](https://ffmpeg.org/ffmpeg.html#Advanced-options)

Scale/crop có thể tạo khung cố định **1280×720** bằng scale giữ tỉ lệ với `force_original_aspect_ratio=increase`, sau đó crop đúng kích thước. Kiểu `increase` lấp đầy khung nhưng cắt phần thừa; tùy chọn `decrease` giữ toàn bộ hình nhưng có thể cần pad. Vì asset nguồn có thể dọc hoặc khác aspect ratio, UI nên cho chọn fill/crop hoặc contain/pad, và preview crop trước khi render.[FFmpeg scale filter](https://ffmpeg.org/ffmpeg-filters.html#scale)

`subtitles` filter đốt phụ đề lên hình qua libass; FFmpeg build phải có `--enable-libass`. Filter đọc SRT và chuyển nội bộ sang ASS; `force_style` nhận cặp `KEY=VALUE` kiểu ASS, còn `fontsdir` chỉ định thư mục font bổ sung. Có thể lưu SRT gốc riêng, rồi render từ SRT/ASS đã chuẩn hóa style; nếu preview phải sát output thì nên kiểm tra một frame bằng cùng libass/font thay vì giả định CSS trình duyệt giống hoàn toàn.[FFmpeg subtitles filter](https://ffmpeg.org/ffmpeg-filters.html#subtitles-1) · [FFmpeg subtitle filter source](https://ffmpeg.org/doxygen/8.1/vf__subtitles_8c_source.html)

FFmpeg hỗ trợ `-progress pipe:1`, xuất các dòng `key=value` có chu kỳ và kết thúc mỗi nhóm bằng `progress=continue` hoặc `progress=end`; `-stats_period` điều khiển chu kỳ cập nhật. yt-dlp Python API có `progress_hooks`, và README khuyên không phụ thuộc vào việc parse stdout mặc định vì định dạng có thể đổi.[FFmpeg progress options](https://ffmpeg.org/ffmpeg.html) · [yt-dlp progress hooks](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#adding-logger-and-progress-hook) · [yt-dlp embedding guidance](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#embedding-yt-dlp)

FFmpeg source khai báo encoder `h264_videotoolbox` cho H.264 qua VideoToolbox; khả năng sử dụng thực tế tùy binary FFmpeg được cài/đóng gói và máy. Detect encoder lúc khởi động, không hard-code rằng mọi bản FFmpeg macOS đều có encoder này.[FFmpeg VideoToolbox encoder source](https://ffmpeg.org/doxygen/8.0/videotoolboxenc_8c_source.html) · [FFmpeg hardware acceleration options](https://ffmpeg.org/ffmpeg.html)

## 4. Local worker và job queue

Python `asyncio.create_subprocess_exec(program, *args, ...)` tạo subprocess và trả object để theo dõi stdout/stderr/hoàn tất; Python cảnh báo nếu chạy qua shell thì ứng dụng chịu trách nhiệm quote để tránh shell injection. Với worker local, dùng argv riêng cho từng command thay vì dựng chuỗi shell, ghi nhận trạng thái và exit code theo job, đọc progress hook của yt-dlp và progress stream của FFmpeg.[Python asyncio subprocess docs](https://docs.python.org/3/library/asyncio-subprocess.html)

Khuyến nghị chạy từng job qua worker có trạng thái riêng: `metadata → assets → subtitle review → render → thumbnail → done/error`; snapshot video nền/preset/output trước khi chạy để retry không đổi lựa chọn. Bắt đầu với một render FFmpeg đồng thời, sau đó đo rồi mới cho cấu hình concurrency, vì nhiều encode cùng lúc có thể tranh CPU/GPU/disk. Đây là khuyến nghị thiết kế; tài liệu Python chỉ cung cấp primitive subprocess/concurrency, không định nghĩa queue sản phẩm.

## 5. Local web hay Tauri cho Windows + macOS?

| Hạng mục | Local web | Tauri v2 |
|---|---|---|
| UI | React/TypeScript chạy trong browser; thuận tiện phát triển | Có thể giữ cùng UI web trong WebView desktop |
| Chọn file/thư mục | File System Access API dùng picker và yêu cầu tương tác/permission; API này là proposal WICG, không nên giả định có mặt đồng nhất trong mọi browser. Safari/WebKit hỗ trợ Origin Private File System nhưng issue của WebKit nói các picker `showOpenFilePicker`/`showSaveFilePicker`/`showDirectoryPicker` không nằm trong kế hoạch của WebKit. `input type=file` và download là fallback cơ bản nhưng kém phù hợp cho thư viện video lớn/output theo thư mục.[WICG spec](https://wicg.github.io/file-system-access/) · [Chrome File System Access docs](https://developer.chrome.com/docs/capabilities/web-apis/file-system-access) · [WebKit issue 231706](https://bugs.webkit.org/show_bug.cgi?id=231706) · [WebKit OPFS docs](https://webkit.org/blog/12257/the-file-system-access-api-with-origin-private-file-system/) | Dialog plugin trả path file/thư mục trên Windows và macOS; filesystem plugin có scope để giới hạn đường dẫn được đọc/ghi. Scope cần cấu hình rõ cho thư mục asset/output của người dùng.[Tauri dialog](https://v2.tauri.app/plugin/dialog/) · [Tauri filesystem](https://v2.tauri.app/plugin/file-system/) |
| Chạy yt-dlp/FFmpeg | Browser không tự chạy executable của máy; cần Python/Rust local backend hoặc helper service. Python subprocess API phù hợp cho backend local.[Python asyncio subprocess docs](https://docs.python.org/3/library/asyncio-subprocess.html) | Shell plugin spawn process/sidecar trên Windows và macOS; Tauri yêu cầu capability scope quy định binary/arguments được phép.[Tauri shell](https://v2.tauri.app/plugin/shell/) |
| Đóng gói | Nếu phát cho máy khác vẫn phải cài hoặc bundle backend và media tools; UI-only không thay thế worker. | Tauri hỗ trợ sidecar bằng `externalBin`; sidecar có thể là Python API/CLI đã bundle bằng PyInstaller. Cần artifact riêng theo target triple/OS/architecture cho từng binary.[Tauri sidecar guide](https://v2.tauri.app/develop/sidecar/) · [Tauri externalBin config](https://v2.tauri.app/reference/config/#bundleconfig) |
| Runtime UI | Phụ thuộc browser mà người dùng mở | Tauri dùng WebView2 trên Windows và WKWebView trên macOS; WebView2 runtime được xử lý bởi installer trong phiên bản Windows cũ, còn macOS dùng WebKit hệ thống.[Tauri WebView versions](https://v2.tauri.app/reference/webview-versions/) |

**Khuyến nghị:** nếu mục tiêu là cài app riêng trên cả Windows và macOS, dùng Tauri v2 cho native picker/worker lifecycle, React cho UI, và Python worker đóng gói thành sidecar nếu muốn giữ Python orchestration. Bundle `yt-dlp`, `ffmpeg`, `ffprobe` theo từng target; Whisper có thể là dependency tùy chọn để giảm độ phức tạp và kích thước của MVP. Tauri yêu cầu sidecar khớp target triple, ví dụ Windows x64 và macOS Apple Silicon/Intel cần artifact tương ứng.[Tauri sidecar guide](https://v2.tauri.app/develop/sidecar/) · [Tauri config externalBin](https://v2.tauri.app/reference/config/#bundleconfig)

Tauri không làm biến mất khác biệt hệ điều hành: build/release cần artifact Windows và macOS; khi phân phối bên ngoài, Tauri ghi rõ macOS cần code signing/notarization để tránh cảnh báo hệ thống, còn Windows có thể hiện SmartScreen warning cho app chưa có reputation/signature phù hợp. Có thể hoãn ký app nếu chỉ chạy nội bộ trong giai đoạn phát triển.[Tauri macOS signing](https://v2.tauri.app/distribute/sign/macos/) · [Tauri Windows signing](https://v2.tauri.app/distribute/sign/windows/)

Local web vẫn là lựa chọn tốt để prototype nhanh UI/preset và chạy backend từ source trên một máy. Nhưng nếu chọn để dùng lâu dài trên Safari/macOS, đừng dựa vào File System Access picker của browser; cần để worker mở picker native hoặc chuyển sang Tauri. Đây là suy luận từ giới hạn picker của WebKit và các API native của Tauri.[WebKit issue 231706](https://bugs.webkit.org/show_bug.cgi?id=231706) · [Tauri dialog](https://v2.tauri.app/plugin/dialog/)

## 6. FFmpeg so với Adobe Media Encoder

Adobe hiện ghi H.264/HEVC dùng Hardware Accelerated làm lựa chọn mặc định khi khả dụng; nếu cấu hình máy không hỗ trợ một số tùy chọn export, Media Encoder chuyển sang Software Only. FFmpeg có encoder H.264 VideoToolbox trên Apple platforms khi binary/build hỗ trợ.[Adobe export settings](https://helpx.adobe.com/media-encoder/desktop/encoding-and-exporting/export-settings-reference.html) · [FFmpeg VideoToolbox encoder source](https://ffmpeg.org/doxygen/8.0/videotoolboxenc_8c_source.html)

Các tài liệu này chứng minh có đường hardware encoding, không đưa ra benchmark so sánh FFmpeg và Media Encoder. Với workflow này, tổng thời gian còn gồm loop/decode, scale/crop, burn subtitle và audio encode; tên hardware encoder riêng lẻ không đủ để kết luận tốc độ toàn pipeline. Đây là suy luận từ các bước filter và encoder độc lập trong FFmpeg.[FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html) · [FFmpeg codecs](https://ffmpeg.org/ffmpeg-codecs.html)

So sánh trên máy mục tiêu bằng clip giống nhau: cùng nền/audio, thời lượng, frame rate, H.264, 1280×720, chất lượng/bitrate gần nhau, font/subtitle style, audio settings, và trạng thái hardware acceleration tương đương. FFmpeg `-benchmark` ghi real/system/user time và mức RAM tối đa nếu được hỗ trợ; với Media Encoder đo wall-clock theo cùng quy trình và kiểm tra output nhìn/nghe tương đương. Không dùng kết quả từ một cấu hình làm khẳng định chung cho máy khác.[FFmpeg benchmark options](https://ffmpeg.org/ffmpeg.html) · [Adobe export settings](https://helpx.adobe.com/media-encoder/desktop/encoding-and-exporting/export-settings-reference.html)

## 7. Quyết định đề xuất và câu hỏi còn mở

### Đề xuất cho MVP

1. Frontend React/TypeScript; Tauri v2 làm app shell khi bắt đầu hướng Windows/macOS.
2. Python worker có job state cục bộ; gọi yt-dlp/FFmpeg qua subprocess argv, đọc progress API, giữ log/asset theo từng job.[Tauri sidecar guide](https://v2.tauri.app/develop/sidecar/) · [Python asyncio subprocess docs](https://docs.python.org/3/library/asyncio-subprocess.html)
3. Download audio-only; lấy `--list-subs`/metadata để chọn subtitle thủ công rồi auto; cho bật Whisper fallback theo kênh. Giữ SRT nguồn cho sửa/chuyển preset.[yt-dlp format selection](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#format-selection) · [yt-dlp subtitle options](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#subtitle-options)
4. Render FFmpeg 1280×720 mặc định, chọn `fill/crop` hoặc `contain/pad`, burn subtitle bằng libass/ASS, map audio rõ ràng và dừng output theo audio.[FFmpeg CLI](https://ffmpeg.org/ffmpeg.html) · [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html)
5. Thumbnail auto: ảnh nguồn → OCR + confidence/box → sửa text → preset group được phân bổ cho từng job → SVG/resvg-js PNG. Có mode manual lưu thumbnail gốc, mode skip, và review bắt buộc khi OCR khó.[Tesseract TSV](https://github.com/tesseract-ocr/tessdoc/blob/main/Command-Line-Usage.md#tsv-output) · [resvg-js](https://github.com/thx/resvg-js)

### Cần chốt khi chuyển sang implementation

- Ngôn ngữ subtitle ưu tiên và quy tắc chọn một track khi có nhiều track cùng ngôn ngữ.
- Whisper bật mặc định hay opt-in, model/lang nào; nếu không có caption thì cho render không caption hay dừng chờ người dùng.
- Output FPS, codec/quality preset, audio codec/bitrate, và chính sách frame rate khi asset nền khác nhau.
- Thumbnail auto luôn thay cả nền bằng preset hay có lựa chọn giữ artwork nguồn; preset nhóm xoay vòng/trộn đều như nền video.
- Ngưỡng confidence OCR và trường hợp yêu cầu user sửa tay; cần tập ảnh thật từ các kênh để đo trước.
- Phạm vi phát hành: chỉ chạy source nội bộ hay cần installer dễ cài; target kiến trúc nào trên Windows và macOS, có cần ký/notarize bản chia sẻ hay không.
