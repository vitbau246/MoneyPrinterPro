"""
Trang/kênh đăng bài đã xác nhận, để không đăng nhầm tài khoản.

"Kiểm tra đăng nhập" (web) hoặc /dangnhap kiemtra (bot) đọc tài khoản đang đăng nhập
trong trình duyệt đăng bài và lưu vào storage/social/accounts.json:

- Facebook: hồ sơ hoặc Trang đang dùng (cookie i_user khi đang dùng Trang, c_user
  khi là trang cá nhân) – bài Reels đăng dưới tên này;
- TikTok: @username;
- YouTube: kênh (mã UC...) đang chọn trong YouTube Studio.

Trước mỗi lần đăng, app/services/social_publish.py so tài khoản đang đăng nhập với
tài khoản đã lưu; khác nhau thì dừng, không đăng.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass

from loguru import logger

from app.services import social_browser
from app.utils import utils

FACEBOOK = "facebook"
TIKTOK = "tiktok"
YOUTUBE = "youtube"
PLATFORMS = (FACEBOOK, TIKTOK, YOUTUBE)
DETECT_TIMEOUT_MS = 30_000

_YOUTUBE_CHANNEL_RE = re.compile(r"/channel/(UC[\w-]+)")


@dataclass
class Account:
    id: str
    name: str
    url: str = ""

    def label(self) -> str:
        if self.name and self.name != self.id:
            return f"{self.name} ({self.id})"
        return self.id

    def same_as(self, other: "Account | None") -> bool:
        return other is not None and self.id == other.id


def _path() -> str:
    return os.path.join(utils.storage_dir("social", create=True), "accounts.json")


def confirmed() -> dict[str, Account]:
    """Tài khoản đã xác nhận theo nền tảng."""
    try:
        with open(_path(), encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError):
        return {}
    return {
        platform: Account(**{key: str(value.get(key) or "") for key in ("id", "name", "url")})
        for platform, value in data.items()
        if platform in PLATFORMS and isinstance(value, dict) and value.get("id")
    }


def save(accounts: dict[str, Account | None]) -> dict[str, Account]:
    """Lưu kết quả kiểm tra: nền tảng chưa đăng nhập thì bỏ xác nhận cũ."""
    current = confirmed()
    for platform, account in accounts.items():
        if account is None:
            current.pop(platform, None)
        else:
            current[platform] = account
    temp = _path() + ".tmp"
    with open(temp, "w", encoding="utf-8") as file:
        json.dump({key: asdict(value) for key, value in current.items()}, file, ensure_ascii=False, indent=2)
    os.replace(temp, _path())
    return current


# ------------------------------------------------------------------ nhận diện


def facebook_id(context) -> str:
    """Mã hồ sơ đang dùng: Trang (i_user) nếu đang dùng Trang, ngược lại trang cá nhân (c_user)."""
    cookies = {cookie["name"]: cookie["value"] for cookie in context.cookies("https://www.facebook.com")}
    return cookies.get("i_user") or cookies.get("c_user") or ""


def detect_facebook(context, page) -> Account | None:
    account_id = facebook_id(context)
    if not account_id:
        return None
    social_browser.goto(page, f"https://www.facebook.com/profile.php?id={account_id}")
    # Tên Trang là h1 trong vùng nội dung chính (tiêu đề tab thường chỉ là "Facebook").
    name = ""
    try:
        heading = page.locator("div[role=main] h1").first
        heading.wait_for(state="visible", timeout=20_000)
        name = heading.inner_text().strip()
    except Exception:
        pass
    if not name:
        # Tiêu đề trang dạng "(3) Tên Trang | Facebook".
        title = re.sub(r"\s*\|\s*Facebook\s*$", "", re.sub(r"^\(\d+\)\s*", "", page.title() or "")).strip()
        name = "" if title == "Facebook" else title
    return Account(account_id, name or account_id, page.url)


_TIKTOK_USER_JS = """
async () => {
  try {
    const node = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');
    if (node) {
      const data = JSON.parse(node.textContent);
      const user = ((data.__DEFAULT_SCOPE__ || {})['webapp.app-context'] || {}).user;
      if (user && (user.uniqueId || user.uid)) {
        return {id: user.uniqueId || String(user.uid), name: user.nickName || ''};
      }
    }
  } catch (error) {}
  try {
    const response = await fetch('/passport/web/account/info/?aid=1459', {credentials: 'include'});
    const body = await response.json();
    const user = body && body.data;
    if (user && (user.username || user.user_id_str)) {
      return {id: user.username || user.user_id_str, name: user.screen_name || ''};
    }
  } catch (error) {}
  return null;
}
"""


def detect_tiktok(page) -> Account | None:
    social_browser.goto(page, "https://www.tiktok.com/")
    data = page.evaluate(_TIKTOK_USER_JS)
    if not data or not data.get("id"):
        return None
    username = str(data["id"]).lstrip("@")
    name = f"@{username}" + (f" – {data['name']}" if data.get("name") else "")
    return Account(f"@{username}", name, f"https://www.tiktok.com/@{username}")


def youtube_channel(url: str) -> str:
    match = _YOUTUBE_CHANNEL_RE.search(url or "")
    return match[1] if match else ""


def detect_youtube(page) -> Account | None:
    social_browser.goto(page, "https://studio.youtube.com/")
    try:
        page.wait_for_url(_YOUTUBE_CHANNEL_RE, timeout=DETECT_TIMEOUT_MS)
    except Exception:
        return None
    channel = youtube_channel(page.url)
    name = ""
    try:
        entity = page.locator("#entity-name").first
        entity.wait_for(state="visible", timeout=10_000)
        name = entity.inner_text().strip()
    except Exception:
        pass
    url = f"https://www.youtube.com/channel/{channel}"
    if not name:
        try:
            social_browser.goto(page, url)
            name = (page.locator("meta[property='og:title']").first.get_attribute("content") or "").strip()
        except Exception:
            pass
    return Account(channel, name or channel, url)


def detect(context, page, platform: str) -> Account | None:
    if platform == FACEBOOK:
        return detect_facebook(context, page)
    if platform == TIKTOK:
        return detect_tiktok(page)
    if platform == YOUTUBE:
        return detect_youtube(page)
    raise ValueError(platform)


def check_and_save() -> dict[str, Account | str | None]:
    """
    Đọc tài khoản đang đăng nhập trên từng nền tảng và lưu làm tài khoản đăng bài.
    Giá trị: Account (đã lưu), None (chưa đăng nhập, bỏ xác nhận cũ) hoặc chuỗi lỗi
    (không đọc được, giữ nguyên xác nhận cũ).
    """
    found: dict[str, Account | str | None] = {}
    with social_browser.connect() as context:
        page = context.new_page()
        page.set_default_timeout(DETECT_TIMEOUT_MS)
        try:
            for platform in PLATFORMS:
                try:
                    found[platform] = detect(context, page, platform)
                except Exception as exc:
                    logger.warning(f"cannot detect {platform} account: {exc}")
                    found[platform] = str(exc).splitlines()[0][:200] or type(exc).__name__
        finally:
            page.close()
    save({key: value for key, value in found.items() if not isinstance(value, str)})
    logger.info(f"social accounts check: { {k: v.label() if isinstance(v, Account) else v for k, v in found.items()} }")
    return found
