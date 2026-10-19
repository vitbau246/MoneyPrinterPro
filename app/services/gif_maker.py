"""
Ảnh động (GIF) có chữ từ clip Pixabay, không lồng tiếng.

API của Pixabay chỉ trả về ảnh tĩnh và video, không có GIF, nên ảnh động được cắt
từ đoạn video Pixabay sát nghĩa nhất với từ khoá: lấy vài giây, chèn chữ với màu
tương phản cao nhất so với nền thật của các khung hình, rồi xuất GIF lặp vô hạn.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from typing import Sequence
from uuid import uuid4

import numpy as np
import requests
from loguru import logger
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.config import config
from app.services import cover as cover_service
from app.services import material
from app.utils import utils

# Kích thước GIF theo khung hình: đủ nét trên điện thoại mà file vẫn nhẹ.
OUTPUT_SIZES = {"9:16": (480, 854), "1:1": (480, 480), "16:9": (640, 360)}
DEFAULT_ASPECT = "9:16"
GIF_SECONDS = 4.0
# Nhiều clip mở đầu bằng cảnh mờ dần từ màu đen; clip đủ dài thì bỏ qua đoạn này.
SKIP_SECONDS = 0.5
# GIF nén kém với cảnh chuyển động (clip lá rơi 4 giây: 11,9MB ở 12 hình/giây, 256
# màu). Thử lần lượt (hình/giây, số màu, tỉ lệ kích thước) đến khi dưới MAX_GIF_BYTES.
GIF_ATTEMPTS = ((10, 128, 1.0), (8, 96, 1.0), (8, 96, 0.75))
MAX_GIF_BYTES = 8 * 1024 * 1024
# Bản MP4 không tiếng để Telegram phát như ảnh động: nhẹ hơn GIF khoảng 10 lần.
PREVIEW_FPS = 24
MAX_DOWNLOAD_BYTES = 80 * 1024 * 1024
SAMPLE_FRAMES = 5
# Lấy sâu để loạt ảnh cùng chủ đề vẫn còn đủ clip chưa dùng (cùng chi phí hạn mức API).
SEARCH_PER_PAGE = 100
# Lượt cuối khi mọi từ khoá AI chọn đều không có clip, hoặc mọi clip hợp đều đã dùng.
FALLBACK_TERM = "nature"
# Clip đã dùng cho ảnh GIF trước (lẻ hay trong loạt) không được chọn lại khi còn clip khác.
USED_CLIPS_FILE = "used_clips.json"
USED_CLIPS_LIMIT = 500

WHITE = (255, 255, 255)
INK = (17, 17, 17)
# Chuẩn WCAG cho chữ cỡ lớn; tương phản thấp hơn thì đặt dải nền mờ sau chữ.
MIN_CONTRAST = 3.0
# Clip kho thường đặt chủ thể giữa khung (chữ ở giữa từng che mất con bạch tuộc), nên
# khi các vùng đọc rõ gần như nhau thì ưu tiên trên, rồi dưới, rồi mới đến giữa.
BAND_PREFERENCE = ("top", "bottom", "center")
BAND_TOLERANCE = 0.85


class GifError(Exception):
    """Lỗi có thông báo tiếng Việt dành cho người dùng."""


@dataclass
class Clip:
    url: str
    page_url: str
    width: int
    height: int
    duration: float
    term: str
    # Mã video trên Pixabay, dùng để không chọn lại clip đã dùng.
    clip_id: str = ""


@dataclass
class TextStyle:
    fill: tuple[int, int, int]
    stroke: tuple[int, int, int]
    # Tâm theo chiều dọc của khối chữ (pixel).
    center_y: int
    # Tương phản WCAG xấu nhất giữa màu chữ và nền (chưa tính dải nền mờ).
    contrast: float
    # Độ đậm (0–255) của dải nền mờ sau chữ; 0 là không cần.
    backdrop_alpha: int = 0


@dataclass
class Rendered:
    style: TextStyle
    # Kích thước bản MP4; GIF có thể nhỏ hơn nếu phải thu nhỏ cho nhẹ.
    width: int
    height: int
    seconds: float
    # MP4 không tiếng để Telegram phát mượt; None nếu không mã hoá được.
    preview_path: str | None


@dataclass
class GifResult:
    path: str
    preview_path: str | None
    width: int
    height: int
    seconds: float
    clip: Clip
    style: TextStyle


# ------------------------------------------------------------ tìm clip


def _largest(videos: dict) -> tuple[int, int]:
    sizes = [
        (int(v.get("width") or 0), int(v.get("height") or 0))
        for v in (videos or {}).values()
        if isinstance(v, dict)
    ]
    return max(sizes, default=(0, 0), key=lambda size: size[0] * size[1])


def pick_rendition(videos: dict, width: int, height: int) -> tuple[str, int, int] | None:
    """Bản nhỏ nhất vẫn phủ kín khung GIF sau khi cắt; không có thì lấy bản lớn nhất."""
    options = []
    for video in (videos or {}).values():
        if not isinstance(video, dict) or not video.get("url"):
            continue
        w, h = int(video.get("width") or 0), int(video.get("height") or 0)
        if w > 0 and h > 0:
            options.append((w * h, video["url"], w, h))
    if not options:
        return None
    options.sort()
    for _, url, w, h in options:
        if max(width / w, height / h) <= 1.0:
            return url, w, h
    _, url, w, h = options[-1]
    return url, w, h


# Pixabay tìm theo kiểu "hoặc" nên các từ chỉ cách quay kéo về clip lạc đề: "octopus
# closeup" trả về tinh thể thạch anh "closeup" trước cả clip bạch tuộc.
_GENERIC_WORDS = {
    "a", "an", "and", "at", "of", "on", "in", "the", "with",
    "closeup", "close", "up", "macro", "slow", "motion", "aerial", "view", "shot",
    "footage", "video", "background", "beautiful", "4k", "hd",
}
# Clip khớp từ chừng này từ ngữ cảnh trở lên đều coi là đúng chủ đề như nhau, để clip
# có danh sách thẻ dài không thắng chỉ vì khớp ngẫu nhiên nhiều từ.
_CONTEXT_CAP = 2


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _key_words(term: str) -> list[str]:
    words = _words(term)
    return [word for word in words if word not in _GENERIC_WORDS] or words


def _has(tag_words: set[str], word: str) -> bool:
    """Khớp nguyên từ, chấp nhận số ít và số nhiều (lake/lakes)."""
    return (
        word in tag_words
        or f"{word}s" in tag_words
        or (word.endswith("s") and word[:-1] in tag_words)
    )


def _clip_id(hit: dict) -> str:
    return str(hit.get("id") or hit.get("pageURL") or "")


def _used_clips_path() -> str:
    return os.path.join(utils.storage_dir("gifs", create=True), USED_CLIPS_FILE)


def used_clip_ids() -> list[str]:
    """Mã các clip đã dùng cho ảnh GIF, cũ trước mới sau."""
    try:
        with open(_used_clips_path(), encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError):
        return []
    return [str(item) for item in data] if isinstance(data, list) else []


def remember_clip(clip_id: str) -> None:
    if not clip_id:
        return
    ids = [item for item in used_clip_ids() if item != clip_id] + [clip_id]
    path = _used_clips_path()
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(ids[-USED_CLIPS_LIMIT:], file)
    os.replace(temp_path, path)


def _score(
    hit: dict, term: str, context: set[str], aspect: str, order: int, rank: int, unused: bool
) -> tuple:
    """
    Khớp đủ từ khoá chính > chưa dùng cho ảnh GIF trước > khớp ngữ cảnh của mọi từ khoá >
    đúng hướng khung hình > đủ dài > từ khoá AI xếp trước > thứ hạng của Pixabay.
    """
    tag_words = set(_words(str(hit.get("tags") or "")))
    w, h = _largest(hit.get("videos"))
    if aspect == "9:16":
        oriented = h > w
    elif aspect == "16:9":
        oriented = w > h
    else:
        oriented = True
    return (
        all(_has(tag_words, word) for word in _key_words(term)),
        unused,
        min(sum(_has(tag_words, word) for word in context), _CONTEXT_CAP),
        oriented,
        float(hit.get("duration") or 0) >= 3,
        -order,
        -rank,
    )


def _search(term: str, api_key: str) -> list[dict]:
    try:
        response = requests.get(
            "https://pixabay.com/api/videos/",
            params={
                "q": term,
                "video_type": "all",
                "per_page": SEARCH_PER_PAGE,
                "safesearch": "true",
                "key": api_key,
            },
            proxies=config.proxy,
            verify=material._get_tls_verify(),
            timeout=(20, 60),
        )
        hits = response.json().get("hits", []) if response.status_code == 200 else []
    except (requests.RequestException, ValueError) as exc:
        logger.warning(f"pixabay gif search failed for {term!r}: {type(exc).__name__}")
        return []
    return [hit for hit in hits if isinstance(hit, dict)]


def find_clip(
    terms: Sequence[str], aspect: str = DEFAULT_ASPECT, avoid: set[str] | None = None
) -> Clip:
    """
    Clip Pixabay sát nghĩa nhất trong kết quả của mọi từ khoá. Clip phải có đủ từ khoá
    chính trong thẻ và chưa nằm trong ``avoid`` (mặc định: clip đã dùng cho ảnh GIF
    trước). Hết clip như vậy thì dùng FALLBACK_TERM; chỉ khi cả hai đều chỉ còn clip đã
    dùng mới chọn lại clip hợp nhất.
    """
    width, height = OUTPUT_SIZES.get(aspect, OUTPUT_SIZES[DEFAULT_ASPECT])
    api_key = material.get_api_key("pixabay_api_keys")
    if not api_key:
        raise GifError("Chưa cấu hình pixabay_api_keys trong config.toml.")
    avoid = set(used_clip_ids()) if avoid is None else set(avoid)
    terms = [term.strip() for term in terms if term and term.strip()]
    reused = None
    for group in (terms, [FALLBACK_TERM]):
        context = {word for term in group for word in _key_words(term)}
        best = None
        for order, term in enumerate(group):
            for rank, hit in enumerate(_search(term, api_key)):
                unused = _clip_id(hit) not in avoid
                score = _score(hit, term, context, aspect, order, rank, unused)
                if not score[0] or (best and score <= best[0]):
                    continue
                rendition = pick_rendition(hit.get("videos"), width, height)
                if rendition:
                    best = (score, hit, rendition, term)
        if best:
            score, hit, (url, w, h), term = best
            clip = Clip(
                url=url,
                page_url=str(hit.get("pageURL") or ""),
                width=w,
                height=h,
                duration=float(hit.get("duration") or 0),
                term=term,
                clip_id=_clip_id(hit),
            )
            if score[1]:
                return clip
            reused = reused or clip
    if reused:
        logger.warning(f"all matching pixabay clips were used before, reusing {reused.clip_id}")
        return reused
    raise GifError("Không tìm thấy clip phù hợp trên Pixabay.")


def _download(url: str, path: str) -> None:
    try:
        with requests.get(
            url,
            stream=True,
            proxies=config.proxy,
            verify=material._get_tls_verify(),
            timeout=(20, 120),
        ) as response:
            response.raise_for_status()
            size = 0
            with open(path, "wb") as file:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    size += len(chunk)
                    if size > MAX_DOWNLOAD_BYTES:
                        raise GifError("Clip Pixabay quá lớn để làm ảnh GIF.")
                    file.write(chunk)
    except requests.RequestException as exc:
        raise GifError(f"Không tải được clip từ Pixabay ({type(exc).__name__}).") from exc


# ------------------------------------------------------- màu và vị trí chữ


def relative_luminance(rgb: np.ndarray) -> np.ndarray:
    """Độ chói tương đối theo WCAG cho mảng màu sRGB 0–255 (trục cuối là R, G, B)."""
    channel = np.asarray(rgb, dtype=np.float32) / 255.0
    linear = np.where(channel <= 0.04045, channel / 12.92, ((channel + 0.055) / 1.055) ** 2.4)
    return linear @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def contrast_ratio(first: float, second: float) -> float:
    light, dark = max(first, second), min(first, second)
    return (light + 0.05) / (dark + 0.05)


def _band_centers(height: int) -> dict[str, int]:
    return {"center": height // 2, "top": round(height * 0.27), "bottom": round(height * 0.73)}


def choose_style(
    frames: Sequence[np.ndarray], size: tuple[int, int], block: tuple[int, int]
) -> TextStyle:
    """
    Chọn chữ trắng hoặc đen và vùng đặt chữ cho tương phản cao nhất với nền.

    Tương phản tính với phân vị 10% và 90% độ chói của nền ở mọi khung hình mẫu,
    tức trường hợp xấu nhất khi cảnh chuyển động; các vùng gần bằng vùng tốt nhất
    thì chọn theo BAND_PREFERENCE. Nền vẫn quá rối thì thêm dải nền mờ màu ngược
    với chữ, đủ đậm để chữ đạt MIN_CONTRAST.
    """
    width, height = size
    block_width, block_height = block
    pad = max(round(height * 0.02), 6)
    candidates = (WHITE, INK)
    luminance = {color: float(relative_luminance(np.array(color))) for color in candidates}

    results = {}
    for name, center in _band_centers(height).items():
        top = min(max(center - block_height // 2 - pad, 0), max(height - block_height - 2 * pad, 0))
        bottom = min(top + block_height + 2 * pad, height)
        left = max((width - block_width) // 2 - pad, 0)
        right = min(left + block_width + 2 * pad, width)
        values = np.concatenate(
            [relative_luminance(frame[top:bottom, left:right]).ravel() for frame in frames]
        ) if frames else np.array([0.0])
        low, high = (float(v) for v in np.percentile(values, [10, 90]))
        best = max(
            candidates,
            key=lambda color: min(
                contrast_ratio(luminance[color], low), contrast_ratio(luminance[color], high)
            ),
        )
        worst = min(contrast_ratio(luminance[best], low), contrast_ratio(luminance[best], high))
        results[name] = (worst, best, low, high, (top + bottom) // 2)

    best_contrast = max(result[0] for result in results.values())
    best_name = next(
        name for name in BAND_PREFERENCE if results[name][0] >= best_contrast * BAND_TOLERANCE
    )
    worst, fill, low, high, center_y = results[best_name]
    stroke = INK if fill == WHITE else WHITE

    alpha = 0
    if worst < MIN_CONTRAST:
        fill_l, stroke_l = luminance[fill], luminance[stroke]
        if fill == WHITE:
            # Nền sáng nhất phải tối xuống còn mức này để chữ trắng đạt MIN_CONTRAST.
            target = (fill_l + 0.05) / MIN_CONTRAST - 0.05
            needed = (high - target) / max(high - stroke_l, 1e-6)
        else:
            target = MIN_CONTRAST * (fill_l + 0.05) - 0.05
            needed = (target - low) / max(stroke_l - low, 1e-6)
        alpha = round(min(max(needed, 0.45), 0.8) * 255)
    return TextStyle(fill, stroke, center_y, round(worst, 2), alpha)


# ------------------------------------------------------------ vẽ chữ


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(cover_service._font_path("BeVietnamPro-Bold.ttf"), size)


def fit_text(text: str, size: tuple[int, int]):
    """Cỡ chữ lớn nhất để câu nằm gọn trong khung: (font, các dòng, chiều cao dòng)."""
    width, height = size
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    max_width = round(width * 0.86)
    max_height = round(height * (0.42 if height > width else 0.6))
    max_lines = 5 if height > width else 4
    font_size = round(min(width, height * 1.2) * 0.085)
    min_size = max(18, round(min(width, height) * 0.05))
    while True:
        font = _font(font_size)
        lines = cover_service._balanced_wrap(draw, text, font, max_width)
        line_height = round(font_size * 1.22)
        fits = (
            len(lines) <= max_lines
            and line_height * len(lines) <= max_height
            and all(draw.textlength(line, font=font) <= max_width for line in lines)
        )
        if fits or font_size <= min_size:
            return font, lines, line_height
        font_size = max(min_size, int(font_size * 0.92))


def _block_size(font, lines: list[str], line_height: int) -> tuple[int, int]:
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    stroke = _stroke_width(font)
    width = max((draw.textlength(line, font=font) for line in lines), default=0)
    return round(width) + 2 * stroke, line_height * len(lines) + 2 * stroke


def _stroke_width(font) -> int:
    return max(round(font.size * 0.09), 2)


def render_overlay(size: tuple[int, int], layout, style: TextStyle) -> Image.Image:
    """Lớp chữ trong suốt cùng kích thước GIF: dải nền (nếu cần), bóng mờ, chữ có viền."""
    width, height = size
    font, lines, line_height = layout
    block_width, block_height = _block_size(font, lines, line_height)
    top = min(max(style.center_y - block_height // 2, 4), max(height - block_height - 4, 4))
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    if style.backdrop_alpha:
        pad_x, pad_y = round(font.size * 0.6), round(font.size * 0.4)
        draw.rounded_rectangle(
            (
                (width - block_width) // 2 - pad_x,
                top - pad_y,
                (width + block_width) // 2 + pad_x,
                top + block_height + pad_y,
            ),
            radius=round(font.size * 0.35),
            fill=style.stroke + (style.backdrop_alpha,),
        )

    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    offset = max(round(font.size * 0.05), 1)
    positions = []
    for index, line in enumerate(lines):
        x = (width - draw.textlength(line, font=font)) / 2
        y = top + index * line_height
        positions.append((x, y, line))
        shadow_draw.text((x + offset, y + offset), line, font=font, fill=style.stroke + (170,))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(round(font.size * 0.08), 1)))
    overlay = Image.alpha_composite(overlay, shadow)

    draw = ImageDraw.Draw(overlay)
    for x, y, line in positions:
        draw.text(
            (x, y), line, font=font, fill=style.fill + (255,),
            stroke_width=_stroke_width(font), stroke_fill=style.stroke + (255,),
        )
    return overlay


# ------------------------------------------------------------ dựng GIF


# Một số clip Pixabay gắn thông số màu ở giá trị "reserved" (yuv420p unknown/reserved/
# reserved): ffmpeg vẫn mã hoá được MP4 nhưng không đổi được sang RGB cho PNG và GIF,
# báo lỗi -129 (ENOTSUP trên Windows) và không ra khung hình nào. Đặt hai thông số này
# về "unknown" chỉ sửa siêu dữ liệu, không đổi màu điểm ảnh.
_NORMALIZE_COLOR = "setparams=color_primaries=unknown:color_trc=unknown"


def _frame_filter(width: int, height: int) -> str:
    """Chuẩn hoá thông số màu, phóng và cắt clip cho phủ kín khung GIF."""
    return (
        f"{_NORMALIZE_COLOR},"
        f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={width}:{height},setsar=1"
    )


def _ffmpeg(arguments: list[str]) -> bool:
    result = subprocess.run(
        [utils.get_ffmpeg_binary(), "-hide_banner", "-y", *arguments],
        capture_output=True,
    )
    if result.returncode != 0:
        logger.error(f"ffmpeg failed: {result.stderr[-600:]!r}")
    return result.returncode == 0


def _sample_frames(
    clip_path: str, start: float, length: float, size: tuple[int, int], temp_dir: str
) -> list[np.ndarray]:
    width, height = size
    pattern = os.path.join(temp_dir, "sample-%02d.png")
    rate = SAMPLE_FRAMES / max(length, 0.5)
    _ffmpeg([
        "-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", clip_path,
        "-vf", f"fps={rate:.3f},{_frame_filter(width, height)}",
        "-frames:v", str(SAMPLE_FRAMES), pattern,
    ])
    frames = []
    for index in range(1, SAMPLE_FRAMES + 1):
        path = pattern % index
        if os.path.exists(path):
            with Image.open(path) as image:
                frames.append(np.asarray(image.convert("RGB")))
    return frames


def make_gif(
    clip_path: str,
    text: str,
    output_path: str,
    aspect: str = DEFAULT_ASPECT,
    seconds: float = GIF_SECONDS,
) -> Rendered:
    """
    Cắt clip, chèn chữ, xuất ``output_path`` (GIF) và bản MP4 xem trước cạnh nó.

    Cả hai dùng chung lớp chữ đã chọn màu và vị trí từ các khung hình mẫu.
    """
    width, height = OUTPUT_SIZES.get(aspect, OUTPUT_SIZES[DEFAULT_ASPECT])
    _, _, duration = cover_service._probe(clip_path)
    start = SKIP_SECONDS if duration >= seconds + SKIP_SECONDS else 0.0
    length = min(seconds, duration - start) if duration > 0 else seconds
    trim = ["-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", clip_path]

    temp_dir = tempfile.mkdtemp(dir=utils.storage_dir("temp", create=True))
    try:
        layout = fit_text(text, (width, height))
        frames = _sample_frames(clip_path, start, length, (width, height), temp_dir)
        style = choose_style(frames, (width, height), _block_size(*layout))
        overlay_path = os.path.join(temp_dir, "overlay.png")
        render_overlay((width, height), layout, style).save(overlay_path)

        preview_path = os.path.splitext(output_path)[0] + ".mp4"
        if not _ffmpeg([
            *trim, "-i", overlay_path,
            "-filter_complex",
            f"[0:v]fps={PREVIEW_FPS},{_frame_filter(width, height)}[bg];"
            "[bg][1:v]overlay=0:0,format=yuv420p",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-movflags", "+faststart", preview_path,
        ]):
            preview_path = None

        # Bảng màu riêng cho từng GIF để màu chữ và nền không bị bệt. Dither kiểu
        # bayer giữ nguyên điểm ảnh ở vùng đứng yên (chữ) nên GIF nén tốt hơn.
        for fps, colors, scale in GIF_ATTEMPTS:
            shrink = (
                f",scale={round(width * scale)}:{round(height * scale)}:flags=lanczos"
                if scale < 1
                else ""
            )
            ok = _ffmpeg([
                *trim, "-i", overlay_path,
                "-filter_complex",
                f"[0:v]fps={fps},{_frame_filter(width, height)}[bg];"
                f"[bg][1:v]overlay=0:0{shrink},split[a][b];"
                f"[a]palettegen=max_colors={colors}:stats_mode=full[p];"
                "[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                "-loop", "0", output_path,
            ])
            if not ok or not os.path.exists(output_path):
                raise GifError("ffmpeg không tạo được ảnh GIF.")
            if os.path.getsize(output_path) <= MAX_GIF_BYTES:
                break
        return Rendered(style, width, height, length, preview_path)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _file_name(text: str) -> str:
    """Tên file không dấu theo nội dung chữ, để tải về dễ nhận ra."""
    ascii_text = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    ascii_text = "".join(char for char in ascii_text if unicodedata.category(char) != "Mn")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:48].strip("-")
    return f"{slug or 'gif'}-{uuid4().hex[:6]}.gif"


def create_text_gif(
    text: str, terms: Sequence[str], aspect: str | None, output_dir: str
) -> GifResult:
    """Tìm clip Pixabay sát nghĩa nhất, chèn ``text`` và lưu GIF vào ``output_dir``."""
    aspect = aspect if aspect in OUTPUT_SIZES else DEFAULT_ASPECT
    clip = find_clip(terms, aspect)
    temp_dir = tempfile.mkdtemp(dir=utils.storage_dir("temp", create=True))
    try:
        source = os.path.join(temp_dir, "clip.mp4")
        _download(clip.url, source)
        os.makedirs(output_dir, exist_ok=True)
        output = os.path.join(output_dir, _file_name(text))
        rendered = make_gif(source, text, output, aspect)
        remember_clip(clip.clip_id)
        return GifResult(
            output,
            rendered.preview_path,
            rendered.width,
            rendered.height,
            rendered.seconds,
            clip,
            rendered.style,
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
