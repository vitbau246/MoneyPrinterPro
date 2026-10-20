"""
Lịch đăng video lên Facebook Reels, TikTok và YouTube, dùng chung cho WebUI và bot.

- Lịch lưu ở storage/social/schedule.json; web và bot cùng đọc/ghi qua khoá file.
- Mỗi lúc chỉ một tiến trình (web hoặc bot, bên nào giữ được cổng khoá trước) chạy
  vòng đăng bài, nên một bài không bao giờ bị đăng hai lần. Tiến trình đó tắt thì bên
  còn lại tự nhận việc trong vòng một phút.
- Thiết lập đăng tự động (bật/tắt, nền tảng, khung giờ trong ngày) ở
  storage/social/settings.json, chỉnh được từ web (tab Đăng bài) và bot (/tudongdang).
- Tiêu đề, mô tả, hashtag và thẻ YouTube chuẩn SEO do AI viết khi tạo video được ghi ở
  storage/social/captions.json để khi đăng tự điền đầy đủ (thư mục thành phẩm chỉ giữ
  video, ảnh bìa, lời thoại). Video cũ chưa có thì AI viết từ lời thoại trước khi đăng.
- Kết quả đăng được báo qua Telegram (người đặt lịch trên bot, hoặc quản trị viên).
"""

from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Callable, Iterator, Sequence
from uuid import uuid4

import requests
from loguru import logger

from app.config import config
from app.services import content_presets as cp
from app.services import output_library
from app.services import social_publish as sp
from app.utils import utils

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"
TRIED = "dry_run"
STATUS_NAMES = {
    PENDING: "chờ đăng",
    RUNNING: "đang đăng",
    DONE: "đã đăng",
    FAILED: "lỗi",
    CANCELLED: "đã huỷ",
    TRIED: "đã chạy thử",
}

DEFAULT_SLOTS = ["08:00", "12:00", "19:30"]
MAX_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 10 * 60
RUNNER_PORT = 47832
RUNNER_POLL_SECONDS = 20
LOCK_TIMEOUT_SECONDS = 30
STALE_LOCK_SECONDS = 120
KEEP_FINISHED = 200

_SLOT_RE = re.compile(r"^(\d{1,2})[:hH](\d{2})?$")


def _folder() -> str:
    return utils.storage_dir("social", create=True)


def _path(name: str) -> str:
    return os.path.join(_folder(), name)


@contextmanager
def _locked() -> Iterator[None]:
    """Khoá giữa các tiến trình (web và bot) khi đọc-sửa-ghi file lịch."""
    path = _path("schedule.lock")
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(path) > STALE_LOCK_SECONDS:
                    os.remove(path)
                    continue
            except OSError:
                continue
            if time.monotonic() > deadline:
                raise TimeoutError("schedule lock is busy")
            time.sleep(0.1)
    try:
        yield
    finally:
        os.close(handle)
        try:
            os.remove(path)
        except OSError:
            pass


def _read(name: str, default):
    try:
        with open(_path(name), encoding="utf-8") as file:
            return json.load(file)
    except (OSError, ValueError):
        return default


