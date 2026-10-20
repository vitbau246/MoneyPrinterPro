"""
Tạo nhanh video hoặc ảnh GIF có chữ theo loại nội dung (app/services/content_presets.py).

Phần dùng chung của bot Telegram (telegram_bot.py) và trang "Tạo nhanh" của WebUI,
để hai nơi cho cùng một kết quả: cùng cú pháp tuỳ chọn (#gif, #high, #45s, #ngang,
#en, #15), cùng kịch bản và nội dung đăng bài, cùng ảnh bìa, cùng model AI và cùng
lưu vào thư mục thành phẩm storage/output. Phần riêng của mỗi nơi (gửi tin Telegram,
hiển thị trên web) đi qua các hàm gọi lại ``on_stage``, ``on_progress`` và ``deliver``.

Thiết lập chung đọc từ mục [telegram] của config.toml (giữ tên cũ để không phải
sửa cấu hình): high_model, default_language, default_duration, voices.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, field

from loguru import logger

from app.config import config
from app.models import const
from app.services import content_presets as cp
from app.services import cover as cover_service
from app.services import gif_maker
from app.services import llm
from app.services import output_library
from app.services import social_publish
from app.services import social_schedule
from app.services import state as sm
from app.services import task as tm
from app.utils import utils

DEFAULT_BATCH_SIZE = 10
# Mục trong loạt bị lỗi được thử lại thêm số lần này.
BATCH_RETRIES = 1
DEFAULT_HIGH_MODEL = "gpt-6.1-sol"
ASPECTS = ("9:16", "16:9", "1:1")

# Loạt do AI tự nghĩ chủ đề con: không dùng cho sản phẩm (cần ảnh thật) và tin tức
# (cần bài báo gốc, nếu không sẽ thành tin bịa).
BATCH_PRESETS: dict[str, cp.ContentPreset] = {
    command: preset
    for command, preset in cp.PRESETS_BY_COMMAND.items()
    if not preset.requires_media and not preset.requires_source_text
}

ASPECT_FLAGS = {"#doc": "9:16", "#ngang": "16:9", "#vuong": "1:1"}
# "#45s", "#45 giây", "#2p", "#1.5 phút"
_DURATION_RE = re.compile(
    r"#(\d+(?:[.,]\d+)?)\s*(s|giây|giay|p|phút|phut)\b", re.IGNORECASE
)
# "45", "45s", "2p", "1.5 phút" cho lệnh /thoiluong
DURATION_VALUE_RE = re.compile(
    r"^(\d+(?:[.,]\d+)?)\s*(s|giây|giay|p|phút|phut)?$", re.IGNORECASE
)
# "#en", "#vi": ngôn ngữ riêng cho một video
LANGUAGE_FLAGS = {"en": "en-US", "vi": "vi-VN"}
_LANGUAGE_RE = re.compile(r"#(en|vi)\b", re.IGNORECASE)
# "#gif": ảnh động có chữ từ clip Pixabay thay cho video lồng tiếng
_GIF_RE = re.compile(r"#gif\b", re.IGNORECASE)
# "#high": dùng model AI mạnh hơn cho riêng yêu cầu này
_HIGH_RE = re.compile(r"#high\b", re.IGNORECASE)
# "#dang": lên lịch đăng Facebook/TikTok/YouTube sau khi tạo; "#khongdang": không đăng
# kể cả khi đang bật đăng tự động.
_NO_POST_RE = re.compile(r"#(?:khong|không)\s*dang\b", re.IGNORECASE)
_POST_RE = re.compile(r"#dang\b", re.IGNORECASE)
# "#15", "#15 video" cho loạt
_BATCH_COUNT_RE = re.compile(r"#(\d+)(?:\s*(?:video|clip))?\b", re.IGNORECASE)


# ------------------------------------------------------------ thiết lập chung


def _settings() -> dict:
    return config._cfg.get("telegram", {}) or {}


def high_model() -> str:
    """Model AI cho yêu cầu có #high; các yêu cầu khác dùng [app].openai_model_name."""
    return str(_settings().get("high_model") or DEFAULT_HIGH_MODEL).strip()


