"""
Bot Telegram tạo video ngắn theo các loại nội dung trong app/services/content_presets.py.

Phần tạo video/ảnh GIF dùng chung với trang "Tạo nhanh" của WebUI
(app/services/quick_create.py), nên hai nơi cho cùng kết quả. Trước mỗi yêu cầu bot
đọc lại config.toml, nên thiết lập vừa chỉnh trên WebUI (giọng đọc, phụ đề, nhạc nền,
nguồn video, LLM...) có hiệu lực ngay, không cần khởi động lại bot.

Cấu hình trong config.toml:

    [telegram]
    bot_token = "123456:ABC..."          # hoặc biến môi trường TELEGRAM_BOT_TOKEN
    allowed_user_ids = [123456789]       # chỉ những user này được dùng bot

Chạy: telegram_bot.bat (bản portable) hoặc `python telegram_bot.py`.
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from uuid import uuid4

import telebot
from loguru import logger
from PIL import Image
from telebot import types

from app.config import config
from app.models import const
from app.services import content_presets as cp
from app.services import gif_maker
from app.services import quick_create as qc
from app.services import social_accounts
from app.services import social_browser
from app.services import social_publish as sp
from app.services import social_schedule
from app.services import video as video_service
from app.utils import utils

# Giới hạn của Telegram Bot API: tải xuống tối đa 20MB, gửi lên tối đa 50MB.
TELEGRAM_UPLOAD_LIMIT = 49 * 1024 * 1024
COMPRESS_TARGET_BYTES = 45 * 1024 * 1024
ALBUM_WAIT_SECONDS = 2.0
PROGRESS_INTERVAL_SECONDS = 15
MAX_CAPTION = 1000
MAX_MESSAGE = 4000
SINGLE_INSTANCE_PORT = 47831
# Câu hỏi bổ sung chưa được trả lời sau khoảng này thì bỏ, người dùng gửi lại lệnh.
CLARIFY_TIMEOUT_SECONDS = 30 * 60
DEFAULT_BATCH_SIZE = qc.DEFAULT_BATCH_SIZE
# Danh sách chủ đề con chưa được duyệt sau khoảng này thì bỏ.
BATCH_PLAN_TIMEOUT_SECONDS = 24 * 3600
# Video trong loạt bị lỗi được thử lại thêm số lần này, giống telegram_batch.py.
BATCH_RETRIES = qc.BATCH_RETRIES

_COMMAND_RE = re.compile(r"^/(\w+)(?:@\w+)?(.*)$", re.DOTALL)
LANGUAGE_FLAGS = qc.LANGUAGE_FLAGS

_telegram_cfg = config._cfg.get("telegram", {})
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or _telegram_cfg.get("bot_token", "")
CONFIG_USER_IDS = {int(uid) for uid in _telegram_cfg.get("allowed_user_ids", [])}
# Admin nhận và duyệt yêu cầu cấp quyền; mặc định là các user trong allowed_user_ids.
ADMIN_USER_IDS = {
    int(uid) for uid in _telegram_cfg.get("admin_user_ids", [])
} or set(CONFIG_USER_IDS)
SETTINGS_FILE = os.path.join(utils.storage_dir(create=True), "telegram_settings.json")
# Người dùng được admin duyệt qua Telegram. Lưu riêng thay vì ghi vào config.toml
# vì WebUI ở tiến trình khác có thể ghi đè config.toml bằng bản cũ của nó.
ACCESS_FILE = os.path.join(utils.storage_dir(create=True), "telegram_access.json")
ACCESS_REQUEST_COOLDOWN_SECONDS = 600


def _load_access() -> dict:
    try:
        with open(ACCESS_FILE, encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError):
        data = {}
    data.setdefault("approved", {})
    data.setdefault("pending", {})
    data.setdefault("denied", {})
    return data


def _save_access(data: dict) -> None:
    temp_path = ACCESS_FILE + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    os.replace(temp_path, ACCESS_FILE)


ALLOWED_USER_IDS = CONFIG_USER_IDS | ADMIN_USER_IDS | {
    int(uid) for uid in _load_access()["approved"]
}

if not BOT_TOKEN:
    sys.exit(
        "Thiếu bot token: thêm [telegram].bot_token vào config.toml "
        "hoặc đặt biến môi trường TELEGRAM_BOT_TOKEN."
    )

# Proxy riêng cho Telegram, khi proxy mặc định của máy chặn api.telegram.org. Bỏ trống
# thì dùng proxy hệ thống (biến môi trường HTTPS_PROXY) như trước.
TELEGRAM_PROXY = str(_telegram_cfg.get("proxy") or "").strip()
if TELEGRAM_PROXY:
    telebot.apihelper.proxy = {"http": TELEGRAM_PROXY, "https": TELEGRAM_PROXY}

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

# Loạt video do AI tự nghĩ chủ đề con (không gồm sản phẩm và tin tức).
BATCH_PRESETS = qc.BATCH_PRESETS


@dataclass
class MediaRef:
    file_id: str
    extension: str


@dataclass
class Batch:
    """Loạt video của lệnh /hangloat: chờ duyệt danh sách chủ đề con, rồi tạo lần lượt."""

    id: str
    chat_id: int
    user_id: int
    preset: cp.ContentPreset
    theme: str
    count: int
    aspect: str | None
    duration: int | None
    language: str = cp.DEFAULT_LANGUAGE
    # Loạt ảnh GIF có chữ (tuỳ chọn #gif) thay cho video lồng tiếng.
    gif: bool = False
    # Dùng model AI mạnh hơn cho cả loạt (tuỳ chọn #high).
    high: bool = False
    # Lên lịch đăng Facebook/TikTok/YouTube (#dang / #khongdang; None theo đăng tự động).
    post: bool | None = None
    topics: list[cp.Subtopic] = field(default_factory=list)
    # Cảnh (từ khoá Pixabay) các ảnh GIF trước trong loạt đã dùng, để ảnh sau chọn khác.
    used_terms: list[str] = field(default_factory=list)
    # Các tin hiển thị danh sách chờ duyệt; nút bấm nằm ở tin cuối.
    plan_message_ids: list[int] = field(default_factory=list)
    plan_text: str = ""
    # Đang gọi AI đề xuất danh sách, chưa nhận thao tác khác.
    busy: bool = False
    approved: bool = False
    # Tin theo dõi tiến độ, kèm nút Dừng.
    status_message_id: int | None = None
    next_index: int = 0
    sent: int = 0
    failed: list[int] = field(default_factory=list)
    stopped: bool = False
    finished: bool = False
    created: float = field(default_factory=time.monotonic)
    started: float = 0.0


@dataclass
class Job:
    chat_id: int
    reply_to: int
    preset: cp.ContentPreset
    prompt: str
    aspect: str | None
    duration: int | None = None
    media: list[MediaRef] = field(default_factory=list)
    status_message_id: int | None = None
    language: str = cp.DEFAULT_LANGUAGE
    batch: Batch | None = None
    # Số thứ tự (từ 1) của video trong loạt.
    batch_number: int = 0
    # Ảnh GIF có chữ (tuỳ chọn #gif) thay cho video lồng tiếng.
    gif: bool = False
    # Dùng model AI mạnh hơn (tuỳ chọn #high).
    high: bool = False
    # Lên lịch đăng Facebook/TikTok/YouTube (#dang / #khongdang; None theo đăng tự động).
    post: bool | None = None


@dataclass
class Draft:
    """Yêu cầu đang chờ người dùng trả lời câu hỏi bổ sung trước khi xếp hàng."""

    job: Job
    user_id: int
    questions: list[str]
    text: str
    created: float = field(default_factory=time.monotonic)


jobs: "queue.Queue[Job]" = queue.Queue()
_running_job: Job | None = None
_drafts_lock = threading.Lock()
# Khoá là message_id của tin nhắn câu hỏi, cũng là tin trạng thái của job.
_drafts: dict[int, Draft] = {}
_batches_lock = threading.Lock()
# Loạt video đang chờ duyệt hoặc đang chạy, khoá là Batch.id.
_batches: dict[str, Batch] = {}


# ------------------------------------------------- thiết lập theo người dùng

_settings_lock = threading.Lock()


def _load_settings() -> dict:
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as file:
            return json.load(file)
    except (OSError, ValueError):
        return {}


def _get_user_setting(user_id: int, key: str):
    with _settings_lock:
        return _load_settings().get(str(user_id), {}).get(key)


def _set_user_setting(user_id: int, key: str, value) -> None:
    """Lưu thiết lập của người dùng; giá trị rỗng thì xoá để quay về mặc định."""
    with _settings_lock:
        settings = _load_settings()
        user = settings.setdefault(str(user_id), {})
        if value:
            user[key] = value
        else:
            user.pop(key, None)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
            json.dump(settings, file, ensure_ascii=False, indent=2)


def _get_user_duration(user_id: int) -> int | None:
    value = _get_user_setting(user_id, "duration")
    return cp.normalize_duration(value) if value else qc.default_duration()


def _set_user_duration(user_id: int, seconds: int | None) -> None:
    _set_user_setting(user_id, "duration", seconds)


def _get_user_language(user_id: int) -> str:
    value = _get_user_setting(user_id, "language")
    return value if value in cp.LANGUAGES else qc.default_language()


# ---------------------------------------------------------------- tiện ích


def _is_authorized(message: types.Message) -> bool:
    user_id = message.from_user.id if message.from_user else None
    if user_id in ALLOWED_USER_IDS:
        return True
    who = _describe_user(message.from_user) if message.from_user else "unknown"
    logger.warning(
        f"unauthorized telegram user: id={user_id}, name={who}, "
        f"text={(message.text or message.caption or '')[:100]!r}"
    )
    if user_id is None:
        return False
    with _access_lock:
        pending = str(user_id) in _load_access()["pending"]
    if pending:
        bot.reply_to(
            message,
            "Yêu cầu cấp quyền của bạn đang chờ quản trị viên duyệt. "
            "Bot sẽ nhắn cho bạn khi có kết quả.",
        )
        return False
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("Gửi yêu cầu cấp quyền", callback_data="access:request")
    )
    bot.reply_to(
        message,
        "Bạn chưa có quyền dùng bot này.\n"
        f"User ID của bạn: {user_id}\n"
        "Bấm nút bên dưới để gửi yêu cầu tới quản trị viên.",
        reply_markup=keyboard,
    )
    return False


# ------------------------------------------------------- cấp quyền truy cập

_access_lock = threading.Lock()


def _describe_user(user: types.User) -> str:
    name = " ".join(part for part in (user.first_name, user.last_name) if part)
    username = f" (@{user.username})" if user.username else ""
    return f"{name or 'Không tên'}{username}"


def _is_admin(user_id: int | None) -> bool:
    return user_id in ADMIN_USER_IDS


@bot.callback_query_handler(func=lambda call: call.data == "access:request")
def handle_access_request(call: types.CallbackQuery) -> None:
    user = call.from_user
    if user.id in ALLOWED_USER_IDS:
        bot.answer_callback_query(call.id, "Bạn đã có quyền dùng bot.")
        return
    now = time.time()
    with _access_lock:
        access = _load_access()
        if str(user.id) in access["pending"]:
            bot.answer_callback_query(call.id, "Yêu cầu đã được gửi, vui lòng chờ duyệt.")
            return
        denied_at = access["denied"].get(str(user.id), {}).get("at", 0)
        wait = ACCESS_REQUEST_COOLDOWN_SECONDS - (now - denied_at)
        if wait > 0:
            bot.answer_callback_query(
                call.id, f"Vui lòng thử lại sau {int(wait // 60) + 1} phút.", show_alert=True
            )
            return
        logger.info(f"access request from id={user.id}, name={_describe_user(user)}")
        access["pending"][str(user.id)] = {
            "name": _describe_user(user),
            "chat_id": call.message.chat.id,
            "at": now,
        }
        _save_access(access)

    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("✅ Duyệt", callback_data=f"access:approve:{user.id}"),
        types.InlineKeyboardButton("❌ Từ chối", callback_data=f"access:deny:{user.id}"),
    )
    text = (
        "Yêu cầu cấp quyền dùng bot:\n"
        f"Người dùng: {_describe_user(user)}\n"
        f"User ID: {user.id}"
    )
    delivered = 0
    for admin_id in ADMIN_USER_IDS:
        try:
            bot.send_message(admin_id, text, reply_markup=keyboard)
            delivered += 1
        except Exception as exc:
            logger.warning(f"cannot deliver access request to admin {admin_id}: {exc}")

    if not delivered:
        with _access_lock:
            access = _load_access()
            access["pending"].pop(str(user.id), None)
            _save_access(access)
        bot.answer_callback_query(
            call.id, "Chưa liên hệ được quản trị viên, vui lòng thử lại sau.", show_alert=True
        )
        return
    bot.answer_callback_query(call.id, "Đã gửi yêu cầu.")
    try:
        bot.edit_message_text(
            "Đã gửi yêu cầu cấp quyền tới quản trị viên. Bot sẽ nhắn cho bạn khi có kết quả.",
            call.message.chat.id,
            call.message.message_id,
        )
    except Exception:
        pass


@bot.callback_query_handler(
    func=lambda call: (call.data or "").startswith(("access:approve:", "access:deny:"))
)
def handle_access_decision(call: types.CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Chỉ quản trị viên được duyệt.")
        return
    _, action, raw_user_id = call.data.split(":", 2)
    user_id = int(raw_user_id)
    with _access_lock:
        access = _load_access()
        request = access["pending"].pop(str(user_id), None)
        if request is None and action == "approve" and user_id in ALLOWED_USER_IDS:
            bot.answer_callback_query(call.id, "Người dùng này đã có quyền.")
            return
        info = request or {"name": f"User {user_id}", "chat_id": user_id}
        if action == "approve":
            access["approved"][str(user_id)] = {
                "name": info["name"],
                "approved_by": call.from_user.id,
                "at": time.time(),
            }
            access["denied"].pop(str(user_id), None)
            ALLOWED_USER_IDS.add(user_id)
        else:
            access["denied"][str(user_id)] = {"name": info["name"], "at": time.time()}
        _save_access(access)

    approved = action == "approve"
    result = "✅ Đã duyệt" if approved else "❌ Đã từ chối"
    bot.answer_callback_query(call.id, result)
    try:
        bot.edit_message_text(
            f"{result}: {info['name']} (ID {user_id}) – bởi {_describe_user(call.from_user)}",
            call.message.chat.id,
            call.message.message_id,
        )
    except Exception:
        pass
    try:
        if approved:
            bot.send_message(info["chat_id"], "Bạn đã được cấp quyền dùng bot!\n\n" + _help_text())
        else:
            bot.send_message(info["chat_id"], "Yêu cầu cấp quyền của bạn đã bị từ chối.")
    except Exception as exc:
        logger.warning(f"cannot notify user {user_id} about access decision: {exc}")


@bot.message_handler(commands=["nguoidung"])
def handle_list_users(message: types.Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        if _is_authorized(message):
            bot.reply_to(message, "Lệnh chỉ dành cho quản trị viên.")
        return
    with _access_lock:
        access = _load_access()
    lines = [f"Trong config.toml: {', '.join(map(str, sorted(CONFIG_USER_IDS))) or '(trống)'}"]
    lines.append(f"Quản trị viên: {', '.join(map(str, sorted(ADMIN_USER_IDS)))}")
    lines.append(f"\nĐã duyệt qua bot ({len(access['approved'])}):")
    lines += [f"• {item['name']} – {uid}" for uid, item in access["approved"].items()] or ["(chưa có)"]
    lines.append(f"\nĐang chờ duyệt ({len(access['pending'])}):")
    lines += [f"• {item['name']} – {uid}" for uid, item in access["pending"].items()] or ["(không có)"]
    lines.append("\nThu hồi quyền: /thuhoi <user_id>")
    bot.reply_to(message, "\n".join(lines)[:MAX_MESSAGE])


@bot.message_handler(commands=["thuhoi"])
def handle_revoke(message: types.Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        if _is_authorized(message):
            bot.reply_to(message, "Lệnh chỉ dành cho quản trị viên.")
        return
    _, value = _parse_command(message.text)
    if not value.strip().isdigit():
        bot.reply_to(message, "Cú pháp: /thuhoi <user_id>. Xem danh sách bằng /nguoidung.")
        return
    user_id = int(value.strip())
    if user_id in CONFIG_USER_IDS or user_id in ADMIN_USER_IDS:
        bot.reply_to(
            message,
            "Người dùng này được cấp trong config.toml; hãy xoá khỏi allowed_user_ids "
            "rồi khởi động lại bot.",
        )
        return
    with _access_lock:
        access = _load_access()
        removed = access["approved"].pop(str(user_id), None)
        _save_access(access)
    ALLOWED_USER_IDS.discard(user_id)
    if removed:
        bot.reply_to(message, f"Đã thu hồi quyền của {removed['name']} ({user_id}).")
    else:
        bot.reply_to(message, f"User {user_id} không nằm trong danh sách đã duyệt.")


def _parse_command(text: str | None) -> tuple[str | None, str]:
    """Tách '/lenh@TenBot nội dung' thành ('lenh', 'nội dung')."""
    match = _COMMAND_RE.match((text or "").strip())
    if not match:
        return None, (text or "").strip()
    return match.group(1).lower(), match.group(2).strip()


_llm_model = qc.llm_model


def _refresh_config() -> None:
    """Đọc lại config.toml: thiết lập vừa chỉnh trên WebUI có hiệu lực ngay với bot."""
    config.reload_config()

_language_name = qc.language_name
_format_duration = qc.format_duration


def _model_note(high: bool) -> str:
    return f"\nModel AI: {qc.high_model()} (#high)" if high else ""


def _media_from_message(message: types.Message) -> MediaRef | None:
    if message.photo:
        return MediaRef(message.photo[-1].file_id, ".jpg")
    if message.video:
        mime = (message.video.mime_type or "video/mp4").split("/")[-1]
        ext = {"quicktime": "mov"}.get(mime, mime)
        return MediaRef(message.video.file_id, f".{ext}")
    if message.document:
        ext = os.path.splitext(message.document.file_name or "")[1].lower()
        if ext.lstrip(".") in const.FILE_TYPE_IMAGES + const.FILE_TYPE_VIDEOS:
            return MediaRef(message.document.file_id, ext)
    return None


def _edit_status(job: Job, text: str) -> None:
    if job.status_message_id is None:
        return
    try:
        bot.edit_message_text(text, job.chat_id, job.status_message_id)
    except Exception:
        # Telegram từ chối khi nội dung không đổi hoặc tin đã bị xoá; bỏ qua.
        pass


def _queue_note() -> str:
    position = jobs.qsize() + (1 if _running_job else 0)
    return f"Đang chờ {position} video phía trước." if position else "Bắt đầu tạo ngay."


def _enqueue(job: Job, reply_to: int | None = None) -> None:
    """Xếp job vào hàng đợi; báo trạng thái ở tin hiện có hoặc tin mới reply ``reply_to``."""
    note = _queue_note()
    seconds = job.duration or job.preset.default_seconds
    media_note = ""
    if job.media:
        media_note = f"\nHình ảnh: {len(job.media)} tệp của bạn."
        # Mỗi tệp hiển thị tối đa 10 giây; ít hơn mức cần thì phải lặp lại.
        needed = -(-seconds // 10)
        if len(job.media) < needed:
            media_note += (
                f" Nên gửi ít nhất {needed} tệp cho video {_format_duration(seconds)} "
                "để hình ảnh không bị lặp."
            )
    text = (
        f"Đã nhận yêu cầu: {job.preset.title}\n"
        f"Thời lượng: khoảng {_format_duration(seconds)}\n"
        f"Ngôn ngữ: {_language_name(job.language)}{_model_note(job.high)}{media_note}\n{note}"
    )
    if job.status_message_id is None:
        status = bot.send_message(
            job.chat_id, text, reply_to_message_id=reply_to or job.reply_to
        )
        job.status_message_id = status.message_id
    else:
        _edit_status(job, text)
    jobs.put(job)


# ------------------------------------------------- hỏi lại khi thiếu thông tin


def _clarify_or_enqueue(job: Job, user_id: int) -> None:
    """Hỏi lại người dùng khi yêu cầu còn thiếu thông tin quan trọng, ngược lại xếp hàng ngay."""
    try:
        _refresh_config()
        with _llm_model(job.high):
            questions = cp.clarifying_questions(job.preset, job.prompt, len(job.media))
    except Exception:
        logger.exception("failed to check request for clarifying questions")
        questions = []
    if not questions:
        _enqueue(job)
        return
    kind = job.preset.title.split("/")[0].strip().lower()
    lines = [f"Để video {kind} hay và đúng hơn, bạn cho mình biết thêm:\n"]
    lines += [f"{index}. {question}" for index, question in enumerate(questions, start=1)]
    lines.append(
        "\nTrả lời tất cả trong một tin nhắn, hoặc bấm “Tạo luôn” để dùng thông tin hiện có."
    )
    text = "\n".join(lines)
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("Tạo luôn", callback_data="clarify:go"),
        types.InlineKeyboardButton("Huỷ", callback_data="clarify:cancel"),
    )
    with _drafts_lock:
        _drafts[job.status_message_id] = Draft(job, user_id, questions, text)
    try:
        bot.edit_message_text(text, job.chat_id, job.status_message_id, reply_markup=keyboard)
    except Exception:
        logger.exception("failed to send clarifying questions")
        with _drafts_lock:
            _drafts.pop(job.status_message_id, None)
        _enqueue(job)


def _take_draft(chat_id: int, user_id: int, message_id: int | None = None) -> Draft | None:
    """
    Gỡ và trả về yêu cầu đang chờ trả lời của người dùng: đúng tin ``message_id``
    nếu có, ngược lại là yêu cầu mới nhất. Yêu cầu quá hạn bị bỏ.
    """
    now = time.monotonic()
    with _drafts_lock:
        for key, draft in list(_drafts.items()):
            if now - draft.created > CLARIFY_TIMEOUT_SECONDS:
                del _drafts[key]
        keys = [
            key
            for key, draft in _drafts.items()
            if draft.job.chat_id == chat_id
            and draft.user_id == user_id
            and message_id in (None, key)
        ]
        # message_id tăng dần nên khoá lớn nhất là câu hỏi gửi gần nhất.
        return _drafts.pop(max(keys)) if keys else None


def _close_questions(draft: Draft, note: str) -> None:
    """Giữ lại câu hỏi trong lịch sử chat, bỏ nút bấm và ghi kết quả."""
    try:
        bot.edit_message_text(
            f"{draft.text}\n\n→ {note}", draft.job.chat_id, draft.job.status_message_id
        )
    except Exception:
        pass


def _answer_draft(message: types.Message) -> bool:
    """Nhận câu trả lời cho câu hỏi bổ sung; False nếu không có yêu cầu nào đang chờ."""
    user_id = message.from_user.id if message.from_user else 0
    replied = message.reply_to_message.message_id if message.reply_to_message else None
    draft = (replied and _take_draft(message.chat.id, user_id, replied)) or _take_draft(
        message.chat.id, user_id
    )
    if draft is None:
        return False
    job = draft.job
    answer, options = qc.parse_options(message.text or "")
    error = qc.duration_error(options.duration)
    if error:
        with _drafts_lock:
            _drafts[job.status_message_id] = draft
        bot.reply_to(message, error)
        return True
    job.high = job.high or options.high
    if options.post is not None:
        job.post = options.post
    job.aspect = options.aspect or job.aspect
    job.language = options.language or job.language
    job.duration = options.duration or job.duration
    if answer:
        job.prompt = cp.merge_answers(job.prompt, draft.questions, answer)
    _close_questions(draft, "Đã nhận thông tin bổ sung.")
    job.status_message_id = None
    _enqueue(job, reply_to=message.message_id)
    return True


@bot.callback_query_handler(func=lambda call: (call.data or "").startswith("clarify:"))
def handle_clarify_button(call: types.CallbackQuery) -> None:
    chat_id, message_id = call.message.chat.id, call.message.message_id
    draft = _take_draft(chat_id, call.from_user.id, message_id)
    if draft is None:
        with _drafts_lock:
            owned_by_other = message_id in _drafts
        if owned_by_other:
            bot.answer_callback_query(call.id, "Chỉ người gửi yêu cầu mới bấm được.")
            return
        bot.answer_callback_query(call.id, "Yêu cầu này đã được xử lý hoặc đã hết hạn.")
        try:
            bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
        except Exception:
            pass
        return
    if call.data == "clarify:cancel":
        _close_questions(draft, "Đã huỷ yêu cầu.")
        bot.answer_callback_query(call.id, "Đã huỷ")
        return
    _close_questions(draft, "Tạo luôn với thông tin hiện có.")
    bot.answer_callback_query(call.id, "Đã xếp hàng")
    draft.job.status_message_id = None
    _enqueue(draft.job)


def _submit(message: types.Message, command: str, prompt: str, media=None) -> None:
    preset = cp.PRESETS_BY_COMMAND[command]
    prompt, options = qc.parse_options(prompt)
    gif, high, aspect = options.gif, options.high, options.aspect
    language, duration = options.language, options.duration
    error = qc.duration_error(duration)
    if error:
        bot.reply_to(message, error)
        return
    if duration is None and message.from_user:
        duration = _get_user_duration(message.from_user.id)
    if language is None:
        language = (
            _get_user_language(message.from_user.id)
            if message.from_user
            else qc.default_language()
        )
    error = qc.request_error(preset, prompt, len(media or []), gif)
    if error:
        if gif and media and not preset.requires_media:
            error += " Hãy gửi lệnh dạng chữ, ví dụ: /dongluc Kiên trì mỗi ngày #gif"
        bot.reply_to(message, error)
        return
    job = Job(
        chat_id=message.chat.id,
        reply_to=message.message_id,
        preset=preset,
        prompt=prompt,
        aspect=aspect,
        duration=duration,
        media=list(media or []),
        language=language,
        gif=gif,
        high=high,
        post=options.post,
    )
    if gif:
        # Ảnh GIF chỉ có một câu ngắn nên không hỏi lại, và không xếp sau video dài.
        _start_gif(job)
        return
    if not preset.clarify:
        _enqueue(job)
        return
    # Gọi AI mất vài giây nên chạy ở luồng riêng, không chặn bot nhận tin khác.
    job.status_message_id = bot.reply_to(message, "Đang xem yêu cầu của bạn...").message_id
    user_id = message.from_user.id if message.from_user else 0
    threading.Thread(target=_clarify_or_enqueue, args=(job, user_id), daemon=True).start()


# ------------------------------- loạt video hoặc ảnh GIF theo một chủ đề lớn

_REDO_FEEDBACK = "Đề xuất danh sách mới, các chủ đề con khác hẳn danh sách trên."


def _batch_usage() -> str:
    return (
        "Tạo hàng loạt video hoặc ảnh GIF theo một chủ đề: AI đề xuất các chủ đề con "
        "kèm ý chính, bạn duyệt xong bot mới tạo và gửi lần lượt từng mục.\n"
        "Cú pháp: /hangloat <loại> <chủ đề> [#số lượng] [#gif] [#high]\n"
        f"Loại: {', '.join(BATCH_PRESETS)}\n"
        f"Mặc định {DEFAULT_BATCH_SIZE} mục, tối đa {cp.MAX_BATCH_TOPICS}. "
        "Dùng được #45s, #2p, #ngang, #en như lệnh thường; thêm #gif để tạo ảnh GIF "
        f"có chữ, không lồng tiếng; thêm #high để AI dùng model {qc.high_model()}.\n"
        "Ví dụ: /hangloat meo tiết kiệm tiền cho sinh viên #15\n"
        "Ví dụ: /hangloat dongluc kiên trì mỗi ngày #10 #gif"
    )


def _unit(batch: Batch) -> str:
    """Tên loại nội dung của loạt trong các tin trạng thái."""
    return "ảnh GIF" if batch.gif else "video"


def _job_title(job: Job) -> str:
    """Tên job trong tin trạng thái; video trong loạt kèm số thứ tự và chủ đề con."""
    if job.batch:
        return f"[{job.batch_number}/{len(job.batch.topics)}] {cp.cover_title(job.prompt)}"
    return job.preset.title


def _plan_chunks(batch: Batch, note: str = "") -> list[str]:
    """Danh sách chủ đề con, chia thành các tin trong giới hạn độ dài của Telegram."""
    seconds = batch.duration or batch.preset.default_seconds
    if batch.gif:
        shape = f"Ảnh GIF có chữ, không lồng tiếng, khung hình {batch.aspect or '9:16'}."
    else:
        shape = f"Mỗi video khoảng {_format_duration(seconds)}, khung hình {batch.aspect or '9:16'}."
    header = "\n".join(
        line
        for line in (
            note,
            f"Đề xuất {len(batch.topics)} {_unit(batch)} /{batch.preset.command} "
            f"({batch.preset.title})",
            f"Chủ đề: {cp.cover_title(batch.theme, 200)}",
            shape,
            f"Ngôn ngữ: {_language_name(batch.language)}",
            f"Model AI: {qc.high_model()} (#high)" if batch.high else "",
        )
        if line
    )
    items = [
        f"{index}. {topic.title}" + (f"\n   {topic.content}" if topic.content else "")
        for index, topic in enumerate(batch.topics, start=1)
    ]
    footer = (
        "Bấm “Duyệt & tạo” để bắt đầu, “Đề xuất lại” để AI làm danh sách khác. "
        "Muốn chỉnh thì nhắn góp ý, ví dụ: bỏ số 3, thêm chủ đề về tiền điện."
    )
    chunks: list[str] = []
    for block in (header, *items, footer):
        if chunks and len(chunks[-1]) + 2 + len(block) <= MAX_MESSAGE:
            chunks[-1] += "\n\n" + block
        else:
            chunks.append(block[:MAX_MESSAGE])
    return chunks


def _plan_keyboard(batch_id: str) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("✅ Duyệt & tạo", callback_data=f"batch:go:{batch_id}")
    )
    keyboard.add(
        types.InlineKeyboardButton("🔄 Đề xuất lại", callback_data=f"batch:redo:{batch_id}"),
        types.InlineKeyboardButton("❌ Huỷ", callback_data=f"batch:cancel:{batch_id}"),
    )
    return keyboard


def _show_plan(batch: Batch, note: str = "") -> None:
    """Gửi danh sách chờ duyệt, thay tin “Đang đề xuất...” bằng phần đầu danh sách."""
    chunks = _plan_chunks(batch, note)
    placeholder = batch.plan_message_ids[0] if batch.plan_message_ids else None
    message_ids = []
    for index, text in enumerate(chunks):
        markup = _plan_keyboard(batch.id) if index == len(chunks) - 1 else None
        if index == 0 and placeholder is not None:
            try:
                bot.edit_message_text(text, batch.chat_id, placeholder, reply_markup=markup)
                message_ids.append(placeholder)
                continue
            except Exception:
                pass
        message_ids.append(bot.send_message(batch.chat_id, text, reply_markup=markup).message_id)
    batch.plan_message_ids = message_ids
    batch.plan_text = chunks[-1]


def _close_plan(batch: Batch, note: str) -> None:
    """Giữ danh sách trong lịch sử chat, bỏ nút bấm và ghi kết quả."""
    if not batch.plan_message_ids or not batch.plan_text:
        return
    try:
        bot.edit_message_text(
            f"{batch.plan_text}\n\n→ {note}", batch.chat_id, batch.plan_message_ids[-1]
        )
    except Exception:
        pass


def _claim_plan(batch: Batch, approve: bool = False) -> bool:
    """Giữ danh sách cho một thao tác; False nếu đang đề xuất, đã duyệt hoặc đã huỷ."""
    with _batches_lock:
        if batch.busy or batch.approved or batch.id not in _batches:
            return False
        if approve:
            batch.approved = True
        else:
            batch.busy = True
        return True


def _propose_topics(batch: Batch, feedback: str = "") -> None:
    """Gọi AI đề xuất (hoặc sửa theo góp ý) danh sách chủ đề con rồi gửi để duyệt."""
    try:
        try:
            _refresh_config()
            with _llm_model(batch.high):
                topics = cp.generate_subtopics(
                    batch.preset,
                    batch.theme,
                    len(batch.topics) if feedback else batch.count,
                    batch.topics,
                    feedback,
                )
        except Exception:
            logger.exception("failed to generate batch subtopics")
            topics = []
        if topics:
            note = ""
            if not feedback and len(topics) < batch.count:
                note = f"AI chỉ đề xuất được {len(topics)}/{batch.count} chủ đề con."
            batch.topics = topics
            _show_plan(batch, note)
        elif batch.topics:
            _show_plan(batch, "Chưa đề xuất lại được, vẫn giữ danh sách trước.")
        else:
            with _batches_lock:
                _batches.pop(batch.id, None)
            text = "Không đề xuất được chủ đề con (AI không trả lời). Hãy gửi lại lệnh sau ít phút."
            try:
                bot.edit_message_text(text, batch.chat_id, batch.plan_message_ids[0])
            except Exception:
                bot.send_message(batch.chat_id, text)
    except Exception:
        logger.exception("failed to show batch subtopics")
    finally:
        batch.busy = False


def _find_plan(chat_id: int, user_id: int, message_id: int | None = None) -> Batch | None:
    """
    Danh sách chờ duyệt của người dùng: danh sách chứa tin ``message_id`` nếu có,
    ngược lại là danh sách mới nhất. Danh sách quá hạn bị bỏ.
    """
    now = time.monotonic()
    with _batches_lock:
        for key, batch in list(_batches.items()):
            if not batch.approved and now - batch.created > BATCH_PLAN_TIMEOUT_SECONDS:
                del _batches[key]
        plans = [
            batch
            for batch in _batches.values()
            if not batch.approved
            and batch.chat_id == chat_id
            and batch.user_id == user_id
            and (message_id is None or message_id in batch.plan_message_ids)
        ]
    return max(plans, key=lambda batch: batch.created) if plans else None


def _revise_plan(message: types.Message, batch: Batch) -> None:
    """Tin nhắn của người dùng khi danh sách đang chờ duyệt là góp ý để sửa danh sách."""
    if not _claim_plan(batch):
        bot.reply_to(message, "Danh sách đang được đề xuất lại, vui lòng chờ.")
        return
    _close_plan(batch, "Đã nhận góp ý.")
    batch.plan_message_ids = [
        bot.reply_to(message, "Đang sửa danh sách chủ đề con theo góp ý...").message_id
    ]
    threading.Thread(
        target=_propose_topics, args=(batch, message.text or ""), daemon=True
    ).start()


@bot.message_handler(commands=["hangloat"])
def handle_batch_command(message: types.Message) -> None:
    if not _is_authorized(message):
        return
    _, value = _parse_command(message.text)
    value, options = qc.parse_options(value, batch=True)
    gif, high, aspect = options.gif, options.high, options.aspect
    language, duration, count = options.language, options.duration, options.count
    parts = value.split(None, 1)
    preset = BATCH_PRESETS.get(parts[0].lstrip("/").lower()) if parts else None
    if preset is None:
        bot.reply_to(message, _batch_usage())
        return
    theme = parts[1] if len(parts) > 1 else ""
    error = qc.duration_error(duration)
    if error:
        bot.reply_to(message, error)
        return
    if count is not None and not 1 <= count <= cp.MAX_BATCH_TOPICS:
        kind = "ảnh GIF" if gif else "video"
        bot.reply_to(message, f"Số {kind} phải từ 1 đến {cp.MAX_BATCH_TOPICS}. Ví dụ: #15.")
        return
    if len(theme) < preset.min_prompt_length:
        bot.reply_to(message, _batch_usage())
        return
    user_id = message.from_user.id
    batch = Batch(
        id=uuid4().hex[:12],
        chat_id=message.chat.id,
        user_id=user_id,
        preset=preset,
        theme=theme,
        count=count or DEFAULT_BATCH_SIZE,
        aspect=aspect,
        duration=duration or _get_user_duration(user_id),
        language=language or _get_user_language(user_id),
        gif=gif,
        high=high,
        post=options.post,
        busy=True,
    )
    status = bot.reply_to(
        message,
        f"Đang đề xuất {batch.count} chủ đề con cho /{preset.command}"
        f"{' (ảnh GIF)' if gif else ''}...{_model_note(high)}",
    )
    batch.plan_message_ids = [status.message_id]
    with _batches_lock:
        _batches[batch.id] = batch
    # Gọi AI mất vài giây nên chạy ở luồng riêng, không chặn bot nhận tin khác.
    threading.Thread(target=_propose_topics, args=(batch,), daemon=True).start()


def _stop_keyboard(batch: Batch) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(
            f"⏹ Dừng sau {_unit(batch)} đang tạo", callback_data=f"batch:stop:{batch.id}"
        )
    )
    return keyboard


def _batch_progress_text(batch: Batch) -> str:
    total = len(batch.topics)
    seconds = batch.duration or batch.preset.default_seconds
    unit = _unit(batch)
    progress = f"Đã gửi {batch.sent}/{total}"
    if batch.failed:
        progress += f", lỗi {len(batch.failed)} (số {', '.join(map(str, batch.failed))})"
    if batch.gif:
        kind = "có chữ, không lồng tiếng."
    else:
        kind = f"mỗi video khoảng {_format_duration(seconds)}."
    lines = [
        f"Loạt {total} {unit} /{batch.preset.command} ({batch.preset.title}), {kind}",
        f"Chủ đề: {cp.cover_title(batch.theme, 200)}",
        f"Ngôn ngữ: {_language_name(batch.language)}",
        progress + ".",
    ]
    done = batch.sent + len(batch.failed)
    if batch.finished:
        lines.append("Đã dừng theo yêu cầu." if batch.stopped else "Đã hoàn tất.")
    elif batch.stopped:
        lines.append(f"Sẽ dừng sau {unit} đang tạo.")
    else:
        if done:
            minutes = (time.monotonic() - batch.started) / done * (total - done) / 60
            eta = f"{minutes / 60:.1f} giờ" if minutes >= 60 else f"{max(round(minutes), 1)} phút"
            lines.append(f"Còn lại khoảng {eta}.")
        lines.append(
            f"{'Ảnh GIF' if batch.gif else 'Video'} được gửi lần lượt khi xong. Bấm nút "
            f"bên dưới hoặc gõ /dunghangloat để dừng sau {unit} đang tạo."
        )
    return "\n".join(lines)


def _show_batch_status(batch: Batch) -> None:
    text = _batch_progress_text(batch)
    markup = None if batch.finished or batch.stopped else _stop_keyboard(batch)
    try:
        if batch.status_message_id is None:
            message = bot.send_message(batch.chat_id, text, reply_markup=markup)
            batch.status_message_id = message.message_id
        else:
            bot.edit_message_text(
                text, batch.chat_id, batch.status_message_id, reply_markup=markup
            )
    except Exception:
        # Telegram từ chối khi nội dung không đổi; lỗi mạng cũng không được chặn loạt video.
        pass


def _continue_batch(batch: Batch) -> None:
    """
    Xếp video kế tiếp của loạt vào cuối hàng đợi; hết video hoặc đã dừng thì báo
    tổng kết. Mỗi lúc loạt chỉ giữ một chỗ trong hàng đợi, nên yêu cầu của người
    khác gửi trong lúc chạy được xen vào giữa thay vì chờ cả loạt.
    """
    if batch.stopped or batch.next_index >= len(batch.topics):
        _finish_batch(batch)
        return
    topic = batch.topics[batch.next_index]
    batch.next_index += 1
    job = Job(
        chat_id=batch.chat_id,
        reply_to=None,
        preset=batch.preset,
        prompt=topic.prompt(),
        aspect=batch.aspect,
        duration=batch.duration,
        language=batch.language,
        batch=batch,
        batch_number=batch.next_index,
        gif=batch.gif,
        high=batch.high,
        post=batch.post,
    )
    _show_batch_status(batch)
    try:
        job.status_message_id = bot.send_message(
            batch.chat_id, f"{_job_title(job)}\n{_queue_note()}"
        ).message_id
    except Exception as exc:
        logger.warning(f"cannot send batch item status: {exc}")
    jobs.put(job)


def _start_batch(batch: Batch) -> None:
    batch.started = time.monotonic()
    logger.info(
        f"telegram batch {batch.id}: {len(batch.topics)} {'gifs' if batch.gif else 'videos'} "
        f"/{batch.preset.command} – {batch.theme[:100]}"
    )
    _continue_batch(batch)


def _finish_batch(batch: Batch) -> None:
    with _batches_lock:
        if batch.finished:
            return
        batch.finished = True
        _batches.pop(batch.id, None)
    if batch.status_message_id is not None:
        _show_batch_status(batch)
    total = len(batch.topics)
    unit = _unit(batch)
    verb = "Đã dừng" if batch.stopped else "Hoàn tất"
    lines = [f"{verb} loạt /{batch.preset.command}: đã gửi {batch.sent}/{total} {unit}."]
    skipped = total - batch.sent - len(batch.failed)
    if skipped:
        lines.append(f"Chưa tạo {skipped} {unit}.")
    if batch.failed:
        lines.append(
            f"Lỗi {len(batch.failed)} {unit}, có thể tạo lại từng {unit} bằng "
            f"/{batch.preset.command} <chủ đề>{' #gif' if batch.gif else ''}:"
        )
        lines += [f"{number}. {batch.topics[number - 1].title}" for number in batch.failed]
    logger.info(f"telegram batch {batch.id} finished: {lines[0]}")
    bot.send_message(batch.chat_id, "\n".join(lines)[:MAX_MESSAGE])


def _stop_batch(batch: Batch) -> None:
    """Dừng loạt sau video đang tạo; video còn chờ trong hàng đợi bị bỏ."""
    batch.stopped = True
    # Đặt stopped trước rồi mới xem _running_job: worker đặt _running_job trước
    # khi kiểm tra stopped, nên một trong hai bên chắc chắn thấy bên kia.
    running = _running_job
    if running is not None and running.batch is batch:
        _show_batch_status(batch)
    else:
        _finish_batch(batch)


@bot.callback_query_handler(func=lambda call: (call.data or "").startswith("batch:"))
def handle_batch_button(call: types.CallbackQuery) -> None:
    _, action, batch_id = call.data.split(":", 2)
    with _batches_lock:
        batch = _batches.get(batch_id)
    if batch is None:
        bot.answer_callback_query(call.id, "Loạt này đã xong, đã huỷ hoặc đã hết hạn.")
        try:
            bot.edit_message_reply_markup(
                call.message.chat.id, call.message.message_id, reply_markup=None
            )
        except Exception:
            pass
        return
    if call.from_user.id != batch.user_id:
        bot.answer_callback_query(call.id, "Chỉ người gửi yêu cầu mới bấm được.")
        return
    if action == "stop":
        _stop_batch(batch)
        bot.answer_callback_query(call.id, "Đã dừng")
        return
    if not _claim_plan(batch, approve=action == "go"):
        bot.answer_callback_query(call.id, "Danh sách đang được xử lý, vui lòng chờ.")
        return
    if action == "go":
        _close_plan(batch, f"Đã duyệt, bắt đầu tạo {_unit(batch)}.")
        bot.answer_callback_query(call.id, "Bắt đầu tạo")
        _start_batch(batch)
    elif action == "redo":
        _close_plan(batch, "Đã yêu cầu đề xuất lại.")
        bot.answer_callback_query(call.id, "Đang đề xuất lại")
        status = bot.send_message(batch.chat_id, "Đang đề xuất lại danh sách chủ đề con...")
        batch.plan_message_ids = [status.message_id]
        threading.Thread(
            target=_propose_topics, args=(batch, _REDO_FEEDBACK), daemon=True
        ).start()
    else:
        with _batches_lock:
            _batches.pop(batch.id, None)
        _close_plan(batch, "Đã huỷ.")
        bot.answer_callback_query(call.id, "Đã huỷ")


@bot.message_handler(commands=["dunghangloat"])
def handle_stop_batch(message: types.Message) -> None:
    if not _is_authorized(message):
        return
    with _batches_lock:
        running = [
            batch
            for batch in _batches.values()
            if batch.approved
            and not batch.stopped
            and batch.chat_id == message.chat.id
            and batch.user_id == message.from_user.id
        ]
    if not running:
        bot.reply_to(message, "Bạn không có loạt nào đang chạy.")
        return
    for batch in running:
        _stop_batch(batch)
    bot.reply_to(
        message,
        f"Đã dừng {len(running)} loạt. Mục đang tạo (nếu có) vẫn được gửi xong.",
    )


# ------------------------------------- đăng Facebook Reels, TikTok, YouTube

_WHEN_RE = re.compile(
    r"(?<!\S)(?:(\d{1,2}/\d{1,2}(?:/\d{4})?)\s+)?(\d{1,2}[:h]\d{2})(?!\S)|(?<!\S)(ngay|now)(?!\S)",
    re.IGNORECASE,
)
_NUMBERS_RE = re.compile(r"^\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*$")
_DRY_RUN_RE = re.compile(r"#(?:thu|thử)\b", re.IGNORECASE)


def _platform_names(platforms) -> str:
    return ", ".join(sp.PLATFORM_NAMES[name] for name in platforms)


def _dang_usage() -> str:
    settings = social_schedule.get_settings()
    latest = social_schedule.library_videos()[:8]
    lines = [
        "Lên lịch đăng video trong thư mục thành phẩm lên Facebook Reels, TikTok, YouTube.",
        "Cú pháp: /dang <số video> [fb tt yt] [ngay | 20:00 | 21/10 20:00] [#thu]",
        "Ví dụ: /dang 105 – vào khung giờ trống kế tiếp, các nền tảng mặc định",
        "/dang 105-110 tt yt – mỗi video một khung giờ",
        "/dang 105 fb ngay – đăng ngay; #thu: chạy thử, điền xong không bấm Đăng",
        f"Nền tảng mặc định: {_platform_names(settings['platforms'])}. "
        f"Khung giờ: {', '.join(settings['slots']) or 'không có (đăng ngay)'}.",
        "Lần đầu dùng: /dangnhap để đăng nhập các trang trong trình duyệt đăng bài.",
    ]
    if latest:
        lines.append("\nVideo mới nhất:")
        lines += [f"{name}" for _, name, _ in latest]
    return "\n".join(lines)


def _expand_numbers(spec: str) -> list[int]:
    numbers = []
    for part in spec.split(","):
        first, _, last = part.partition("-")
        start, end = int(first), int(last or first)
        numbers += list(range(min(start, end), max(start, end) + 1))
    return list(dict.fromkeys(numbers))[:30]


@bot.message_handler(commands=["dang"])
def handle_post(message: types.Message) -> None:
    if not _is_authorized(message):
        return
    _, value = _parse_command(message.text)
    if not value:
        bot.reply_to(message, _dang_usage())
        return
    dry_run = bool(_DRY_RUN_RE.search(value))
    value = _DRY_RUN_RE.sub(" ", value)
    run_at = None
    when = _WHEN_RE.search(value)
    if when:
        run_at = social_schedule.parse_when(
            when.group(3) or " ".join(part for part in when.group(1, 2) if part)
        )
        if run_at is None:
            bot.reply_to(message, "Không hiểu thời gian. Ví dụ: ngay, 20:00, 21/10 20:00.")
            return
        value = value[: when.start()] + " " + value[when.end():]
    numbers, platforms, unknown = [], [], []
    for token in value.split():
        if _NUMBERS_RE.match(token.lstrip("#")):
            numbers += _expand_numbers(token.lstrip("#"))
        elif token.lower() in sp.PLATFORM_ALIASES:
            platforms.append(token)
        else:
            unknown.append(token)
    if unknown or not numbers:
        note = f"Không hiểu: {' '.join(unknown)}\n\n" if unknown else ""
        bot.reply_to(message, note + _dang_usage())
        return
    lines, missing = [], []
    for number in numbers:
        path = social_schedule.find_video(number)
        if not path:
            missing.append(str(number))
            continue
        try:
            entry = social_schedule.schedule(
                path, platforms or None, run_at, source="telegram",
                chat_id=message.chat.id, dry_run=dry_run,
            )
        except ValueError as exc:
            bot.reply_to(message, str(exc))
            return
        lines.append(social_schedule.describe(entry))
    if lines:
        lines.insert(0, "Đã lên lịch đăng (kết quả sẽ báo ở đây; /lichdang để xem, huỷ):")
        chosen = (
            social_schedule.normalize_platforms(platforms)
            or social_schedule.get_settings()["platforms"]
        )
        lines.append("\nĐăng lên:\n" + _accounts_text(chosen))
        if any(name not in social_accounts.confirmed() for name in chosen):
            lines.append("Xác nhận trang/kênh còn thiếu bằng /dangnhap kiemtra trước giờ đăng.")
    if missing:
        lines.append(f"Không có video số {', '.join(missing)} trong thư mục thành phẩm.")
    bot.reply_to(message, "\n".join(lines)[:MAX_MESSAGE])


def _schedule_view() -> tuple[str, types.InlineKeyboardMarkup | None]:
    entries = social_schedule.entries()
    upcoming = [
        entry for entry in entries
        if social_schedule.entry_status(entry) in (social_schedule.PENDING, social_schedule.RUNNING)
    ][:10]
    finished = [entry for entry in entries if entry not in upcoming][-5:]
    lines = []
    if upcoming:
        lines.append("Sắp đăng:")
        lines += [f"{index}. {social_schedule.describe(entry)}" for index, entry in enumerate(upcoming, 1)]
    else:
        lines.append("Không có bài nào đang chờ đăng.")
    if finished:
        lines.append("\nGần đây:")
        for entry in finished:
            lines.append(social_schedule.describe(entry))
            errors = [t["error"] for t in entry["targets"].values() if t["status"] == social_schedule.FAILED]
            if errors:
                lines.append(f"   Lỗi: {errors[0][:200]}")
    settings = social_schedule.get_settings()
    lines.append(
        f"\nĐăng tự động video mới: {'bật' if settings['auto_post'] else 'tắt'} (/tudongdang)."
    )
    lines.append("Trang/kênh đăng bài:\n" + _accounts_text())
    keyboard = None
    if upcoming:
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        for index, entry in enumerate(upcoming, 1):
            keyboard.add(
                types.InlineKeyboardButton(f"▶ Đăng ngay {index}", callback_data=f"post:now:{entry['id']}"),
                types.InlineKeyboardButton(f"✖ Huỷ {index}", callback_data=f"post:cancel:{entry['id']}"),
            )
    return "\n".join(lines)[:MAX_MESSAGE], keyboard


@bot.message_handler(commands=["lichdang"])
def handle_schedule(message: types.Message) -> None:
    if not _is_authorized(message):
        return
    text, keyboard = _schedule_view()
    bot.reply_to(message, text, reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: (call.data or "").startswith("post:"))
def handle_schedule_button(call: types.CallbackQuery) -> None:
    if call.from_user.id not in ALLOWED_USER_IDS:
        bot.answer_callback_query(call.id, "Bạn chưa có quyền dùng bot này.")
        return
    _, action, entry_id = call.data.split(":", 2)
    entry = social_schedule.run_now(entry_id) if action == "now" else social_schedule.cancel(entry_id)
    if entry is None:
        bot.answer_callback_query(call.id, "Bài này không còn trong lịch.")
    else:
        bot.answer_callback_query(call.id, "Sẽ đăng trong ít phút" if action == "now" else "Đã huỷ")
    text, keyboard = _schedule_view()
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=keyboard)
    except Exception:
        pass


@bot.message_handler(commands=["tudongdang"])
def handle_auto_post(message: types.Message) -> None:
    if not _is_authorized(message):
        return
    _, value = _parse_command(message.text)
    changes: dict = {}
    slots, platforms, unknown = [], [], []
    for token in value.replace(",", " ").split():
        word = token.lower()
        if word in ("bat", "bật", "on"):
            changes["auto_post"] = True
        elif word in ("tat", "tắt", "off"):
            changes["auto_post"] = False
        elif word in sp.PLATFORM_ALIASES:
            platforms.append(word)
        elif social_schedule.normalize_slots([token]):
            slots.append(token)
        else:
            unknown.append(token)
    if unknown:
        bot.reply_to(message, f"Không hiểu: {' '.join(unknown)}")
        return
    if slots:
        changes["slots"] = slots
    if platforms:
        changes["platforms"] = platforms
    settings = (
        social_schedule.save_settings(**changes) if changes else social_schedule.get_settings()
    )
    bot.reply_to(
        message,
        f"Đăng tự động video mới tạo: {'BẬT' if settings['auto_post'] else 'TẮT'}\n"
        f"Nền tảng: {_platform_names(settings['platforms'])}\n"
        f"Khung giờ mỗi ngày: {', '.join(settings['slots']) or 'không có (đăng ngay)'}\n\n"
        "Đổi: /tudongdang bat|tat [8:00 12:00 19:30] [fb tt yt]. Riêng một yêu cầu: thêm "
        "#dang hoặc #khongdang vào nội dung (cả /hangloat).",
    )


def _accounts_text(platforms=sp.PLATFORMS) -> str:
    """Trang/kênh đã xác nhận; bài chỉ được đăng lên đúng các tài khoản này."""
    accounts = social_accounts.confirmed()
    return "\n".join(
        f"{sp.PLATFORM_NAMES[name]}: "
        + (f"✅ {accounts[name].label()}" if name in accounts else "⚠️ chưa xác nhận – sẽ không đăng")
        for name in platforms
    )


def _report_login(chat_id: int, message_id: int) -> None:
    try:
        found = social_accounts.check_and_save()
        notes = []
        for name, value in found.items():
            if isinstance(value, str):
                notes.append(f"{sp.PLATFORM_NAMES[name]}: không đọc được ({value}), giữ xác nhận cũ.")
            elif value is None:
                notes.append(f"{sp.PLATFORM_NAMES[name]}: chưa đăng nhập.")
        text = (
            "Đã lưu trang/kênh đăng bài (lần đăng sau mà trình duyệt ở tài khoản khác sẽ "
            "không đăng):\n" + _accounts_text()
        )
        if notes:
            text += "\n\n" + "\n".join(notes)
    except Exception as exc:
        text = f"Không kiểm tra được: {exc}"
    try:
        bot.edit_message_text(text, chat_id, message_id)
    except Exception:
        bot.send_message(chat_id, text)


@bot.message_handler(commands=["dangnhap"])
def handle_login(message: types.Message) -> None:
    if not _is_authorized(message):
        return
    _, value = _parse_command(message.text)
    if value.strip().lower() in ("kiemtra", "kiểm tra", "check"):
        status = bot.reply_to(message, "Đang kiểm tra đăng nhập...")
        threading.Thread(
            target=_report_login, args=(message.chat.id, status.message_id), daemon=True
        ).start()
        return
    try:
        social_browser.open_login_pages()
    except social_browser.BrowserError as exc:
        bot.reply_to(message, str(exc))
        return
    bot.reply_to(
        message,
        "Đã mở trình duyệt đăng bài trên máy chạy bot, với các trang Facebook, TikTok, "
        "YouTube Studio. Đăng nhập một lần trong cửa sổ đó (đây là profile riêng: "
        f"{social_browser.profile_dir()}); bot dùng lại phiên đăng nhập này để đăng bài. "
        "Facebook: muốn đăng lên Trang thì chuyển sang hồ sơ của Trang đó. YouTube: chọn đúng "
        "kênh trong YouTube Studio. Xong gõ /dangnhap kiemtra để lưu trang/kênh đăng bài – "
        "bot chỉ đăng khi trình duyệt đang ở đúng các tài khoản này.",
    )


# ---------------------------------------------------------------- lệnh


def _media_commands() -> str:
    return " hoặc ".join(
        f"/{preset.command}" for preset in cp.PRESETS.values() if preset.accepts_media
    )


def _clarify_commands() -> str:
    return ", ".join(f"/{preset.command}" for preset in cp.PRESETS.values() if preset.clarify)


def _help_text() -> str:
    lines = ["Bot tạo video ngắn tự động. Các lệnh:\n"]
    for preset in cp.PRESETS.values():
        lines.append(f"/{preset.command} – {preset.title}")
        lines.append(f"   {preset.description}")
        lines.append(f"   Ví dụ: {preset.example}\n")
    lines.append(
        "Tuỳ chọn khung hình: thêm #ngang (16:9), #vuong (1:1) hoặc #doc (9:16, mặc định) "
        "vào nội dung.\n"
        f"Thời lượng: thêm #45s hoặc #2p vào nội dung ({cp.MIN_DURATION_SECONDS} giây – "
        f"{cp.MAX_DURATION_SECONDS // 60} phút), hoặc đặt mặc định bằng /thoiluong.\n"
        "Ngôn ngữ: thêm #en (lời đọc tiếng Anh, phụ đề tiếng Việt) hoặc #vi vào nội dung, "
        "hoặc đặt mặc định bằng /ngonngu.\n"
        f"Model AI: mặc định theo config.toml; thêm #high để AI viết bằng model {qc.high_model()} "
        "(logic và chất lượng tốt hơn).\n"
        "Ví dụ: /meo 5 mẹo ngủ ngon #90s #ngang\n"
        "Ảnh GIF có chữ, không lồng tiếng: thêm #gif, ví dụ /dongluc Kiên trì mỗi ngày #gif. "
        "Bot chọn clip Pixabay sát nghĩa nhất, chưa dùng ở ảnh GIF trước, rồi chèn câu AI "
        "viết (cũng là tiêu đề) với màu dễ đọc nhất; caption kèm lời diễn giải chi tiết hơn "
        "(dùng được với #doc, #vuong, #ngang, #en, #high và /hangloat; không dùng với "
        "/sanpham).\n"
        "Dùng ảnh/video riêng: gửi ảnh hoặc album, caption bắt đầu bằng "
        f"{_media_commands()} <mô tả> (bắt buộc với /sanpham).\n"
        f"Nếu yêu cầu còn thiếu thông tin quan trọng, {_clarify_commands()} sẽ hỏi lại "
        "vài câu: trả lời trong một tin nhắn hoặc bấm “Tạo luôn”.\n"
        "Mỗi video gửi kèm sẵn tiêu đề, mô tả và hashtag chuẩn SEO để đăng TikTok, "
        "YouTube Shorts, Facebook Reels.\n"
        f"/hangloat <loại> <chủ đề> [#số lượng] [#gif] – AI đề xuất {DEFAULT_BATCH_SIZE} "
        "chủ đề con (hoặc số bạn chọn) kèm ý chính, bạn duyệt rồi bot tạo lần lượt video, "
        "hoặc ảnh GIF nếu có #gif. Ví dụ: /hangloat meo tiết kiệm tiền cho sinh viên #15, "
        "/hangloat dongluc kiên trì mỗi ngày #10 #gif\n"
        "/trangthai – xem hàng đợi.\n\n"
        "Đăng Facebook Reels, TikTok, YouTube Shorts (qua trình duyệt đăng bài trên máy):\n"
        "/dangnhap – mở trình duyệt để đăng nhập các trang lần đầu; /dangnhap kiemtra.\n"
        "/dang <số video> [fb tt yt] [ngay | 20:00 | 21/10 20:00] [#thu] – lên lịch đăng "
        "video trong thư mục thành phẩm, ví dụ /dang 105-110 tt yt.\n"
        "/lichdang – xem lịch, đăng ngay hoặc huỷ.\n"
        "/tudongdang bat|tat [8:00 12:00 19:30] [fb tt yt] – tự đăng video mới tạo vào các "
        "khung giờ trống. Riêng một yêu cầu: thêm #dang hoặc #khongdang."
    )
    return "\n".join(lines)


@bot.message_handler(commands=["start", "help"])
def handle_help(message: types.Message) -> None:
    if _is_authorized(message):
        bot.reply_to(message, _help_text())


@bot.message_handler(commands=["trangthai"])
def handle_status(message: types.Message) -> None:
    if not _is_authorized(message):
        return
    running = (
        f"Đang tạo: {_running_job.preset.title} – {_running_job.prompt[:60]}"
        if _running_job
        else "Không có video nào đang tạo."
    )
    with _batches_lock:
        batches = [batch for batch in _batches.values() if batch.approved]
    lines = [f"{running}\nĐang chờ: {jobs.qsize()} yêu cầu."]
    for batch in batches:
        failed = f", lỗi {len(batch.failed)}" if batch.failed else ""
        lines.append(
            f"Loạt /{batch.preset.command}{' (GIF)' if batch.gif else ''}: đã gửi "
            f"{batch.sent}/{len(batch.topics)}{failed} – {batch.theme[:60]}"
        )
    bot.reply_to(message, "\n".join(lines))


def _duration_keyboard() -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup(row_width=4)
    keyboard.add(
        *[
            types.InlineKeyboardButton(label, callback_data=f"duration:{seconds}")
            for label, seconds in (
                ("30 giây", 30), ("45 giây", 45), ("1 phút", 60), ("90 giây", 90),
                ("2 phút", 120), ("3 phút", 180), ("Mặc định", 0),
            )
        ]
    )
    return keyboard


def _duration_summary(user_id: int) -> str:
    seconds = _get_user_duration(user_id)
    if seconds:
        return f"Thời lượng mặc định của bạn: {_format_duration(seconds)}."
    defaults = ", ".join(
        f"/{p.command} {_format_duration(p.default_seconds)}" for p in cp.PRESETS.values()
    )
    return f"Đang dùng thời lượng riêng của từng loại: {defaults}."


@bot.message_handler(commands=["thoiluong"])
def handle_duration(message: types.Message) -> None:
    if not _is_authorized(message):
        return
    _, value = _parse_command(message.text)
    if not value:
        bot.reply_to(
            message,
            f"{_duration_summary(message.from_user.id)}\n\n"
            "Chọn thời lượng mặc định cho các video sau, hoặc gõ /thoiluong 75 "
            "(giây), /thoiluong 2p (phút). Muốn đổi riêng một video thì thêm #45s "
            "hoặc #2p vào nội dung.",
            reply_markup=_duration_keyboard(),
        )
        return
    if value.lower() in ("0", "macdinh", "mặc định", "reset"):
        _set_user_duration(message.from_user.id, None)
        bot.reply_to(message, _duration_summary(message.from_user.id))
        return
    match = qc.DURATION_VALUE_RE.match(value)
    seconds = qc.to_seconds(match.group(1), match.group(2)) if match else None
    if not seconds or cp.normalize_duration(seconds) != seconds:
        bot.reply_to(
            message,
            f"Thời lượng phải từ {cp.MIN_DURATION_SECONDS} đến "
            f"{cp.MAX_DURATION_SECONDS} giây. Ví dụ: /thoiluong 45 hoặc /thoiluong 2p.",
        )
        return
    _set_user_duration(message.from_user.id, seconds)
    bot.reply_to(message, _duration_summary(message.from_user.id))


@bot.callback_query_handler(func=lambda call: (call.data or "").startswith("duration:"))
def handle_duration_button(call: types.CallbackQuery) -> None:
    if call.from_user.id not in ALLOWED_USER_IDS:
        bot.answer_callback_query(call.id, "Bạn chưa có quyền dùng bot này.")
        return
    seconds = int(call.data.split(":", 1)[1])
    _set_user_duration(call.from_user.id, seconds or None)
    summary = _duration_summary(call.from_user.id)
    bot.answer_callback_query(call.id, "Đã lưu")
    try:
        bot.edit_message_text(summary, call.message.chat.id, call.message.message_id)
    except Exception:
        bot.send_message(call.message.chat.id, summary)


def _language_summary(user_id: int) -> str:
    code = _get_user_language(user_id)
    voice = qc.language_voice(code) or cp.get_language(code).voice
    voice_note = f" Giọng đọc: {voice}." if voice else ""
    return f"Ngôn ngữ video của bạn: {_language_name(code)}.{voice_note}"


def _language_keyboard() -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        *[
            types.InlineKeyboardButton(language.name, callback_data=f"language:{code}")
            for code, language in cp.LANGUAGES.items()
        ]
    )
    return keyboard


@bot.message_handler(commands=["ngonngu"])
def handle_language(message: types.Message) -> None:
    if not _is_authorized(message):
        return
    _, value = _parse_command(message.text)
    if not value:
        bot.reply_to(
            message,
            f"{_language_summary(message.from_user.id)}\n\n"
            "Chọn ngôn ngữ cho các video sau, hoặc gõ /ngonngu en, /ngonngu vi. Muốn "
            "đổi riêng một video thì thêm #en hoặc #vi vào nội dung.",
            reply_markup=_language_keyboard(),
        )
        return
    key = value.strip().lower()
    code = LANGUAGE_FLAGS.get(key) or next(
        (code for code in cp.LANGUAGES if code.lower() == key), None
    )
    if code is None:
        bot.reply_to(message, "Chưa hỗ trợ ngôn ngữ này. Gõ /ngonngu en hoặc /ngonngu vi.")
        return
    _set_user_setting(message.from_user.id, "language", code)
    bot.reply_to(message, _language_summary(message.from_user.id))


@bot.callback_query_handler(func=lambda call: (call.data or "").startswith("language:"))
def handle_language_button(call: types.CallbackQuery) -> None:
    if call.from_user.id not in ALLOWED_USER_IDS:
        bot.answer_callback_query(call.id, "Bạn chưa có quyền dùng bot này.")
        return
    code = call.data.split(":", 1)[1]
    if code not in cp.LANGUAGES:
        bot.answer_callback_query(call.id, "Ngôn ngữ không hợp lệ.")
        return
    _set_user_setting(call.from_user.id, "language", code)
    summary = _language_summary(call.from_user.id)
    bot.answer_callback_query(call.id, "Đã lưu")
    try:
        bot.edit_message_text(summary, call.message.chat.id, call.message.message_id)
    except Exception:
        bot.send_message(call.message.chat.id, summary)


@bot.message_handler(commands=list(cp.PRESETS_BY_COMMAND))
def handle_preset_command(message: types.Message) -> None:
    if not _is_authorized(message):
        return
    command, prompt = _parse_command(message.text)
    _submit(message, command, prompt)


# ------------------------------------------------- ảnh/video kèm caption

_album_lock = threading.Lock()
_albums: dict[str, dict] = {}


def _handle_media_batch(messages: list[types.Message]) -> None:
    caption_message = next((m for m in messages if m.caption), messages[0])
    command, prompt = _parse_command(caption_message.caption)
    media = [ref for ref in (_media_from_message(m) for m in messages) if ref]
    if command not in cp.PRESETS_BY_COMMAND:
        bot.reply_to(
            caption_message,
            "Để dùng ảnh/video này, gửi kèm caption: /sanpham <mô tả sản phẩm> "
            "hoặc /diadiem <tên địa điểm>",
        )
        return
    if not media:
        bot.reply_to(caption_message, "Không đọc được ảnh/video nào (chỉ hỗ trợ jpg, png, mp4, mov...).")
        return
    _submit(caption_message, command, prompt, media)


def _flush_album(group_id: str) -> None:
    with _album_lock:
        entry = _albums.pop(group_id, None)
    if entry:
        messages = sorted(entry["messages"], key=lambda m: m.message_id)
        try:
            _handle_media_batch(messages)
        except Exception:
            logger.exception("failed to handle telegram album")


@bot.message_handler(content_types=["photo", "video", "document"])
def handle_media(message: types.Message) -> None:
    group_id = message.media_group_id
    if not group_id:
        if _is_authorized(message):
            _handle_media_batch([message])
        return
    # Album được Telegram gửi thành nhiều tin riêng lẻ; gom lại rồi xử lý một lần.
    with _album_lock:
        entry = _albums.get(group_id)
        if entry is None:
            if not _is_authorized(message):
                return
            entry = _albums[group_id] = {"messages": [], "timer": None}
        entry["messages"].append(message)
        if entry["timer"]:
            entry["timer"].cancel()
        entry["timer"] = threading.Timer(ALBUM_WAIT_SECONDS, _flush_album, args=(group_id,))
        entry["timer"].start()


@bot.message_handler(func=lambda message: True)
def handle_other(message: types.Message) -> None:
    if not _is_authorized(message):
        return
    # Lệnh gõ sai không được coi là góp ý cho danh sách chủ đề con.
    is_text = not (message.text or "").startswith("/")
    user_id = message.from_user.id if message.from_user else 0
    replied = message.reply_to_message.message_id if message.reply_to_message else None
    # Trả lời đúng tin danh sách chủ đề con thì là góp ý cho danh sách đó; ngược
    # lại ưu tiên câu hỏi bổ sung đang chờ, rồi mới đến danh sách mới nhất.
    plan = is_text and replied and _find_plan(message.chat.id, user_id, replied)
    if plan:
        _revise_plan(message, plan)
    elif _answer_draft(message):
        pass
    elif is_text and (plan := _find_plan(message.chat.id, user_id)):
        _revise_plan(message, plan)
    else:
        bot.reply_to(message, "Mình chưa hiểu yêu cầu. Gõ /help để xem các lệnh.")


# ---------------------------------------------------------------- xử lý job


def _download_media(job: Job) -> list[str]:
    target_dir = utils.storage_dir("local_videos", create=True)
    paths = []
    for index, ref in enumerate(job.media, start=1):
        file_info = bot.get_file(ref.file_id)
        data = bot.download_file(file_info.file_path)
        path = os.path.join(target_dir, f"tg-{uuid4().hex}-{index}{ref.extension}")
        with open(path, "wb") as file:
            file.write(data)
        paths.append(path)
    return paths



def _probe_video(path: str) -> tuple[int, int, float]:
    """Đọc (rộng, cao, thời lượng) từ đầu ra của ffmpeg -i."""
    result = subprocess.run(
        [video_service.get_ffmpeg_binary(), "-hide_banner", "-i", path],
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


def _run_ffmpeg(arguments: list[str]) -> bool:
    result = subprocess.run(
        [video_service.get_ffmpeg_binary(), "-hide_banner", "-y", *arguments],
        capture_output=True,
    )
    if result.returncode != 0:
        logger.error(f"ffmpeg failed: {result.stderr[-800:]!r}")
    return result.returncode == 0


def _prepare_for_telegram(path: str, duration: float) -> str | None:
    """
    Tạo bản MP4 chuẩn cho Telegram: AAC stereo 44.1kHz và moov ở đầu file
    (faststart). MoviePy ghi moov ở cuối file; Telegram có thể xử lý file như vậy
    thành video không tiếng hoặc ảnh động. Video quá 50MB được nén lại.
    Trả về None nếu không tạo được bản nằm trong giới hạn.
    """
    output = os.path.splitext(path)[0] + "-telegram.mp4"
    audio_args = ["-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2"]
    common_args = ["-map", "0:v:0", "-map", "0:a:0?", "-movflags", "+faststart"]

    if os.path.getsize(path) <= TELEGRAM_UPLOAD_LIMIT:
        ok = _run_ffmpeg(["-i", path, *common_args, "-c:v", "copy", *audio_args, output])
        if ok and os.path.getsize(output) <= TELEGRAM_UPLOAD_LIMIT:
            return output

    if duration <= 0:
        return None
    video_kbps = int(COMPRESS_TARGET_BYTES * 8 / 1024 / duration) - 128
    if video_kbps < 300:
        return None
    ok = _run_ffmpeg([
        "-i", path, *common_args,
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-b:v", f"{video_kbps}k", "-maxrate", f"{video_kbps}k",
        "-bufsize", f"{video_kbps * 2}k", *audio_args, output,
    ])
    if ok and os.path.getsize(output) <= TELEGRAM_UPLOAD_LIMIT:
        return output
    return None


def _make_thumbnail(path: str, cover_path: str | None = None) -> str | None:
    """Ảnh nhỏ (tối đa 320px) Telegram dùng cho danh sách; ưu tiên thu nhỏ từ cover."""
    thumbnail = os.path.splitext(path)[0] + "-thumb.jpg"
    if cover_path:
        try:
            with Image.open(cover_path) as image:
                image.thumbnail((320, 320))
                image.convert("RGB").save(thumbnail, "JPEG", quality=85)
            return thumbnail
        except Exception as exc:
            logger.warning(f"failed to make thumbnail from cover: {exc}")
    ok = _run_ffmpeg([
        "-ss", "1", "-i", path, "-frames:v", "1",
        "-vf", "scale=320:320:force_original_aspect_ratio=decrease", thumbnail,
    ])
    return thumbnail if ok and os.path.exists(thumbnail) else None


def make_cover(job: Job, video_path: str, result: dict | None = None) -> str | None:
    return qc.make_cover(job.preset, job.prompt, video_path, result)


def _send_video(
    job: Job, path: str, caption: str, duration: float, cover_path: str | None = None
) -> bool:
    """Gửi video qua Telegram; False nếu không chuẩn bị được bản gửi (đã báo người dùng)."""
    _edit_status(job, "Đang chuẩn bị video để gửi qua Telegram...")
    prepared = _prepare_for_telegram(path, duration)
    if not prepared:
        bot.send_message(
            job.chat_id,
            f"Không chuẩn bị được video để gửi qua Telegram (quá lớn hoặc lỗi ffmpeg). "
            f"File nằm trên máy chủ:\n{path}",
            reply_to_message_id=job.reply_to,
        )
        return False
    width, height, probed_duration = _probe_video(prepared)
    thumbnail = _make_thumbnail(prepared, cover_path)

    def send(with_cover: bool):
        files = []
        try:
            thumbnail_file = open(thumbnail, "rb") if thumbnail else None
            cover_file = open(cover_path, "rb") if with_cover and cover_path else None
            files = [f for f in (thumbnail_file, cover_file) if f]
            with open(prepared, "rb") as file:
                return bot.send_video(
                    job.chat_id,
                    file,
                    # Truyền rõ kích thước và thời lượng để Telegram nhận đúng là video
                    # có tiếng, không tự đoán thành ảnh động (GIF).
                    duration=round(probed_duration or duration) or None,
                    width=width or None,
                    height=height or None,
                    thumbnail=thumbnail_file,
                    cover=cover_file,
                    caption=caption[:MAX_CAPTION],
                    supports_streaming=True,
                    reply_to_message_id=job.reply_to,
                    timeout=600,
                )
        finally:
            for opened in files:
                opened.close()

    try:
        sent = send(with_cover=True)
    except telebot.apihelper.ApiTelegramException as exc:
        if not cover_path:
            raise
        # Máy chủ Bot API cũ không hỗ trợ tham số cover; gửi lại chỉ với thumbnail.
        logger.warning(f"send_video with cover failed, retrying without cover: {exc}")
        sent = send(with_cover=False)
    if sent.video is None:
        logger.warning(
            f"telegram did not store the upload as a video: "
            f"content_type={sent.content_type}, file={prepared}"
        )
    return True


keep_video = qc.keep_video
keep_gif = qc.keep_gif
saved_note = qc.saved_note


def gif_caption(header: str, gif_text: cp.GifText) -> str:
    detail = f"\n\n{gif_text.detail}" if gif_text.detail else ""
    return f"{header}{gif_text.text}{detail}"


def post_caption(post: cp.PostPackage | None, script: str, header: str = "") -> str:
    """Caption video: nội dung đăng bài chuẩn SEO để dán thẳng, hoặc kịch bản nếu không có."""
    body = post.text(MAX_CAPTION - len(header)) if post else script
    return f"{header}{body}"[:MAX_CAPTION]


def send_script(chat_id: int, script: str, post: cp.PostPackage | None) -> None:
    keyword = f"Từ khoá chính: {post.keyword}\n\n" if post and post.keyword else ""
    bot.send_message(chat_id, f"{keyword}Kịch bản:\n\n{script}"[:MAX_MESSAGE])


def _video_caption(job: Job, result: qc.VideoResult) -> str:
    post = result.post
    if job.batch:
        # Dòng đầu chỉ để đánh số video trong loạt, giống telegram_batch.py.
        label = f"[{job.batch_number}/{len(job.batch.topics)}]"
        header = f"{label}\n" if post else f"{label} {cp.cover_title(job.prompt)}\n\n"
    else:
        header = "" if post else f"{job.preset.title}\n\n"
    return post_caption(post, result.script, header)


def _process(job: Job) -> bool:
    """Tạo và gửi video cho một yêu cầu; False nếu không gửi được video nào."""
    # Video trong loạt ghi rõ là video nào, vì tin trạng thái không reply lệnh gốc.
    which = f"{_job_title(job)}\n" if job.batch else ""
    started = time.monotonic()
    _edit_status(job, f"Đang viết kịch bản và nội dung đăng bài: {_job_title(job)}")
    material_paths = _download_media(job) if job.media else None

    def on_stage(stage: str) -> None:
        if stage == "deliver":
            minutes = (time.monotonic() - started) / 60
            _edit_status(job, f"Hoàn tất sau {minutes:.1f} phút. Đang gửi video...")

    def deliver(result: qc.VideoResult, path: str, cover_path: str | None) -> bool:
        caption = _video_caption(job, result)
        return _send_video(job, path, caption, result.audio_duration, cover_path)

    try:
        result = qc.create_video(
            job.preset,
            job.prompt,
            aspect=job.aspect,
            duration=job.duration,
            language=job.language,
            high=job.high,
            material_paths=material_paths,
            on_stage=on_stage,
            on_progress=lambda progress: _edit_status(
                job, f"Đang tạo video: {_job_title(job)}\nTiến độ: {progress}%"
            ),
            progress_interval=PROGRESS_INTERVAL_SECONDS,
            deliver=deliver,
        )
    except qc.VideoFailed as exc:
        _edit_status(job, f"{which}{exc.describe()}"[:MAX_MESSAGE])
        return False

    sent = result.delivered
    # Caption đã là nội dung đăng bài nên gửi kịch bản riêng để tiện xem lại; loạt
    # video thì bỏ qua để chat không bị ngập tin.
    if not job.batch and (result.post or len(result.script) > MAX_CAPTION):
        send_script(job.chat_id, result.script, result.post)
    verb = "Đã gửi video" if sent else "Đã tạo xong nhưng không gửi được video"
    notes = "\n".join(saved_note(item.saved, item.path) for item in result.outputs)
    try:
        scheduled = qc.schedule_outputs(result, job.post, source="telegram", chat_id=job.chat_id)
    except Exception:
        logger.exception("cannot schedule social posts")
        scheduled = []
    if scheduled:
        notes += "\n" + qc.schedule_note(scheduled)
    _edit_status(job, f"{which}{verb} ({result.minutes:.1f} phút).\n{notes}")
    return sent


def _run_job(job: Job) -> bool:
    try:
        _refresh_config()
        return _process(job)
    except Exception as exc:
        logger.error(f"telegram job failed: {exc}\n{traceback.format_exc()}")
        _edit_status(job, f"Lỗi khi tạo video: {type(exc).__name__}: {exc}"[:MAX_MESSAGE])
        return False


# ------------------------------------------------- ảnh GIF có chữ (#gif)

# Mỗi lúc dựng một GIF. Ảnh GIF lẻ chạy ngoài hàng đợi video vì chỉ mất vài chục giây;
# GIF trong loạt /hangloat đi qua hàng đợi như video để dùng chung cơ chế của loạt.
_gif_lock = threading.Lock()


def _start_gif(job: Job) -> None:
    waiting = "\nĐang chờ ảnh GIF trước đó xong." if _gif_lock.locked() else ""
    status = bot.send_message(
        job.chat_id,
        f"Đã nhận yêu cầu ảnh GIF: {job.preset.title}\n"
        f"Ngôn ngữ: {_language_name(job.language)}{_model_note(job.high)}{waiting}",
        reply_to_message_id=job.reply_to,
    )
    job.status_message_id = status.message_id
    threading.Thread(target=_run_gif, args=(job,), daemon=True).start()


def _send_gif(job: Job, result: gif_maker.GifResult, caption: str) -> None:
    # Telegram phát ảnh động dạng MP4 không tiếng; bản MP4 nhẹ và mượt hơn GIF nhiều.
    # File .gif được lưu vào thư mục thành phẩm (keep_gif), không gửi kèm.
    with open(result.preview_path or result.path, "rb") as file:
        bot.send_animation(
            job.chat_id,
            file,
            duration=round(result.seconds) or None,
            width=result.width,
            height=result.height,
            caption=caption[:MAX_CAPTION],
            reply_to_message_id=job.reply_to,
            timeout=300,
        )


def _process_gif(job: Job) -> bool:
    """Tạo và gửi một ảnh GIF; lỗi người dùng cần biết thì ném GifError."""
    # GIF trong loạt ghi rõ là mục nào, vì tin trạng thái không reply lệnh gốc.
    which = f"{_job_title(job)}\n" if job.batch else ""
    # Như loạt video: dòng đầu caption chỉ để đánh số mục trong loạt.
    header = f"[{job.batch_number}/{len(job.batch.topics)}]\n" if job.batch else ""

    def on_stage(stage: str, text: str) -> None:
        if stage == "text":
            _edit_status(job, f"Đang viết chữ cho ảnh GIF: {_job_title(job)}")
        elif stage == "clip":
            _edit_status(job, f"{which}Đang tìm clip Pixabay và chèn chữ:\n{text}")
        else:
            _edit_status(job, f"{which}Đang gửi ảnh GIF...")

    output = qc.create_gif(
        job.preset,
        job.prompt,
        aspect=job.aspect,
        language=job.language,
        high=job.high,
        used_terms=job.batch.used_terms if job.batch else None,
        on_stage=on_stage,
        deliver=lambda gif_text, result: _send_gif(job, result, gif_caption(header, gif_text)),
    )
    _edit_status(
        job,
        f"{which}Đã gửi ảnh GIF ({output.seconds:.0f} giây).\n"
        f"{saved_note(output.saved, output.gif.path)}",
    )
    return True


def _run_gif(job: Job) -> bool:
    """Tạo một ảnh GIF, lẻ hoặc trong loạt; False nếu không gửi được."""
    which = f"{_job_title(job)}\n" if job.batch else ""
    with _gif_lock:
        try:
            _refresh_config()
            return _process_gif(job)
        except gif_maker.GifError as exc:
            _edit_status(job, f"{which}Không tạo được ảnh GIF: {exc}"[:MAX_MESSAGE])
        except Exception as exc:
            logger.error(f"telegram gif job failed: {exc}\n{traceback.format_exc()}")
            _edit_status(
                job, f"{which}Lỗi khi tạo ảnh GIF: {type(exc).__name__}: {exc}"[:MAX_MESSAGE]
            )
    return False


def _worker() -> None:
    # Dựng video tốn nhiều CPU/RAM nên xử lý tuần tự từng yêu cầu.
    global _running_job
    while True:
        job = jobs.get()
        batch = job.batch
        _running_job = job
        try:
            if batch and batch.stopped:
                _edit_status(job, f"Đã bỏ {_job_title(job)} vì loạt đã dừng.")
            else:
                sent = False
                for attempt in range(1 + (BATCH_RETRIES if batch else 0)):
                    if attempt:
                        logger.warning(f"retrying batch item {_job_title(job)}")
                    sent = _run_gif(job) if job.gif else _run_job(job)
                    if sent or (batch and batch.stopped):
                        break
                if batch:
                    # Ghi kết quả trước khi bỏ _running_job để lệnh dừng gửi cùng lúc
                    # không báo tổng kết thiếu video này.
                    if sent:
                        batch.sent += 1
                    else:
                        batch.failed.append(job.batch_number)
        finally:
            _running_job = None
            jobs.task_done()
        if batch:
            try:
                _continue_batch(batch)
            except Exception:
                logger.exception("failed to continue telegram batch")


def _bot_commands() -> list[types.BotCommand]:
    commands = [
        types.BotCommand(p.command, p.title)
        for p in cp.PRESETS.values()
    ]
    commands += [
        types.BotCommand("hangloat", "Tạo hàng loạt video hoặc ảnh GIF (#gif) theo một chủ đề"),
        types.BotCommand("dunghangloat", "Dừng loạt đang tạo"),
        types.BotCommand("thoiluong", "Đặt thời lượng video mặc định"),
        types.BotCommand("ngonngu", "Chọn ngôn ngữ video (Việt / Anh)"),
        types.BotCommand("trangthai", "Xem video đang tạo và hàng đợi"),
        types.BotCommand("dang", "Lên lịch đăng video lên Facebook, TikTok, YouTube"),
        types.BotCommand("lichdang", "Xem lịch đăng, đăng ngay hoặc huỷ"),
        types.BotCommand("tudongdang", "Bật/tắt tự đăng video mới, khung giờ đăng"),
        types.BotCommand("dangnhap", "Mở trình duyệt đăng bài để đăng nhập các trang"),
        types.BotCommand("help", "Hướng dẫn sử dụng và ví dụ"),
        types.BotCommand("start", "Bắt đầu"),
    ]
    return commands


def _register_menu() -> None:
    """Đăng ký danh sách lệnh và nút Menu cạnh ô nhập tin của Telegram."""
    commands = _bot_commands()
    try:
        bot.set_my_commands(commands)
        # Client đặt ngôn ngữ tiếng Việt ưu tiên danh sách theo language_code.
        bot.set_my_commands(commands, language_code="vi")
        bot.set_chat_menu_button(menu_button=types.MenuButtonCommands(type="commands"))
        # Admin thấy thêm các lệnh quản lý quyền trong menu chat riêng của họ.
        admin_commands = commands + [
            types.BotCommand("nguoidung", "Danh sách người dùng và yêu cầu"),
            types.BotCommand("thuhoi", "Thu hồi quyền: /thuhoi <user_id>"),
        ]
        for admin_id in ADMIN_USER_IDS:
            bot.set_my_commands(admin_commands, scope=types.BotCommandScopeChat(admin_id))
    except Exception as exc:
        # Lỗi mạng khi đăng ký menu không được chặn bot hoạt động.
        logger.warning(f"failed to register telegram bot menu: {exc}")


def _acquire_single_instance_lock():
    """Telegram chỉ cho một tiến trình polling mỗi bot; chạy trùng sẽ bị lỗi 409."""
    import socket

    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
    except OSError:
        lock.close()
        return None
    return lock


def main() -> None:
    instance_lock = _acquire_single_instance_lock()
    if instance_lock is None:
        logger.info("telegram bot đã chạy ở cửa sổ khác, bỏ qua lần khởi động này")
        return
    if not ADMIN_USER_IDS:
        logger.warning(
            "Chưa có quản trị viên ([telegram].admin_user_ids hoặc allowed_user_ids trống): "
            "yêu cầu cấp quyền sẽ không gửi được tới ai."
        )
    # Ghi log ra file để tra cứu lại (cửa sổ console mất log khi đóng).
    logger.add(
        os.path.join(utils.storage_dir("logs", create=True), "telegram_bot.log"),
        level="INFO", encoding="utf-8", rotation="10 MB", retention=10,
    )
    _register_menu()
    threading.Thread(target=_worker, daemon=True).start()
    # Vòng đăng bài theo lịch; nếu WebUI đã chạy vòng này thì bot chỉ nhận việc khi web tắt.
    social_schedule.start_runner()
    logger.info("telegram bot started")
    bot.infinity_polling(timeout=30, long_polling_timeout=30, skip_pending=True)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    main()