def _write(name: str, data) -> None:
    temp = _path(name + ".tmp")
    with open(temp, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    os.replace(temp, _path(name))


# ---------------------------------------------------------------- thiết lập


def normalize_slots(values: Sequence[str]) -> list[str]:
    """"8:00", "19h30", "7h" -> ["07:00", "08:00", "19:30"]; bỏ giá trị sai."""
    slots = set()
    for value in values:
        match = _SLOT_RE.match(str(value).strip())
        if match and int(match[1]) < 24 and int(match[2] or 0) < 60:
            slots.add(f"{int(match[1]):02d}:{int(match[2] or 0):02d}")
    return sorted(slots)


def normalize_platforms(values: Sequence[str]) -> list[str]:
    chosen = {sp.PLATFORM_ALIASES.get(str(value).strip().lower()) for value in values}
    return [platform for platform in sp.PLATFORMS if platform in chosen]


def get_settings() -> dict:
    data = _read("settings.json", {})
    return {
        "auto_post": bool(data.get("auto_post", False)),
        "platforms": normalize_platforms(data.get("platforms") or sp.PLATFORMS) or list(sp.PLATFORMS),
        # Danh sách rỗng là lựa chọn của người dùng: đăng ngay khi tạo xong.
        "slots": normalize_slots(data["slots"] if "slots" in data else DEFAULT_SLOTS),
    }


def save_settings(**changes) -> dict:
    with _locked():
        settings = get_settings()
        if "auto_post" in changes:
            settings["auto_post"] = bool(changes["auto_post"])
        if changes.get("platforms") is not None:
            settings["platforms"] = normalize_platforms(changes["platforms"]) or settings["platforms"]
        if changes.get("slots") is not None:
            settings["slots"] = normalize_slots(changes["slots"])
        _write("settings.json", settings)
    return settings


# ------------------------------------------------------- nội dung đăng bài


def remember_post(
    video_path: str, title: str, description: str, tags: Sequence[str] = ()
) -> None:
    """Ghi tiêu đề, mô tả (kèm hashtag) và thẻ YouTube của video trong thư mục thành phẩm."""
    try:
        with _locked():
            captions = _read("captions.json", {})
            captions[os.path.basename(video_path)] = {
                "title": title,
                "description": description,
                "tags": list(tags),
            }
            _write("captions.json", captions)
    except Exception as exc:
        logger.warning(f"cannot remember post text for {video_path}: {exc}")


def _stem_title(video_path: str) -> str:
    stem = os.path.splitext(os.path.basename(video_path))[0]
    return re.sub(r"^#\d+\s+", "", stem)


def caption_for(video_path: str) -> tuple[str, str, list[str]]:
    """(tiêu đề, mô tả, thẻ) để đăng; video cũ chưa có thì lấy tiêu đề từ tên file."""
    saved = _read("captions.json", {}).get(os.path.basename(video_path)) or {}
    title = saved.get("title") or _stem_title(video_path)
    return title, saved.get("description") or "", list(saved.get("tags") or [])


def has_post_info(video_path: str) -> bool:
    saved = _read("captions.json", {}).get(os.path.basename(video_path)) or {}
    return bool(saved.get("description"))


def post_fields(post: cp.PostPackage | None, fallback_title: str) -> tuple[str, str, list[str]]:
    """(tiêu đề, mô tả kèm hashtag, thẻ YouTube) từ nội dung AI viết."""
    if not post:
        return fallback_title, "", []
    hashtags = " ".join(post.hashtags)
    description = "\n\n".join(part for part in (post.caption, hashtags) if part)
    tags = post.tags or cp.clean_tags([post.keyword, *(tag.lstrip("#") for tag in post.hashtags)])
    return post.title or fallback_title, description, tags


class _AnyVideo:
    """Loại nội dung chung cho video cũ không rõ loại."""

    title = "Video ngắn"
    seo_hint = ""
    default_hashtags: tuple[str, ...] = ()


def generate_post_info(video_path: str) -> tuple[str, str, list[str]] | None:
    """
    AI viết tiêu đề, mô tả, hashtag và thẻ cho video chưa có (video tạo trước khi có
    tính năng này), từ lời thoại trong file .txt cạnh video; lưu lại và trả về.
    """
    script_path = os.path.splitext(video_path)[0] + ".txt"
    try:
        with open(script_path, encoding="utf-8") as file:
            script = file.read().strip()
    except OSError:
        script = ""
    title = _stem_title(video_path)
    post = cp.generate_post(_AnyVideo(), title, script or title)
    if post is None:
        return None
    fields = post_fields(post, title)
    remember_post(video_path, *fields)
    return fields


def library_videos() -> list[tuple[int, str, str]]:
    """(số thứ tự, tên, đường dẫn mp4) trong storage/output/video, mới nhất trước."""
    folder = output_library.output_dir(output_library.VIDEO)
    items = []
    for name in os.listdir(folder):
        match = re.match(r"^#(\d+) ", name)
        if match and name.lower().endswith(".mp4"):
            items.append((int(match[1]), os.path.splitext(name)[0], os.path.join(folder, name)))
    return sorted(items, reverse=True)


def find_video(number: int) -> str | None:
    return next((path for index, _, path in library_videos() if index == number), None)


# ------------------------------------------------------------------- thời gian


def next_free_slot(after: float | None = None, taken: Sequence[float] = ()) -> float:
    """Khung giờ đăng kế tiếp chưa có bài nào; không có khung giờ thì đăng ngay."""
    now = time.time() if after is None else after
    slots = get_settings()["slots"]
    if not slots:
        return now
    busy = {round(value) for value in taken}
    busy |= {
        round(entry["run_at"])
        for entry in _read("schedule.json", [])
        if any(target["status"] in (PENDING, RUNNING) for target in entry["targets"].values())
    }
    day = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    for offset in range(366):
        for slot in slots:
            hour, minute = map(int, slot.split(":"))
            moment = (day + timedelta(days=offset)).replace(hour=hour, minute=minute).timestamp()
            if moment > now + 60 and round(moment) not in busy:
                return moment
    return now


def parse_when(text: str, now: float | None = None) -> float | None:
    """
    Thời điểm gõ trên bot: "ngay"/"now", "20:00" (hôm nay, đã qua thì ngày mai),
    "21/10 20:00", "21/10/2026 20:00". None nếu không hiểu.
    """
    text = (text or "").strip().lower()
    current = datetime.fromtimestamp(time.time() if now is None else now)
    if text in ("ngay", "now", "luôn", "luon"):
        return current.timestamp()
    match = re.match(r"^(?:(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\s+)?(\d{1,2})[:h](\d{2})$", text)
    if not match:
        return None
    day, month, year, hour, minute = match.groups()
    try:
        moment = current.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
        if day:
            moment = moment.replace(year=int(year or current.year), month=int(month), day=int(day))
        elif moment <= current:
            moment += timedelta(days=1)
    except ValueError:
        return None
    return moment.timestamp()


def format_time(timestamp: float) -> str:
    moment = datetime.fromtimestamp(timestamp)
    today = datetime.now().date()
    if moment.date() == today:
        return moment.strftime("%H:%M hôm nay")
    if moment.date() == today + timedelta(days=1):
        return moment.strftime("%H:%M ngày mai")
    return moment.strftime("%H:%M %d/%m/%Y")


# --------------------------------------------------------------------- lịch


def entries() -> list[dict]:
    """Toàn bộ lịch, gần nhất trước."""
    return sorted(_read("schedule.json", []), key=lambda entry: entry["run_at"])


def get(entry_id: str) -> dict | None:
    return next((entry for entry in _read("schedule.json", []) if entry["id"] == entry_id), None)


def entry_status(entry: dict) -> str:
    statuses = {target["status"] for target in entry["targets"].values()}
    for status in (RUNNING, PENDING, FAILED, TRIED, DONE, CANCELLED):
        if status in statuses:
            return status
    return CANCELLED


def schedule(
    video: str,
    platforms: Sequence[str] | None = None,
    run_at: float | None = None,
    *,
    title: str | None = None,
    description: str | None = None,
    tags: Sequence[str] | None = None,
    source: str = "web",
    chat_id: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Thêm một video vào lịch; ``run_at`` None thì vào khung giờ trống kế tiếp."""
    if not os.path.isfile(video):
        raise ValueError(f"Không thấy file video: {video}")
    chosen = normalize_platforms(platforms or get_settings()["platforms"])
    if not chosen:
        raise ValueError("Chưa chọn nền tảng nào (Facebook, TikTok, YouTube).")
    saved_title, saved_description, saved_tags = caption_for(video)
    with _locked():
        data = _read("schedule.json", [])
        entry = {
            "id": uuid4().hex[:8],
            "video": video,
            "name": os.path.splitext(os.path.basename(video))[0],
            "title": (title if title is not None else saved_title).strip(),
            "description": (description if description is not None else saved_description).strip(),
            "tags": cp.clean_tags(list(tags) if tags is not None else saved_tags),
            "run_at": run_at if run_at is not None else next_free_slot(),
            "created": time.time(),
            "source": source,
            "chat_id": chat_id,
            "dry_run": bool(dry_run),
            "targets": {
                platform: {"status": PENDING, "attempts": 0, "error": "", "url": "", "finished": 0, "retry_at": 0}
                for platform in chosen
            },
        }
        data.append(entry)
        _write("schedule.json", _trim(data))
    logger.info(f"scheduled {entry['name']} to {chosen} at {format_time(entry['run_at'])}")
    return entry


def _trim(data: list[dict]) -> list[dict]:
    finished = [entry for entry in data if entry_status(entry) not in (PENDING, RUNNING)]
    drop = {entry["id"] for entry in sorted(finished, key=lambda e: e["run_at"])[:-KEEP_FINISHED]} if len(finished) > KEEP_FINISHED else set()
    return [entry for entry in data if entry["id"] not in drop]


def _update(entry_id: str, change: Callable[[dict], None]) -> dict | None:
    with _locked():
        data = _read("schedule.json", [])
        entry = next((item for item in data if item["id"] == entry_id), None)
        if entry is not None:
            change(entry)
            _write("schedule.json", data)
        return entry


def cancel(entry_id: str) -> dict | None:
    """Huỷ các nền tảng chưa đăng của bài."""

    def change(entry):
        for target in entry["targets"].values():
            if target["status"] == PENDING:
                target["status"] = CANCELLED

    return _update(entry_id, change)


def run_now(entry_id: str) -> dict | None:
    """Đăng ngay các nền tảng chưa đăng, kể cả nền tảng lỗi (thử lại)."""

    def change(entry):
        entry["run_at"] = time.time()
        for target in entry["targets"].values():
            if target["status"] in (PENDING, FAILED, CANCELLED):
                target.update(status=PENDING, retry_at=0, attempts=0, error="")

    return _update(entry_id, change)


def remove(entry_id: str) -> None:
    with _locked():
        data = [entry for entry in _read("schedule.json", []) if entry["id"] != entry_id]
        _write("schedule.json", data)


def schedule_created_video(
    video: str,
    title: str,
    description: str,
    tags: Sequence[str] = (),
    *,
    source: str,
    chat_id: int | None = None,
    when: float | None = None,
) -> dict | None:
    """Ghi nội dung đăng bài và đưa video vừa tạo vào lịch (đăng tự động)."""
    remember_post(video, title, description, tags)
    try:
        return schedule(
            video, None, when, title=title, description=description, tags=tags,
            source=source, chat_id=chat_id,
        )
    except Exception as exc:
        logger.warning(f"cannot schedule {video}: {exc}")
        return None


def describe(entry: dict) -> str:
    """Một dòng mô tả bài trong lịch, dùng cho bot."""
    targets = ", ".join(
        f"{sp.PLATFORM_NAMES[name].split()[0]} {STATUS_NAMES[target['status']]}"
        for name, target in entry["targets"].items()
    )
    test = " (chạy thử)" if entry.get("dry_run") else ""
    return f"{entry['name']}\n   {format_time(entry['run_at'])}{test}: {targets}"


# ------------------------------------------------------------------ báo kết quả


def telegram_notify(chat_id: int | None, text: str) -> None:
    """Báo qua Telegram bằng Bot API (chạy được ở cả tiến trình web lẫn bot)."""
    settings = config._cfg.get("telegram", {}) or {}
    token = os.getenv("TELEGRAM_BOT_TOKEN") or settings.get("bot_token")
    if not chat_id:
        ids = list(settings.get("admin_user_ids") or []) + list(settings.get("allowed_user_ids") or [])
        chat_id = ids[0] if ids else None
    if not token or not chat_id:
        return
    proxy = str(settings.get("proxy") or "").strip()
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True},
            proxies={"http": proxy, "https": proxy} if proxy else None,
            timeout=20,
        )
    except Exception as exc:
        logger.warning(f"cannot send telegram notification: {exc}")


# --------------------------------------------------------------------- chạy


def _claim_due(now: float) -> tuple[dict, str] | None:
    """Giữ một (bài, nền tảng) đến giờ đăng: đánh dấu đang đăng và trả về."""
    with _locked():
        data = _read("schedule.json", [])
        for entry in sorted(data, key=lambda item: item["run_at"]):
            if entry["run_at"] > now:
                continue
            for platform, target in entry["targets"].items():
                if target["status"] == PENDING and target.get("retry_at", 0) <= now:
                    target["status"] = RUNNING
                    target["attempts"] = target.get("attempts", 0) + 1
                    _write("schedule.json", data)
                    return dict(entry), platform
    return None


def _finish(entry_id: str, platform: str, **values) -> dict | None:
    return _update(entry_id, lambda entry: entry["targets"][platform].update(values))


def process_once(
    publish: Callable[..., sp.Outcome] = sp.publish,
    notify: Callable[[int | None, str], None] = telegram_notify,
    now: float | None = None,
) -> bool:
    """Đăng một (bài, nền tảng) đến hạn; False nếu không còn gì cần đăng."""
    claimed = _claim_due(time.time() if now is None else now)
    if claimed is None:
        return False
    entry, platform = claimed
    name = sp.PLATFORM_NAMES[platform]
    if not entry.get("description"):
        entry = _fill_missing_info(entry)
    content = sp.Content(entry["video"], entry["title"], entry["description"], list(entry.get("tags") or []))
    target = entry["targets"][platform]
    try:
        outcome = publish(platform, content, dry_run=entry.get("dry_run", False), label=entry["id"])
    except sp.AccountError as exc:
        _finish(entry["id"], platform, status=FAILED, error=str(exc), finished=time.time())
        notify(entry.get("chat_id"), f"❌ Chưa đăng được {entry['name']} lên {name}.\n{exc}")
        return True
    except sp.MaybePosted as exc:
        # Đăng lại có thể thành bài trùng (TikTok từng đăng #071 hai lần): để người dùng xem.
        _finish(entry["id"], platform, status=FAILED, error=str(exc), finished=time.time())
        notify(entry.get("chat_id"), f"⚠️ {entry['name']} trên {name}: {exc}")
        return True
    except Exception as exc:
        error = str(exc) or type(exc).__name__
        if target["attempts"] < MAX_ATTEMPTS:
            _finish(entry["id"], platform, status=PENDING, error=error, retry_at=time.time() + RETRY_DELAY_SECONDS)
            logger.warning(f"publish {entry['name']} to {platform} failed, will retry: {error}")
        else:
            _finish(entry["id"], platform, status=FAILED, error=error, finished=time.time())
            notify(entry.get("chat_id"), f"❌ Lỗi đăng {entry['name']} lên {name}:\n{error}")
        return True
    if outcome.dry_run:
        _finish(entry["id"], platform, status=TRIED, error="", finished=time.time())
        notify(
            entry.get("chat_id"),
            f"🧪 Đã chạy thử {entry['name']} trên {name}: đã điền xong, chưa bấm Đăng. "
            "Tab vẫn mở trong trình duyệt đăng bài để bạn xem lại.",
        )
    else:
        _finish(
            entry["id"], platform, status=DONE, error="", url=outcome.url,
            account=outcome.account, finished=time.time(),
        )
        account = f" ({outcome.account})" if outcome.account else ""
        link = f"\n{outcome.url}" if outcome.url else ""
        notify(entry.get("chat_id"), f"✅ Đã đăng {entry['name']} lên {name}{account}.{link}")
    return True


def _fill_missing_info(entry: dict) -> dict:
    """Video chưa có mô tả/hashtag: dùng nội dung đã lưu, hoặc nhờ AI viết rồi ghi vào lịch."""
    video = entry["video"]
    if has_post_info(video):
        title, description, tags = caption_for(video)
    else:
        try:
            generated = generate_post_info(video)
        except Exception as exc:
            logger.warning(f"cannot generate post text for {video}: {exc}")
            generated = None
        if not generated:
            return entry
        title, description, tags = generated
    # Giữ tiêu đề người dùng đã sửa; chỉ thay khi còn là tiêu đề lấy từ tên file.
    if entry["title"] and entry["title"] != _stem_title(video):
        title = entry["title"]

    def change(item):
        item.update(title=title, description=description, tags=tags)

    return _update(entry["id"], change) or {**entry, "title": title, "description": description, "tags": tags}


def _reset_running() -> None:
    """Bài "đang đăng" từ lần chạy trước (tiến trình bị tắt giữa chừng) được đăng lại."""
    with _locked():
        data = _read("schedule.json", [])
        changed = False
        for entry in data:
            for target in entry["targets"].values():
                if target["status"] == RUNNING:
                    target["status"] = PENDING
                    changed = True
        if changed:
            _write("schedule.json", data)


_runner: threading.Thread | None = None
_runner_lock = threading.Lock()
_runner_socket: socket.socket | None = None


def is_runner() -> bool:
    """Tiến trình này đang giữ vòng đăng bài."""
    return _runner_socket is not None


def _acquire_runner_port() -> bool:
    global _runner_socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", RUNNER_PORT))
    except OSError:
        sock.close()
        return False
    _runner_socket = sock
    return True


def _run_forever() -> None:
    while not _acquire_runner_port():
        time.sleep(60)
    logger.info("social post scheduler started in this process")
    try:
        _reset_running()
    except Exception:
        logger.exception("cannot reset interrupted posts")
    while True:
        try:
            while process_once():
                pass
        except Exception:
            logger.exception("social post scheduler error")
        time.sleep(RUNNER_POLL_SECONDS)


def start_runner() -> None:
    """Chạy vòng đăng bài nền (gọi được nhiều lần). Không chạy khi đang chạy test."""
    global _runner
    if os.environ.get("MPT_TESTING") == "1":
        return
    with _runner_lock:
        if _runner is None or not _runner.is_alive():
            _runner = threading.Thread(target=_run_forever, name="mpt-social-scheduler", daemon=True)
            _runner.start()