def default_language() -> str:
    value = _settings().get("default_language")
    return value if value in cp.LANGUAGES else cp.DEFAULT_LANGUAGE


def default_duration() -> int | None:
    """Thời lượng mặc định; None nghĩa là dùng mặc định riêng của từng loại nội dung."""
    return cp.normalize_duration(_settings().get("default_duration") or None)


def language_voice(code: str) -> str | None:
    """Giọng đọc riêng của ngôn ngữ trong [telegram].voices, nếu có."""
    voices = _settings().get("voices") or {}
    voice = voices.get(code) if isinstance(voices, dict) else None
    return str(voice) if voice else None


def llm_model(high: bool):
    """Model AI cho mọi lời gọi trong khối: #high dùng high_model(), còn lại theo config."""
    model = high_model() if high else ""
    return llm.use_model(model) if model else nullcontext()


def language_name(code: str) -> str:
    return cp.get_language(code).name


def format_duration(seconds: int) -> str:
    minutes, rest = divmod(int(seconds), 60)
    if not minutes:
        return f"{seconds} giây"
    return f"{minutes} phút" + (f" {rest} giây" if rest else "")


def duration_error(seconds: int | None, example: str = "#45s hoặc #2p") -> str:
    """Thông báo khi thời lượng nằm ngoài giới hạn; rỗng nếu hợp lệ hoặc không chỉ định."""
    if seconds is None or cp.normalize_duration(seconds) == seconds:
        return ""
    return (
        f"Thời lượng phải từ {cp.MIN_DURATION_SECONDS} đến "
        f"{cp.MAX_DURATION_SECONDS} giây. Ví dụ: {example}."
    )


# ---------------------------------------------------- tuỳ chọn trong nội dung


