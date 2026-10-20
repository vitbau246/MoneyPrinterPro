"""
Đăng một video lên Facebook Reels, TikTok hoặc YouTube (Shorts) bằng Playwright, qua
trình duyệt đăng bài đã đăng nhập (app/services/social_browser.py).

Mỗi nền tảng làm đúng các bước người dùng tự làm trên trang tải lên: chọn file, điền
tiêu đề/mô tả, chờ tải lên xong rồi bấm Đăng. Nút được tìm theo id ổn định của trang
hoặc theo tên nút tiếng Việt/tiếng Anh. ``dry_run`` dừng ngay trước khi bấm Đăng và để
tab mở cho người dùng xem lại. Lỗi chụp màn hình vào storage/social/screenshots.

Trước khi đăng, tài khoản đang đăng nhập phải đúng trang/kênh đã xác nhận
(app/services/social_accounts.py); chưa xác nhận hoặc khác tài khoản thì không đăng.
"""

from __future__ import annotations

import os
import re
import time
import unicodedata
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field

from loguru import logger

from app.services import social_accounts
from app.services import social_browser
from app.utils import utils

FACEBOOK = social_accounts.FACEBOOK
TIKTOK = social_accounts.TIKTOK
YOUTUBE = social_accounts.YOUTUBE
PLATFORMS = social_accounts.PLATFORMS
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
YOUTUBE_TAGS_LIMIT = 450
TIKTOK_CAPTION_LIMIT = 2200
FACEBOOK_CAPTION_LIMIT = 5000


class PublishError(Exception):
    """Không đăng được; thông báo dành cho người dùng."""


class AccountError(PublishError):
    """Lỗi tài khoản: thử lại cũng không được, người dùng phải xử lý."""


class NotLoggedIn(AccountError):
    """Trình duyệt đăng bài chưa đăng nhập nền tảng này."""


class NotConfirmed(AccountError):
    """Chưa xác nhận trang/kênh đăng bài cho nền tảng này."""


class WrongAccount(AccountError):
    """Trình duyệt đang đăng nhập tài khoản khác với trang/kênh đã xác nhận."""


class MaybePosted(PublishError):
    """Lỗi sau khi đã bấm Đăng: bài có thể đã lên, không tự đăng lại để tránh trùng."""


@dataclass
class Content:
    video: str
    title: str
    description: str = ""
    # Thẻ tìm kiếm YouTube.
    tags: list[str] = field(default_factory=list)

    def full_text(self, limit: int) -> str:
        text = "\n\n".join(part for part in (self.title.strip(), self.description.strip()) if part)
        return text[:limit]


@dataclass
class Outcome:
    url: str = ""
    dry_run: bool = False
    # Trang/kênh đã đăng lên.
    account: str = ""


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


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text or ""))


def _replace_text(page, box, text: str) -> None:
    """
    Xoá nội dung ô soạn thảo (contenteditable) rồi nhập ``text``. Gõ từng phím có lúc
    rớt chữ có dấu (TikTok từng đăng "Vợt" thay cho "Vượt"), nên kiểm tra lại nội dung và
    nhập lại cả dòng một lần nếu sai; vẫn sai thì dừng, chưa bấm Đăng.
    """
    for attempt in range(2):
        box.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if line:
                if attempt == 0:
                    page.keyboard.type(line, delay=5)
                else:
                    page.keyboard.insert_text(line)
            if index < len(lines) - 1:
                page.keyboard.press("Shift+Enter")
        page.wait_for_timeout(500)
        typed = box.inner_text()
        if _squash(typed) == _squash(text):
            return
        logger.warning(f"typed text mismatch (attempt {attempt + 1}): {typed[:120]!r} != {text[:120]!r}")
    raise PublishError("Nhập tiêu đề/mô tả bị sai chữ; chưa bấm Đăng.")


@contextmanager
def _after_post(platform: str):
    """Lỗi sau khi đã bấm Đăng thành MaybePosted để không tự đăng lại."""
    try:
        yield
    except Exception as exc:
        raise MaybePosted(
            f"Đã bấm Đăng trên {PLATFORM_NAMES[platform]} nhưng không xác nhận được kết quả "
            f"({type(exc).__name__}: {str(exc).splitlines()[0][:200] if str(exc) else ''}). "
            "Bài có thể đã lên: kiểm tra trên trang trước khi đăng lại."
        ) from exc


def _check_account(platform: str, current: social_accounts.Account | None,
                   expected: social_accounts.Account) -> None:
    """Dừng nếu chưa đăng nhập hoặc đang đăng nhập khác trang/kênh đã xác nhận."""
    _require_login(current is None, platform)
    if not expected.same_as(current):
        raise WrongAccount(
            f"{PLATFORM_NAMES[platform]} đang đăng nhập {current.label() if current.name else current.id}, "
            f"khác trang/kênh đã xác nhận {expected.label()}. Không đăng để tránh nhầm. Chuyển "
            "đúng tài khoản trong trình duyệt đăng bài, hoặc bấm “Kiểm tra đăng nhập” "
            "(/dangnhap kiemtra) để xác nhận tài khoản mới."
        )


