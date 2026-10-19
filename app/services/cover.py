"""
Tạo ảnh cover cho video: khung hình lấy từ chính video, phủ gradient tối và
tiêu đề chữ lớn ở giữa khung (vùng an toàn, không bị giao diện TikTok/Reels che).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile

from loguru import logger
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

from app.services import video as video_service
from app.utils import utils

ACCENT_COLOR = (255, 200, 61)
TEXT_COLOR = (255, 255, 255)
SHADOW_COLOR = (0, 0, 0)
MAX_TITLE_LINES = 4


def _font_path(name: str) -> str:
    return os.path.join(utils.font_dir(), name)


def _extract_frame(video_path: str, at_seconds: float, output_path: str) -> bool:
    result = subprocess.run(
        [
            video_service.get_ffmpeg_binary(), "-hide_banner", "-y",
            "-ss", f"{at_seconds:.2f}", "-i", video_path,
            "-frames:v", "1", "-q:v", "2", output_path,
        ],
        capture_output=True,
    )
    return result.returncode == 0 and os.path.exists(output_path)


def _probe(video_path: str) -> tuple[int, int, float]:
    """(rộng, cao, thời lượng) đọc từ đầu ra của ffmpeg -i."""
    result = subprocess.run(
        [video_service.get_ffmpeg_binary(), "-hide_banner", "-i", video_path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    duration_match = re.search(r"Duration: (\d+):(\d+):([\d.]+)", result.stderr)
    size_match = re.search(r"Video: [^\n]*?, (\d{2,5})x(\d{2,5})", result.stderr)
    duration = 0.0
    if duration_match:
        hours, minutes, seconds = duration_match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    width, height = (int(size_match[1]), int(size_match[2])) if size_match else (0, 0)
    return width, height, duration


def _subtitle_gaps(subtitle_path: str, limit: int = 8) -> list[float]:
    """Thời điểm giữa hai câu phụ đề, nơi khung hình không có chữ."""
    def to_seconds(value: str) -> float:
        hours, minutes, rest = value.replace(",", ".").split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(rest)

    try:
        with open(subtitle_path, encoding="utf-8") as file:
            cues = re.findall(
                r"(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)", file.read()
            )
    except OSError:
        return []
    spans = [(to_seconds(start), to_seconds(end)) for start, end in cues]
    gaps = []
    for (_, previous_end), (next_start, _) in zip(spans, spans[1:]):
        if next_start - previous_end >= 0.08:
            gaps.append((previous_end + next_start) / 2)
    if spans and spans[0][0] >= 0.5:
        gaps.insert(0, spans[0][0] / 2)
    step = max(len(gaps) // limit, 1)
    return gaps[::step][:limit]


def _frame_score(image: Image.Image) -> float:
    """Ưu tiên khung hình có màu, có tương phản, không quá sáng hay quá tối."""
    small = image.resize((160, int(160 * image.height / image.width)))
    luminance = ImageStat.Stat(small.convert("L"))
    saturation = ImageStat.Stat(small.convert("HSV").getchannel("S")).mean[0]
    brightness = luminance.mean[0]
    score = luminance.stddev[0] + saturation * 0.6
    if brightness > 200 or brightness < 35:
        score *= 0.4
    return score


def _best_frame(
    video_path: str,
    sources: list[str] | None,
    subtitle_path: str | None,
    temp_dir: str,
) -> Image.Image | None:
    candidates: list[tuple[str, float]] = []
    sources = (sources or [])[:8]
    if len(sources) == 1:
        # Một video duy nhất (ví dụ combined-N.mp4 chưa có phụ đề): lấy nhiều thời điểm.
        _, _, duration = _probe(sources[0])
        candidates = [
            (sources[0], duration * ratio) for ratio in (0.08, 0.2, 0.35, 0.5, 0.65, 0.8)
        ]
    for source in sources if len(sources) > 1 else []:
        _, _, duration = _probe(source)
        candidates.append((source, min(max(duration * 0.4, 0.5), 4.0)))
    if not candidates and subtitle_path:
        candidates = [(video_path, t) for t in _subtitle_gaps(subtitle_path)]
    if not candidates:
        _, _, duration = _probe(video_path)
        candidates = [(video_path, duration * ratio) for ratio in (0.1, 0.3, 0.5, 0.7)]

    best, best_score = None, -1.0
    for index, (path, at_seconds) in enumerate(candidates):
        frame_path = os.path.join(temp_dir, f"frame-{index}.jpg")
        # Ảnh tĩnh (footage của người dùng) chỉ có khung hình ở thời điểm 0.
        if not _extract_frame(path, at_seconds, frame_path) and not _extract_frame(
            path, 0, frame_path
        ):
            continue
        image = Image.open(frame_path).convert("RGB")
        image.load()
        score = _frame_score(image)
        if score > best_score:
            best, best_score = image, score
    return best


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if not current or draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _balanced_wrap(draw, text: str, font, max_width: int) -> list[str]:
    """Giữ nguyên số dòng nhưng thu hẹp bề rộng để các dòng dài gần bằng nhau."""
    lines = _wrap(draw, text, font, max_width)
    low, high = int(max_width * 0.4), max_width
    while low < high:
        middle = (low + high) // 2
        if len(_wrap(draw, text, font, middle)) <= len(lines):
            high = middle
        else:
            low = middle + 1
    return _wrap(draw, text, font, high)


def _fit_title(draw, title: str, max_width: int, max_height: int, start_size: int):
    """Giảm cỡ chữ đến khi tiêu đề vừa tối đa MAX_TITLE_LINES dòng trong khung."""
    size = start_size
    while True:
        font = ImageFont.truetype(_font_path("BeVietnamPro-Bold.ttf"), size)
        lines = _balanced_wrap(draw, title, font, max_width)
        line_height = int(size * 1.18)
        fits_width = all(draw.textlength(line, font=font) <= max_width for line in lines)
        if (
            fits_width
            and len(lines) <= MAX_TITLE_LINES
            and line_height * len(lines) <= max_height
        ) or size <= 36:
            return font, lines, line_height
        size = int(size * 0.92)


def _cover_crop(image: Image.Image, width: int, height: int) -> Image.Image:
    scale = max(width / image.width, height / image.height)
    resized = image.resize(
        (round(image.width * scale), round(image.height * scale)), Image.LANCZOS
    )
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def _gradient_overlay(width: int, height: int) -> Image.Image:
    """Lớp tối dần từ trên xuống, đậm nhất quanh vùng tiêu đề và đáy ảnh."""
    mask = Image.new("L", (1, height))
    for y in range(height):
        ratio = y / height
        if ratio < 0.25:
            alpha = 70
        elif ratio < 0.45:
            alpha = 70 + int((ratio - 0.25) / 0.20 * 110)
        else:
            alpha = 180 + int((ratio - 0.45) / 0.55 * 50)
        mask.putpixel((0, y), alpha)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay.putalpha(mask.resize((width, height)))
    return overlay


def create_cover(
    video_path: str,
    title: str,
    output_path: str,
    label: str = "",
    sources: list[str] | None = None,
    subtitle_path: str | None = None,
) -> str | None:
    """
    Tạo cover JPG cho ``video_path``; trả về đường dẫn hoặc None nếu lỗi.

    ``sources`` là footage gốc (chưa có phụ đề) để chọn khung hình. Nếu không có,
    khung hình lấy từ video thành phẩm ở khoảng lặng giữa các câu trong
    ``subtitle_path`` để tránh dính chữ phụ đề.
    """
    title = " ".join((title or "").split())
    if not title:
        return None
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            frame = _best_frame(video_path, sources, subtitle_path, temp_dir)
        if frame is None:
            logger.warning(f"cover: cannot extract frame from {video_path}")
            return None

        width, height, _ = _probe(video_path)
        if not width or not height:
            width, height = frame.size
        canvas = _cover_crop(frame, width, height).convert("RGBA")
        canvas = Image.alpha_composite(canvas, _gradient_overlay(width, height))

        margin = int(width * 0.08)
        max_text_width = width - margin * 2
        portrait = height > width
        title_text = title.upper()
        draw = ImageDraw.Draw(canvas)
        font, lines, line_height = _fit_title(
            draw,
            title_text,
            max_text_width,
            int(height * (0.34 if portrait else 0.45)),
            start_size=int(width * (0.115 if portrait else 0.075)),
        )

        label_font = ImageFont.truetype(
            _font_path("BeVietnamPro-Medium.ttf"), max(int(font.size * 0.42), 24)
        )
        label_text = (label or "").upper()
        label_height = int(label_font.size * 1.6) if label_text else 0
        bar_height = max(int(font.size * 0.09), 6)
        block_height = label_height + line_height * len(lines) + bar_height * 3
        top = int(height * (0.56 if portrait else 0.5)) - block_height // 2

        # Bóng chữ mờ để tiêu đề nổi trên mọi nền.
        shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        text_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        text_draw = ImageDraw.Draw(text_layer)

        y = top
        if label_text:
            # Nhãn dạng viên thuốc nền vàng, chữ tối: luôn đọc được trên nền rối.
            label_width = text_draw.textlength(label_text, font=label_font)
            pad_x, pad_y = label_font.size * 0.8, label_font.size * 0.35
            x = (width - label_width) / 2
            _, text_top, _, text_bottom = text_draw.textbbox((x, y), label_text, font=label_font)
            text_draw.rounded_rectangle(
                (x - pad_x, text_top - pad_y, x + label_width + pad_x, text_bottom + pad_y),
                radius=int((text_bottom - text_top) / 2 + pad_y),
                fill=ACCENT_COLOR,
            )
            text_draw.text((x, y), label_text, font=label_font, fill=(25, 25, 25))
            y += label_height + int(pad_y * 2)

        offset = max(int(font.size * 0.05), 3)
        for line in lines:
            line_width = text_draw.textlength(line, font=font)
            x = (width - line_width) / 2
            shadow_draw.text((x + offset, y + offset), line, font=font, fill=SHADOW_COLOR + (200,))
            text_draw.text(
                (x, y), line, font=font, fill=TEXT_COLOR,
                stroke_width=max(int(font.size * 0.03), 2), stroke_fill=SHADOW_COLOR,
            )
            y += line_height

        bar_width = int(width * 0.18)
        bar_top = y + bar_height
        text_draw.rounded_rectangle(
            ((width - bar_width) / 2, bar_top, (width + bar_width) / 2, bar_top + bar_height),
            radius=bar_height // 2,
            fill=ACCENT_COLOR,
        )

        shadow = shadow.filter(ImageFilter.GaussianBlur(max(int(font.size * 0.08), 4)))
        canvas = Image.alpha_composite(canvas, shadow)
        canvas = Image.alpha_composite(canvas, text_layer)
        canvas.convert("RGB").save(output_path, "JPEG", quality=92)
        return output_path
    except Exception as exc:
        logger.warning(f"cover: failed to create cover for {video_path}: {exc}")
        return None


def _audio_format(video_path: str) -> tuple[int, str] | None:
    """(sample rate, channel layout) của track âm thanh, None nếu video không có tiếng."""
    result = subprocess.run(
        [video_service.get_ffmpeg_binary(), "-hide_banner", "-i", video_path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    match = re.search(r"Audio: [^,]+, (\d+) Hz, (mono|stereo)", result.stderr)
    return (int(match[1]), match[2]) if match else None


def leading_dark_seconds(video_path: str, max_seconds: float = 3.0) -> float:
    """Độ dài đoạn đen/tối ngay đầu video (ví dụ hiệu ứng fade từ màu đen), 0 nếu không có."""
    result = subprocess.run(
        [
            video_service.get_ffmpeg_binary(), "-hide_banner", "-t", f"{max_seconds}",
            "-i", video_path, "-vf", "blackdetect=d=0.02:pix_th=0.20:pic_th=0.90",
            "-an", "-f", "null", "-",
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    match = re.search(r"black_start:([\d.]+) black_end:([\d.]+)", result.stderr)
    if match and float(match[1]) <= 0.05:
        return float(match[2])
    return 0.0


def black_segments(video_path: str) -> list[tuple[float, float]]:
    """Các đoạn gần như đen hoàn toàn trong video, dạng (bắt đầu, kết thúc) theo giây."""
    result = subprocess.run(
        [
            video_service.get_ffmpeg_binary(), "-hide_banner", "-i", video_path,
            "-vf", "blackdetect=d=0.02:pix_th=0.10", "-an", "-f", "null", "-",
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return [
        (float(start), float(end))
        for start, end in re.findall(
            r"black_start:([\d.]+) black_end:([\d.]+)", result.stderr
        )
    ]


def _freeze_black_frames(
    segments: list[tuple[float, float]],
    after: float,
    duration: float,
    source: str,
    target: str,
    fps: int = 30,
) -> str:
    """
    Đoạn filtergraph từ ``[source]`` tới ``[target]`` thay mỗi đoạn đen bằng khung
    hình ngay sau nó, giữ nguyên số khung hình nên âm thanh vẫn khớp.
    freezeframes cần hai đầu vào nên luồng được split cho từng đoạn.
    """
    parts = []
    current = source
    for index, (start, end) in enumerate(segments):
        # Đoạn đen ở cuối video không có khung hình phía sau để thay thế.
        if end <= after or end >= duration - 0.1:
            continue
        first = max(int(round(max(start, after) * fps)), 0)
        last = int(round(end * fps)) - 1
        if last < first:
            continue
        parts.append(
            f"[{current}]split[fa{index}][fb{index}];"
            f"[fa{index}][fb{index}]freezeframes=first={first}:last={last}"
            f":replace={last + 1}[fz{index}]"
        )
        current = f"fz{index}"
    parts.append(f"[{current}]null[{target}]")
    return ";".join(parts)


def _run_ffmpeg(arguments: list[str], timeout: float) -> bool:
    try:
        result = subprocess.run(
            [video_service.get_ffmpeg_binary(), "-hide_banner", "-y", *arguments],
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.warning(f"cover: ffmpeg timed out after {timeout:.0f}s")
        return False
    if result.returncode != 0:
        logger.warning(f"cover: ffmpeg failed: {result.stderr[-600:]!r}")
    return result.returncode == 0


def _remove_black_frames(
    video_path: str, cover_path: str, output_path: str, scale: str, duration: float,
    timeout: float,
) -> bool:
    """
    Lượt 1: phủ cover lên đoạn tối đầu video và thay khung đen giữa video bằng
    khung hình liền sau. Chạy riêng (âm thanh copy thẳng) vì freezeframes cần đọc
    trước khung hình; nếu gộp với concat ở lượt 2, luồng âm thanh của video gốc
    bị dồn ứ trong lúc concat còn xử lý đoạn cover và ffmpeg treo vĩnh viễn.
    """
    dark_seconds = leading_dark_seconds(video_path)
    segments = black_segments(video_path)
    freeze = _freeze_black_frames(segments, dark_seconds, duration, "m0", "fixed")
    if dark_seconds <= 0 and freeze.startswith("[m0]null"):
        return False

    command = ["-i", video_path]
    graph = f"[0:v]{scale}[m0];{freeze}"
    if dark_seconds > 0:
        command += ["-loop", "1", "-framerate", "30", "-t", f"{dark_seconds + 0.1:.3f}",
                    "-i", cover_path]
        graph += (
            f";[1:v]{scale}[mask];"
            f"[fixed][mask]overlay=eof_action=pass:enable='lt(t,{dark_seconds:.3f})'[out]"
        )
        logger.info(f"cover: covering {dark_seconds:.2f}s dark start of {video_path}")
    else:
        graph += ";[fixed]null[out]"
    command += [
        "-filter_complex", graph, "-map", "[out]", "-map", "0:a?", "-c:a", "copy",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-color_range", "tv", output_path,
    ]
    return _run_ffmpeg(command, timeout)


def prepend_cover(video_path: str, cover_path: str, seconds: float) -> bool:
    """
    Ghép ảnh cover thành đoạn mở đầu dài ``seconds`` giây (âm thanh im lặng) rồi
    ghi đè ``video_path``. Nền tảng như TikTok/Reels/Telegram lấy khung hình đầu
    làm ảnh bìa mặc định. Trước đó xoá mọi khung đen (fade từ màu đen) mà vẫn giữ
    nguyên thời lượng, nên âm thanh và phụ đề vẫn khớp. Encode lại bằng concat
    filter: ghép nối kiểu copy giữa hai luồng H.264 khác thông số dễ hỏng video.
    """
    if seconds <= 0 or not os.path.exists(cover_path):
        return False
    width, height, duration = _probe(video_path)
    if not width or not height or duration <= 0:
        logger.warning(f"cover: cannot probe {video_path}, skip prepending cover")
        return False

    # Video 1 phút encode mất khoảng 20–60 giây; giới hạn rộng để không treo mãi.
    timeout = max(300.0, duration * 20)
    scale = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase:out_range=tv,"
        f"crop={width}:{height},setsar=1,fps=30,format=yuv420p"
    )
    base = os.path.splitext(video_path)[0]
    output_path = base + ".with-cover.mp4"
    temp_paths = [output_path]
    try:
        source = video_path
        # Khung thay thế có thể vẫn hơi tối (cảnh đang fade); lặp tối đa 3 lượt.
        for attempt in range(3):
            cleaned_path = f"{base}.no-black-{attempt}.mp4"
            temp_paths.append(cleaned_path)
            if not _remove_black_frames(source, cover_path, cleaned_path, scale, duration, timeout):
                break
            source = cleaned_path

        audio = _audio_format(source)
        command = [
            "-loop", "1", "-framerate", "30", "-t", f"{seconds:.3f}", "-i", cover_path,
            "-i", source,
        ]
        if audio:
            sample_rate, layout = audio
            command += [
                "-f", "lavfi", "-t", f"{seconds:.3f}",
                "-i", f"anullsrc=r={sample_rate}:cl={layout}",
            ]
            graph = (
                f"[0:v]{scale}[intro];[1:v]{scale}[main];"
                "[intro][2:a][main][1:a]concat=n=2:v=1:a=1[v][a]"
            )
            maps = ["-map", "[v]", "-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
        else:
            graph = f"[0:v]{scale}[intro];[1:v]{scale}[main];[intro][main]concat=n=2:v=1:a=0[v]"
            maps = ["-map", "[v]"]
        command += [
            "-filter_complex", graph, *maps,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-color_range", "tv",
            "-movflags", "+faststart", output_path,
        ]
        if not _run_ffmpeg(command, timeout) or not os.path.exists(output_path):
            return False

        _, _, new_duration = _probe(output_path)
        if abs(new_duration - (duration + seconds)) > 0.5:
            logger.warning(
                f"cover: unexpected duration after prepending ({new_duration:.2f}s, "
                f"expected {duration + seconds:.2f}s), keep original video"
            )
            return False
        os.replace(output_path, video_path)
        logger.info(f"cover: prepended {seconds:.1f}s cover to {video_path}")
        return True
    finally:
        for temp_path in temp_paths:
            if os.path.exists(temp_path):
                os.remove(temp_path)