def _tidy(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def to_seconds(number: str, unit: str | None) -> int:
    value = float(number.replace(",", "."))
    if unit and unit.lower() in ("p", "phút", "phut"):
        value *= 60
    return round(value)


def extract_aspect(prompt: str) -> tuple[str, str | None]:
    aspect = None
    for flag, value in ASPECT_FLAGS.items():
        if flag in prompt:
            aspect = value
            prompt = prompt.replace(flag, " ")
    return _tidy(prompt), aspect


def extract_duration(prompt: str) -> tuple[str, int | None]:
    match = _DURATION_RE.search(prompt)
    if not match:
        return prompt, None
    seconds = to_seconds(match.group(1), match.group(2))
    return _tidy(prompt[: match.start()] + " " + prompt[match.end():]), seconds


def extract_language(prompt: str) -> tuple[str, str | None]:
    match = _LANGUAGE_RE.search(prompt)
    if not match:
        return prompt, None
    prompt = prompt[: match.start()] + " " + prompt[match.end():]
    return _tidy(prompt), LANGUAGE_FLAGS[match.group(1).lower()]


def extract_gif(prompt: str) -> tuple[str, bool]:
    if not _GIF_RE.search(prompt):
        return prompt, False
    return _tidy(_GIF_RE.sub(" ", prompt)), True


def extract_high(prompt: str) -> tuple[str, bool]:
    if not _HIGH_RE.search(prompt):
        return prompt, False
    return _tidy(_HIGH_RE.sub(" ", prompt)), True


def extract_post(prompt: str) -> tuple[str, bool | None]:
    if _NO_POST_RE.search(prompt):
        return _tidy(_NO_POST_RE.sub(" ", prompt)), False
    if _POST_RE.search(prompt):
        return _tidy(_POST_RE.sub(" ", prompt)), True
    return prompt, None


def extract_batch_count(prompt: str) -> tuple[str, int | None]:
    match = _BATCH_COUNT_RE.search(prompt)
    if not match:
        return prompt, None
    return _tidy(prompt[: match.start()] + " " + prompt[match.end():]), int(match.group(1))


@dataclass
class Options:
    """Tuỳ chọn gõ kèm nội dung; None/False nghĩa là người dùng không chỉ định."""

    aspect: str | None = None
    duration: int | None = None
    language: str | None = None
    gif: bool = False
    high: bool = False
    count: int | None = None
    # None: theo thiết lập đăng tự động; True/False: #dang / #khongdang.
    post: bool | None = None


def parse_options(text: str, batch: bool = False) -> tuple[str, Options]:
    """
    Tách các tuỳ chọn #... khỏi nội dung, theo đúng thứ tự bot vẫn dùng.
    ``batch`` thì nhận thêm số lượng (#15) cho loạt.
    """
    options = Options()
    text, options.post = extract_post(text or "")
    text, options.gif = extract_gif(text)
    text, options.high = extract_high(text)
    text, options.aspect = extract_aspect(text)
    text, options.language = extract_language(text)
    text, options.duration = extract_duration(text)
    if batch:
        text, options.count = extract_batch_count(text)
    return text, options


def request_error(
    preset: cp.ContentPreset, prompt: str, media_count: int = 0, gif: bool = False
) -> str:
    """Lỗi của yêu cầu tạo một video/ảnh GIF; rỗng nếu hợp lệ."""
    if gif and preset.requires_media:
        return (
            f"/{preset.command} cần ảnh thật của sản phẩm nên không tạo ảnh GIF "
            "từ Pixabay được."
        )
    if gif and media_count:
        return "Ảnh GIF lấy clip từ Pixabay nên không dùng ảnh/video gửi kèm."
    error = cp.validate_prompt(preset, prompt, media_count)
    if error:
        return error
    if media_count and not preset.accepts_media:
        commands = " hoặc ".join(
            f"/{item.command}" for item in cp.PRESETS.values() if item.accepts_media
        )
        return (
            f"/{preset.command} không dùng ảnh/video gửi kèm. "
            f"Chỉ {commands} hỗ trợ dùng hình ảnh của bạn."
        )
    return ""


# ----------------------------------------------------------- thành phẩm


def make_cover(
    preset: cp.ContentPreset, prompt: str, video_path: str, result: dict | None = None
) -> str | None:
    """
    Trả về cover của video. Pipeline đã tạo cover-N.jpg (và ghép vào đầu video)
    khi VideoParams có cover_title; chỉ tạo mới cho video cũ chưa có cover.
    """
    task_dir = os.path.dirname(video_path)
    index = re.search(r"final-(\d+)", os.path.basename(video_path))
    for name in (f"cover-{index[1]}.jpg" if index else "", "cover.jpg"):
        if name and os.path.exists(os.path.join(task_dir, name)):
            return os.path.join(task_dir, name)
    subtitle_path = os.path.join(task_dir, "subtitle.srt")
    return cover_service.create_cover(
        video_path,
        cp.cover_title(prompt),
        os.path.join(task_dir, "cover.jpg"),
        label=preset.title.split("/")[0].strip(),
        sources=(result or {}).get("materials") or None,
        subtitle_path=subtitle_path if os.path.exists(subtitle_path) else None,
    )


def keep_video(
    path: str, title: str, script: str, cover_path: str | None
) -> output_library.SavedItem | None:
    """
    Đưa video cuối, ảnh bìa và lời thoại vào thư mục thành phẩm (storage/output/video).
    Lỗi chỉ ghi log để không chặn việc gửi; khi đó video vẫn nằm trong thư mục task.
    """
    try:
        return output_library.save_video(path, title, script, cover_path)
    except Exception as exc:
        logger.exception(f"failed to save {path} to the output library: {exc}")
        return None


def keep_gif(
    result: gif_maker.GifResult, gif_text: cp.GifText
) -> output_library.SavedItem | None:
    """Đưa ảnh GIF, bản MP4 và lời diễn giải vào storage/output/gif; tiêu đề là chữ trên ảnh."""
    try:
        return output_library.save_gif(
            result.path, result.preview_path, gif_text.text, gif_text.detail
        )
    except Exception as exc:
        logger.exception(f"failed to save {result.path} to the output library: {exc}")
        return None


def saved_note(saved: output_library.SavedItem | None, fallback: str) -> str:
    return f"Đã lưu: {saved.name}" if saved else f"Chưa lưu được vào thư mục thành phẩm: {fallback}"


# ------------------------------------------------------------------ video


class VideoFailed(Exception):
    """Pipeline không tạo được video; ``stage`` rỗng khi chạy xong nhưng không có video."""

    def __init__(self, stage: str, error: str):
        super().__init__(error)
        self.stage = stage
        self.error = error

    def describe(self) -> str:
        if self.stage:
            return f"Tạo video thất bại ở bước {self.stage}:\n{self.error}"
        return self.error


@dataclass
class VideoOutput:
    # Đường dẫn trong thư mục task lúc tạo xong; sau khi lưu thì file nằm ở saved.paths.
    path: str
    cover_path: str | None
    saved: output_library.SavedItem | None
    delivered: bool


@dataclass
class VideoResult:
    task_id: str
    title: str
    script: str
    post: cp.PostPackage | None
    audio_duration: float
    minutes: float
    outputs: list[VideoOutput] = field(default_factory=list)

    @property
    def delivered(self) -> bool:
        return any(output.delivered for output in self.outputs)


def _report_progress(
    task_id: str,
    done: threading.Event,
    on_progress: Callable[[int], None],
    interval: float,
) -> None:
    last_progress = -1
    while not done.wait(interval):
        task = sm.state.get_task(task_id) or {}
        progress = int(task.get("progress", 0) or 0)
        if progress != last_progress:
            last_progress = progress
            try:
                on_progress(progress)
            except Exception:
                logger.exception("progress callback failed")


def create_video(
    preset: cp.ContentPreset,
    prompt: str,
    *,
    aspect: str | None = None,
    duration: int | None = None,
    language: str | None = None,
    high: bool = False,
    material_paths: Sequence[str] | None = None,
    on_stage: Callable[[str], None] | None = None,
    on_progress: Callable[[int], None] | None = None,
    progress_interval: float = 15,
    deliver: Callable[[VideoResult, str, str | None], bool] | None = None,
    render_lock=None,
) -> VideoResult:
    """
    Viết kịch bản và nội dung đăng bài chuẩn SEO, dựng video, làm ảnh bìa rồi lưu vào
    thư mục thành phẩm và xoá thư mục task.

    ``on_stage`` nhận "script", "render", "deliver"; ``on_progress`` nhận phần trăm
    dựng video. ``deliver(result, path, cover)`` gửi/hiển thị từng video trước khi
    file được chuyển vào thư mục thành phẩm, trả về False nếu không gửi được.
    ``render_lock`` giữ trong lúc dựng (WebUI dùng khoá cấu hình để không dựng chồng
    với chế độ tuỳ chỉnh chi tiết). Lỗi pipeline ném VideoFailed.
    """
    language = language or default_language()
    stage = on_stage or (lambda name: None)
    task_id = utils.get_uuid()
    started = time.monotonic()
    with llm_model(high):
        stage("script")
        params = cp.build_params(
            preset,
            prompt,
            material_paths or None,
            aspect,
            duration,
            language=language,
            voice_name=language_voice(language),
        )
        post = cp.prepare_script_and_post(preset, params)
        stage("render")
        if on_progress:
            on_progress(0)
        done = threading.Event()
        if on_progress:
            threading.Thread(
                target=_report_progress,
                args=(task_id, done, on_progress, progress_interval),
                daemon=True,
            ).start()
        try:
            with render_lock or nullcontext():
                result = tm.start(task_id=task_id, params=params, stop_at="video")
        finally:
            done.set()

    if not result or result.get("state") == const.TASK_STATE_FAILED:
        raise VideoFailed(
            (result or {}).get("failed_stage", "unknown"),
            (result or {}).get("error", "không rõ lỗi"),
        )
    videos = result.get("videos") or []
    if not videos:
        raise VideoFailed("", "Pipeline chạy xong nhưng không có video đầu ra.")

    output = VideoResult(
        task_id=task_id,
        title=params.cover_title or cp.cover_title(prompt),
        script=(result.get("script") or "").strip(),
        post=post,
        audio_duration=float(result.get("audio_duration") or 0),
        minutes=(time.monotonic() - started) / 60,
    )
    stage("deliver")
    for path in videos:
        cover_path = make_cover(preset, prompt, path, result)
        delivered = False
        try:
            delivered = bool(deliver(output, path, cover_path)) if deliver else True
        finally:
            # Lưu cả khi gửi lỗi: video đã tạo xong vẫn có trong thư mục thành phẩm.
            saved = keep_video(path, output.title, output.script, cover_path)
            output.outputs.append(VideoOutput(path, cover_path, saved, delivered))
            if saved:
                # Ghi tiêu đề/mô tả chuẩn SEO để khi đăng Facebook/TikTok/YouTube dùng lại.
                social_schedule.remember_post(saved.paths[0], *post_text(post, output.title))
    # Chỉ xoá thư mục task khi mọi video đã nằm trong thư mục thành phẩm.
    if all(item.saved for item in output.outputs):
        output_library.remove_task_dir(task_id)
    return output


# --------------------------------------------------------- ảnh GIF có chữ


@dataclass
class GifOutput:
    text: cp.GifText
    gif: gif_maker.GifResult
    saved: output_library.SavedItem | None
    seconds: float


def create_gif(
    preset: cp.ContentPreset,
    prompt: str,
    *,
    aspect: str | None = None,
    language: str | None = None,
    high: bool = False,
    used_terms: list[str] | None = None,
    on_stage: Callable[[str, str], None] | None = None,
    deliver: Callable[[cp.GifText, gif_maker.GifResult], None] | None = None,
) -> GifOutput:
    """
    AI viết câu chèn lên ảnh (cũng là tiêu đề) và lời diễn giải, tìm clip Pixabay sát
    nghĩa nhất chưa dùng, chèn chữ rồi lưu vào thư mục thành phẩm.

    ``used_terms`` là cảnh các ảnh trước trong loạt đã dùng (được nối thêm cảnh của
    ảnh này) để AI chọn cảnh khác. ``on_stage`` nhận ("text", "") rồi ("clip", câu
    chữ) và ("deliver", ""). Lỗi người dùng cần biết thì ném gif_maker.GifError.
    """
    language = language or default_language()
    stage = on_stage or (lambda name, detail: None)
    started = time.monotonic()
    with llm_model(high):
        stage("text", "")
        gif_text = cp.generate_gif_text(
            preset, prompt, language, used_terms[-12:] if used_terms else ()
        )
    if gif_text is None:
        raise gif_maker.GifError("AI chưa viết được nội dung, thử lại sau ít phút.")
    if used_terms is not None:
        used_terms.extend(gif_text.terms)
    stage("clip", gif_text.text)
    result = gif_maker.create_text_gif(
        gif_text.text, gif_text.terms, aspect, utils.storage_dir("gifs", create=True)
    )
    stage("deliver", "")
    try:
        if deliver:
            deliver(gif_text, result)
    finally:
        saved = keep_gif(result, gif_text)
    return GifOutput(gif_text, result, saved, time.monotonic() - started)


# ------------------------------------------------- lên lịch đăng sau khi tạo


def post_text(post: cp.PostPackage | None, fallback_title: str) -> tuple[str, str, list[str]]:
    """(tiêu đề, mô tả kèm hashtag, thẻ YouTube) để đăng video."""
    return social_schedule.post_fields(post, fallback_title)


def should_post(flag: bool | None) -> bool:
    """#dang / #khongdang thắng; không ghi thì theo thiết lập đăng tự động."""
    return flag if flag is not None else social_schedule.get_settings()["auto_post"]


def schedule_outputs(
    result: VideoResult, flag: bool | None, *, source: str, chat_id: int | None = None
) -> list[dict]:
    """Đưa các video vừa lưu vào lịch đăng nếu người dùng muốn; trả về các mục lịch."""
    if not should_post(flag):
        return []
    title, description, tags = post_text(result.post, result.title)
    scheduled = []
    for output in result.outputs:
        if output.saved:
            entry = social_schedule.schedule_created_video(
                output.saved.paths[0], title, description, tags, source=source, chat_id=chat_id
            )
            if entry:
                scheduled.append(entry)
    return scheduled


def schedule_note(entries: Sequence[dict]) -> str:
    if not entries:
        return ""
    entry = entries[0]
    platforms = ", ".join(social_publish.PLATFORM_NAMES[name] for name in entry["targets"])
    return f"Lịch đăng: {platforms} lúc {social_schedule.format_time(entry['run_at'])}."