def _require_login(condition: bool, platform: str) -> None:
    if condition:
        raise NotLoggedIn(
            f"Chưa đăng nhập {PLATFORM_NAMES[platform]} trong trình duyệt đăng bài. Bấm "
            "“Mở trình duyệt để đăng nhập” trên web (hoặc /dangnhap trên bot), đăng nhập "
            "một lần rồi thử lại."
        )


# ------------------------------------------------------------------ YouTube

_YT_UPLOADING = re.compile(r"(uploading|đang tải lên)[^\n]*\d+\s*%", re.I)
_YT_SHARE_URL = re.compile(r"https://(?:www\.)?youtu(?:\.be|be\.com)/[^\s?]+")


def _fill_youtube_tags(page, tags: list[str]) -> None:
    """Điền ô Thẻ (trong "Hiện thêm"); không điền được thì bỏ qua, không chặn việc đăng."""
    text = ""
    for tag in tags:
        candidate = f"{text}, {tag}" if text else tag
        if len(candidate) > YOUTUBE_TAGS_LIMIT:
            break
        text = candidate
    if not text:
        return
    try:
        # Chỉ tìm trong hộp tải lên: trang nền cũng có ô chip-bar ("Lọc") và nút #toggle-button.
        dialog = page.locator("ytcp-uploads-dialog")
        box = dialog.locator("#tags-container input#text-input").first
        if not box.is_visible():
            more = dialog.locator("#toggle-button").first
            more.scroll_into_view_if_needed()
            more.click()
        box.wait_for(state="visible", timeout=10_000)
        box.scroll_into_view_if_needed()
        box.click()
        box.fill(text)
        page.keyboard.press("Enter")
    except Exception as exc:
        logger.warning(f"cannot fill youtube tags: {exc}")


def _youtube(page, content: Content, dry_run: bool, expected: social_accounts.Account) -> Outcome:
    social_browser.goto(page, "https://www.youtube.com/upload")
    page.wait_for_load_state("load")
    _require_login("accounts.google.com" in page.url, YOUTUBE)
    # YouTube chuyển sang studio.youtube.com/channel/<kênh đang chọn>/videos/upload.
    try:
        page.wait_for_url(re.compile(r"/channel/UC"), timeout=STEP_TIMEOUT_MS)
    except Exception:
        pass
    channel = social_accounts.youtube_channel(page.url)
    _check_account(YOUTUBE, social_accounts.Account(channel, "") if channel else None, expected)
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
    _fill_youtube_tags(page, [clean(tag) for tag in content.tags])
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
    with _after_post(YOUTUBE):
        return _youtube_confirm(page, url)


def _youtube_confirm(page, url: str) -> Outcome:
    # Kiểm tra bản quyền chưa xong thì YouTube hỏi lại; nút chính của hộp thoại là
    # "Quay lại", nút phụ mới là "Vẫn xuất bản".
    # Thẻ ngoài của hộp thoại cao 0px (luôn "ẩn"); phải xem tp-yt-paper-dialog bên trong.
    shared = page.locator(
        "ytcp-video-share-dialog tp-yt-paper-dialog, ytcp-uploads-still-processing-dialog tp-yt-paper-dialog"
    )
    warning = page.locator("ytcp-prechecks-warning-dialog #secondary-action-button")

    def published() -> bool:
        _click_if_visible(warning)
        return any(shared.nth(index).is_visible() for index in range(shared.count()))

    _wait_until(published, 3 * 60 * 1000, "YouTube xác nhận đã xuất bản")
    share = page.locator("ytcp-video-share-dialog")
    found = _YT_SHARE_URL.search(share.first.inner_text()) if share.count() else None
    return Outcome(found[0] if found else url)


# ------------------------------------------------------------------- TikTok

_TT_HASHTAG = re.compile(r"(#[^\s#]+)")
# Gợi ý hashtag đi qua proxy văn phòng có lúc về chậm.
TIKTOK_SUGGESTION_SECONDS = 10


def _tiktok_hashtag(page, tag: str) -> bool:
    """
    Nhập hashtag thành link: TikTok chỉ tạo hashtag thật khi chọn từ danh sách gợi ý
    (gõ "#tag " rồi cách thì chỉ là chữ thường). Chỉ chọn gợi ý trùng đúng tag, vì Enter
    chọn gợi ý đầu tiên dù khác tag. Không có gợi ý trùng thì xoá tag và trả về False:
    để chữ thường thì lần chọn gợi ý sau có lúc thay cả đoạn từ dấu # này (mất tag, như
    #batdauthaydoi của #072), mà chữ thường cũng không thành link.
    """
    page.keyboard.insert_text(tag)
    # Chọn gợi ý ngay khi TikTok chưa kịp ghi nhận tag mới thì nó thay luôn hashtag vừa
    # chọn trước đó (#072 mất lúc #batdauthaydoi, lúc #nangluongnoitam): chờ trước và sau.
    page.wait_for_timeout(1200)
    items = page.locator(".mention-list-popover .hashtag-suggestion-item")
    deadline = time.monotonic() + TIKTOK_SUGGESTION_SECONDS
    while time.monotonic() < deadline:
        try:
            for index in range(items.count()):
                item = items.nth(index)
                if item.is_visible() and item.inner_text().split("\n")[0].strip().lower() == tag.lower():
                    item.click()
                    page.wait_for_timeout(1200)
                    return True
        except Exception:
            pass
        page.wait_for_timeout(300)
    for _ in tag:
        page.keyboard.press("Backspace")
    logger.info(f"tiktok: no hashtag suggestion for {tag}, dropped")
    return False


