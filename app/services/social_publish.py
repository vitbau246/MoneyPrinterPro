"""
Đăng một video lên Facebook Reels, TikTok hoặc YouTube (Shorts) bằng Playwright, qua
trình duyệt đăng bài đã đăng nhập (app/services/social_browser.py).

Mỗi nền tảng làm đúng các bước người dùng tự làm trên trang tải lên: chọn file, điền
tiêu đề/mô tả, chờ tải lên xong rồi bấm Đăng. Nút được tìm theo id ổn định của trang
hoặc theo tên nút tiếng Việt/tiếng Anh. ``dry_run`` dừng ngay trước khi bấm Đăng và để
tab mở cho người dùng xem lại. Lỗi chụp màn hình vào storage/social/screenshots.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from loguru import logger

from app.services import social_browser
from app.utils import utils

FACEBOOK = "facebook"
TIKTOK = "tiktok"
YOUTUBE = "youtube"
PLATFORMS = (FACEBOOK, TIKTOK, YOUTUBE)
PLATFORM_NAMES = {FACEBOOK: "Facebook Reels", TIKTOK: "TikTok", YOUTUBE: "YouTube Shorts"}
# Tên ngắn gõ trên bot.
PLATFORM_ALIASES = {
    "fb": FACEBOOK, "facebook": FACEBOOK, "reels": FACEBOOK,
    "tt": TIKTOK, "tiktok": TIKTOK, "tik": TIKTOK,
    "yt": YOUTUBE, "youtube": YOUTUBE, "shorts": YOUTUBE,
}

UPLOAD_TIMEOUT_MS = 15 * 60 * 1000
STEP_TIMEOUT_MS = 60 * 1000
POLL_SECONDS = 1.0

YOUTUBE_TITLE_LIMIT = 100
YOUTUBE_DESCRIPTION_LIMIT = 4900
TIKTOK_CAPTION_LIMIT = 2200
FACEBOOK_CAPTION_LIMIT = 5000


class PublishError(Exception):
    """Không đăng được; thông báo dành cho người dùng."""


class NotLoggedIn(PublishError):
    """Trình duyệt đăng bài chưa đăng nhập nền tảng này."""


@dataclass
class Content:
    video: str
    title: str
    description: str = ""

    def full_text(self, limit: int) -> str:
        text = "\n\n".join(part for part in (self.title.strip(), self.description.strip()) if part)
        return text[:limit]


@dataclass
class Outcome:
    url: str = ""
    dry_run: bool = False


def _names(*words: str) -> re.Pattern:
    return re.compile(r"^\s*(" + "|".join(re.escape(word) for word in words) + r")\s*$", re.I)


def _wait_until(check: Callable[[], bool], timeout_ms: int, what: str) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except Exception:
            pass
        time.sleep(POLL_SECONDS)
    raise PublishError(f"Quá thời gian chờ {what}.")


def _enabled(locator) -> bool:
    if not locator.count():
        return False
    element = locator.first
    if not element.is_visible() or not element.is_enabled():
        return False
    return all(
        (element.get_attribute(attribute) or "").lower() != "true"
        for attribute in ("aria-disabled", "data-disabled")
    )


def _click_if_visible(locator) -> bool:
    """Bấm hộp thoại xác nhận nếu đang hiện; trả về True nếu đã bấm."""
    if locator.count() and locator.first.is_visible():
        locator.first.click()
        return True
    return False


def _click_when_enabled(locator, timeout_ms: int, what: str) -> None:
    _wait_until(lambda: _enabled(locator), timeout_ms, what)
    locator.first.click()


def _replace_text(page, box, text: str) -> None:
    """Xoá nội dung ô soạn thảo (contenteditable) rồi gõ ``text``."""
    box.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Backspace")
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line:
            page.keyboard.type(line, delay=5)
        if index < len(lines) - 1:
            page.keyboard.press("Shift+Enter")


def _require_login(condition: bool, platform: str) -> None:
    if condition:
        raise NotLoggedIn(
            f"Chưa đăng nhập {PLATFORM_NAMES[platform]} trong trình duyệt đăng bài. Bấm "
            "“Mở trình duyệt để đăng nhập” trên web (hoặc /dangnhap trên bot), đăng nhập "
            "một lần rồi thử lại."
        )


# ------------------------------------------------------------------ YouTube

_YT_UPLOADING = re.compile(r"(uploading|đang tải lên)[^\n]*\d+\s*%", re.I)


def _youtube(page, content: Content, dry_run: bool) -> Outcome:
    page.goto("https://www.youtube.com/upload", wait_until="domcontentloaded")
    page.wait_for_load_state("load")
    _require_login("accounts.google.com" in page.url, YOUTUBE)
    file_input = page.locator("ytcp-uploads-file-picker input[type=file], input[type=file]").first
    file_input.wait_for(state="attached", timeout=STEP_TIMEOUT_MS)
    file_input.set_input_files(content.video)

    title = page.locator("#title-textarea #textbox").first
    title.wait_for(state="visible", timeout=UPLOAD_TIMEOUT_MS)
    # YouTube không nhận dấu < > trong tiêu đề và mô tả.
    clean = lambda text: text.replace("<", "").replace(">", "")  # noqa: E731
    _replace_text(page, title, clean(content.title)[:YOUTUBE_TITLE_LIMIT])
    description = page.locator("#description-textarea #textbox").first
    _replace_text(page, description, clean(content.description)[:YOUTUBE_DESCRIPTION_LIMIT])
    page.locator(
        "tp-yt-paper-radio-button[name=VIDEO_MADE_FOR_KIDS_NOT_MFK],"
        "tp-yt-paper-radio-button[name=NOT_MADE_FOR_KIDS]"
    ).first.click()

    url = ""
    link = page.locator("ytcp-video-info a[href*='youtu'], .video-url-fadeable a").first
    try:
        link.wait_for(state="visible", timeout=30_000)
        url = (link.get_attribute("href") or link.inner_text() or "").strip()
    except Exception:
        pass

    public = page.locator("tp-yt-paper-radio-button[name=PUBLIC]").first
    for _ in range(4):
        if public.is_visible():
            break
        _click_when_enabled(page.locator("#next-button"), STEP_TIMEOUT_MS, "nút Tiếp của YouTube")
        page.wait_for_timeout(1500)
    public.click()

    progress = page.locator("ytcp-video-upload-progress, .progress-label").first
    _wait_until(
        lambda: not _YT_UPLOADING.search(progress.inner_text() if progress.count() else ""),
        UPLOAD_TIMEOUT_MS,
        "YouTube tải video lên",
    )
    if dry_run:
        return Outcome(url, dry_run=True)
    _click_when_enabled(page.locator("#done-button"), UPLOAD_TIMEOUT_MS, "nút Xuất bản của YouTube")
    # Kiểm tra bản quyền chưa xong thì YouTube hỏi lại: vẫn xuất bản.
    shared = page.locator("ytcp-video-share-dialog, ytcp-uploads-still-processing-dialog")
    warning = page.locator("ytcp-prechecks-warning-dialog #primary-action-button")

    def published() -> bool:
        _click_if_visible(warning)
        return shared.count() > 0 and shared.first.is_visible()

    _wait_until(published, 3 * 60 * 1000, "YouTube xác nhận đã xuất bản")
    share_url = page.locator("ytcp-video-share-dialog #share-url").first
    if share_url.count():
        url = (share_url.inner_text() or url).strip()
    return Outcome(url)


# ------------------------------------------------------------------- TikTok

_TT_DONE = re.compile(
    r"(your video has been uploaded|video của bạn đã được tải lên|đã đăng video|"
    r"video đã được đăng|manage your posts|quản lý bài đăng)",
    re.I,
)


def _tiktok(page, content: Content, dry_run: bool) -> Outcome:
    page.goto("https://www.tiktok.com/tiktokstudio/upload?from=webapp", wait_until="domcontentloaded")
    page.wait_for_load_state("load")
    _require_login("/login" in page.url, TIKTOK)
    file_input = page.locator("input[type=file][accept*=video], input[type=file]").first
    try:
        file_input.wait_for(state="attached", timeout=STEP_TIMEOUT_MS)
    except Exception:
        _require_login("/login" in page.url or page.get_by_text(re.compile(r"^(Log in|Đăng nhập)$")).count() > 0, TIKTOK)
        raise
    file_input.set_input_files(content.video)

    editor = page.locator("div.public-DraftEditor-content[contenteditable=true], div[contenteditable=true]").first
    editor.wait_for(state="visible", timeout=UPLOAD_TIMEOUT_MS)
    # Dấu cách cuối đóng ô gợi ý hashtag của TikTok.
    _replace_text(page, editor, content.full_text(TIKTOK_CAPTION_LIMIT) + " ")

    post = page.locator("button[data-e2e=post_video_button]")
    if not post.count():
        post = page.get_by_role("button", name=_names("Post", "Đăng"))
    _wait_until(lambda: _enabled(post), UPLOAD_TIMEOUT_MS, "TikTok tải video lên")
    if dry_run:
        return Outcome(dry_run=True)
    post.first.click()
    confirm = page.get_by_role("button", name=_names("Post now", "Đăng ngay", "Tiếp tục đăng"))

    def posted() -> bool:
        _click_if_visible(confirm)
        return "/tiktokstudio/content" in page.url or bool(
            _TT_DONE.search(page.locator("body").inner_text())
        )

    _wait_until(posted, 5 * 60 * 1000, "TikTok xác nhận đã đăng")
    return Outcome()


# ----------------------------------------------------------------- Facebook

_FB_DONE = re.compile(
    r"(your reel is|reel (has been|was) (shared|published)|is being (shared|published)|"
    r"thước phim của bạn|đã chia sẻ thước phim|đang đăng thước phim|đã đăng thước phim)",
    re.I,
)


def _facebook(page, content: Content, dry_run: bool) -> Outcome:
    page.goto("https://www.facebook.com/reels/create/", wait_until="domcontentloaded")
    page.wait_for_load_state("load")
    _require_login(
        "/login" in page.url or page.locator("input[name=email]").first.is_visible(), FACEBOOK
    )
    file_input = page.locator("input[type=file][accept*=video], input[type=file]").first
    file_input.wait_for(state="attached", timeout=STEP_TIMEOUT_MS)
    file_input.set_input_files(content.video)

    next_button = page.get_by_role("button", name=_names("Next", "Tiếp", "Tiếp tục"))
    textbox = page.locator("div[role=textbox][contenteditable=true]").first
    for _ in range(3):
        if textbox.is_visible():
            break
        _click_when_enabled(next_button, UPLOAD_TIMEOUT_MS, "nút Tiếp của Facebook")
        page.wait_for_timeout(2000)
    textbox.wait_for(state="visible", timeout=STEP_TIMEOUT_MS)
    _replace_text(page, textbox, content.full_text(FACEBOOK_CAPTION_LIMIT))

    publish = page.get_by_role(
        "button", name=_names("Publish", "Share", "Post", "Đăng", "Chia sẻ", "Xuất bản")
    )
    _wait_until(lambda: _enabled(publish), UPLOAD_TIMEOUT_MS, "Facebook tải video lên")
    if dry_run:
        return Outcome(dry_run=True)
    publish.first.click()
    _wait_until(
        lambda: "/reels/create" not in page.url
        or bool(_FB_DONE.search(page.locator("body").inner_text()))
        or not textbox.is_visible(),
        5 * 60 * 1000,
        "Facebook xác nhận đã đăng",
    )
    # Facebook còn xử lý sau khi bấm Đăng; giữ tab thêm chút cho chắc.
    page.wait_for_timeout(10_000)
    return Outcome()


_FLOWS = {YOUTUBE: _youtube, TIKTOK: _tiktok, FACEBOOK: _facebook}


def screenshot_dir() -> str:
    return utils.storage_dir(os.path.join("social", "screenshots"), create=True)


def publish(platform: str, content: Content, dry_run: bool = False, label: str = "") -> Outcome:
    """
    Đăng ``content`` lên ``platform``. Ném NotLoggedIn khi chưa đăng nhập, PublishError
    (kèm đường dẫn ảnh chụp màn hình) khi lỗi.
    """
    if platform not in _FLOWS:
        raise PublishError(f"Nền tảng không hỗ trợ: {platform}")
    if not os.path.isfile(content.video):
        raise PublishError(f"Không thấy file video: {content.video}")
    with social_browser.connect() as context:
        page = context.new_page()
        page.set_default_timeout(STEP_TIMEOUT_MS)
        keep_open = dry_run
        try:
            outcome = _FLOWS[platform](page, content, dry_run)
            logger.info(f"published to {platform}: {content.video} {outcome}")
            return outcome
        except NotLoggedIn:
            keep_open = True
            raise
        except Exception as exc:
            keep_open = True
            shot = os.path.join(
                screenshot_dir(), f"{time.strftime('%Y%m%d-%H%M%S')}-{label or 'post'}-{platform}.png"
            )
            try:
                page.screenshot(path=shot, full_page=True)
            except Exception:
                shot = ""
            logger.exception(f"publish to {platform} failed: {exc}")
            message = str(exc).splitlines()[0][:300] if str(exc) else type(exc).__name__
            if not isinstance(exc, PublishError):
                message = f"{type(exc).__name__}: {message}"
            raise PublishError(message + (f"\nẢnh chụp màn hình: {shot}" if shot else "")) from exc
        finally:
            # Lỗi hoặc chạy thử thì để tab mở cho người dùng xem; xong thì đóng.
            if not keep_open:
                try:
                    page.close()
                except Exception:
                    pass