def _fill_tiktok_caption(page, editor, text: str, video: str) -> None:
    """
    Nhập chữ cả đoạn một lần, hashtag qua gợi ý. TikTok tự điền tên file vào mô tả vài
    giây sau khi chọn video, đè lên chữ đã nhập (từng ra caption "#071 Vượt qua sự trì
    hoãn" hay "Vợt"), nên chờ nó điền xong rồi mới nhập, và kiểm tra lại sau khi nhập.
    """
    stem = _squash(os.path.splitext(os.path.basename(video))[0])
    try:
        _wait_until(lambda: stem in _squash(editor.inner_text()), 20_000, "TikTok điền sẵn mô tả")
    except PublishError:
        pass
    page.wait_for_timeout(1500)
    for attempt in range(3):
        editor.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        # Nội dung đúng ra phải có trong ô, trừ các hashtag bị bỏ.
        expected = ""
        lines = text.splitlines()
        for index, line in enumerate(lines):
            # Sau một hashtag (đã chọn hoặc đã xoá) đã có sẵn dấu cách.
            after_tag = False
            for part in _TT_HASHTAG.split(line):
                if after_tag and part.startswith(" "):
                    part = part[1:]
                after_tag = False
                if _TT_HASHTAG.fullmatch(part):
                    if _tiktok_hashtag(page, part):
                        expected += part
                    after_tag = True
                elif part:
                    page.keyboard.insert_text(part)
                    expected += part
            if index < len(lines) - 1:
                page.keyboard.press("Shift+Enter")
        page.wait_for_timeout(1500)
        typed = editor.inner_text()
        if _squash(typed) == _squash(expected):
            return
        logger.warning(f"tiktok caption mismatch (attempt {attempt + 1}): {typed[-200:]!r} != {expected[-200:]!r}")
    raise PublishError("Nhập mô tả TikTok bị sai chữ; chưa bấm Đăng.")


_TT_DONE = re.compile(
    r"(your video has been uploaded|video của bạn đã được tải lên|đã đăng video|"
    r"video đã được đăng|manage your posts|quản lý bài đăng)",
    re.I,
)


def _tiktok(page, content: Content, dry_run: bool, expected: social_accounts.Account) -> Outcome:
    _check_account(TIKTOK, social_accounts.detect_tiktok(page), expected)
    social_browser.goto(page, "https://www.tiktok.com/tiktokstudio/upload?from=webapp")
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
    _fill_tiktok_caption(page, editor, content.full_text(TIKTOK_CAPTION_LIMIT), content.video)

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

    with _after_post(TIKTOK):
        _wait_until(posted, 5 * 60 * 1000, "TikTok xác nhận đã đăng")
    return Outcome()


# ----------------------------------------------------------------- Facebook

_FB_DONE = re.compile(
    r"(your reel is|reel (has been|was) (shared|published)|is being (shared|published)|"
    r"thước phim của bạn|đã chia sẻ thước phim|đang đăng thước phim|đã đăng thước phim)",
    re.I,
)


def _facebook(page, content: Content, dry_run: bool, expected: social_accounts.Account) -> Outcome:
    # Reels đăng dưới hồ sơ/Trang đang dùng (cookie i_user khi dùng Trang).
    account_id = social_accounts.facebook_id(page.context)
    _check_account(FACEBOOK, social_accounts.Account(account_id, "") if account_id else None, expected)
    social_browser.goto(page, "https://www.facebook.com/reels/create/")
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
    with _after_post(FACEBOOK):
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
    expected = social_accounts.confirmed().get(platform)
    if expected is None:
        raise NotConfirmed(
            f"Chưa xác nhận trang/kênh {PLATFORM_NAMES[platform]} để đăng. Đăng nhập đúng tài "
            "khoản trong trình duyệt đăng bài rồi bấm “Kiểm tra đăng nhập” (/dangnhap kiemtra)."
        )
    with social_browser.connect() as context:
        page = context.new_page()
        page.set_default_timeout(STEP_TIMEOUT_MS)
        keep_open = dry_run
        try:
            outcome = _FLOWS[platform](page, content, dry_run, expected)
            outcome.account = expected.label()
            logger.info(f"published to {platform} ({outcome.account}): {content.video} {outcome}")
            return outcome
        except WrongAccount:
            raise
        except AccountError:
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
            error = MaybePosted if isinstance(exc, MaybePosted) else PublishError
            raise error(message + (f"\nẢnh chụp màn hình: {shot}" if shot else "")) from exc
        finally:
            # Lỗi hoặc chạy thử thì để tab mở cho người dùng xem; xong thì đóng.
            if not keep_open:
                try:
                    page.close()
                except Exception:
                    pass
