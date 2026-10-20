"""
Trình duyệt dùng để đăng video lên Facebook Reels, TikTok và YouTube.

Chrome (hoặc Edge) chạy bằng một profile riêng (storage/social/browser_profile) và mở
cổng điều khiển CDP. Người dùng mở đúng trình duyệt này để đăng nhập các trang một lần
(nút "Mở trình duyệt để đăng nhập" trên web, lệnh /dangnhap trên bot); sau đó
Playwright kết nối vào chính trình duyệt đó qua CDP để đăng bài, dùng phiên đăng nhập
đã lưu trong profile. Không cần tải trình duyệt riêng của Playwright.

Cấu hình (tuỳ chọn) trong config.toml:

    [social]
    browser_path = ""      # bỏ trống: tự tìm Chrome, rồi Edge
    cdp_port = 9333
    profile_dir = ""       # bỏ trống: storage/social/browser_profile
    proxy = ""             # bỏ trống: dùng proxy hệ thống của Windows
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from contextlib import contextmanager

from loguru import logger

from app.config import config
from app.utils import utils

DEFAULT_CDP_PORT = 9333
LAUNCH_TIMEOUT_SECONDS = 30
LOGIN_URLS = {
    "facebook": "https://www.facebook.com/",
    "tiktok": "https://www.tiktok.com/login",
    "youtube": "https://studio.youtube.com/",
}
# Cookie chỉ có khi đã đăng nhập, dùng để kiểm tra nhanh trạng thái đăng nhập.
LOGIN_COOKIES = {
    "facebook": ("facebook.com", ("c_user",)),
    "tiktok": ("tiktok.com", ("sessionid", "sessionid_ss")),
    "youtube": ("youtube.com", ("LOGIN_INFO", "SAPISID", "__Secure-3PAPISID")),
}


class BrowserError(Exception):
    """Không mở hoặc không kết nối được trình duyệt đăng bài."""


def _settings() -> dict:
    return config._cfg.get("social", {}) or {}


def cdp_port() -> int:
    try:
        return int(_settings().get("cdp_port") or DEFAULT_CDP_PORT)
    except (TypeError, ValueError):
        return DEFAULT_CDP_PORT


def cdp_endpoint() -> str:
    return f"http://127.0.0.1:{cdp_port()}"


def profile_dir() -> str:
    configured = str(_settings().get("profile_dir") or "").strip()
    path = configured or os.path.join(utils.storage_dir("social", create=True), "browser_profile")
    os.makedirs(path, exist_ok=True)
    return path


def _candidates() -> list[str]:
    roots = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    paths = [
        os.path.join(root, "Google", "Chrome", "Application", "chrome.exe") for root in roots if root
    ] + [
        os.path.join(root, "Microsoft", "Edge", "Application", "msedge.exe") for root in roots if root
    ]
    for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
        found = shutil.which(name)
        if found:
            paths.append(found)
    return paths


def browser_path() -> str:
    configured = str(_settings().get("browser_path") or "").strip()
    if configured:
        if not os.path.isfile(configured):
            raise BrowserError(f"Không thấy trình duyệt ở [social].browser_path: {configured}")
        return configured
    for path in _candidates():
        if os.path.isfile(path):
            return path
    raise BrowserError("Không tìm thấy Chrome hoặc Edge; đặt [social].browser_path trong config.toml.")


def _get_json(path: str, method: str = "GET", timeout: float = 2.0):
    request = urllib.request.Request(cdp_endpoint() + path, method=method)
    # CDP chỉ nghe trên máy này; không đi qua proxy của hệ thống.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8") or "null")


def is_running() -> bool:
    """Trình duyệt đăng bài đang mở và nhận kết nối CDP."""
    try:
        return bool(_get_json("/json/version"))
    except Exception:
        return False


def launch(urls: list[str] | tuple[str, ...] = ()) -> bool:
    """
    Mở trình duyệt đăng bài nếu chưa mở; ``urls`` mở thành tab mới. Trả về True
    nếu vừa khởi động trình duyệt.
    """
    if is_running():
        for url in urls:
            try:
                _get_json("/json/new?" + urllib.parse.quote(url, safe=":/?=&"), method="PUT")
            except Exception as exc:
                logger.warning(f"cannot open tab {url}: {exc}")
        return False
    arguments = [
        browser_path(),
        f"--remote-debugging-port={cdp_port()}",
        f"--user-data-dir={profile_dir()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=CalculateNativeWinOcclusion",
        # Không tạm dừng tab nền: trang đăng bài vẫn chạy khi cửa sổ bị che.
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
    ]
    proxy = str(_settings().get("proxy") or "").strip()
    if proxy:
        arguments.append(f"--proxy-server={proxy}")
    arguments += list(urls)
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    logger.info(f"launch social browser: {arguments[0]} (profile {profile_dir()})")
    subprocess.Popen(
        arguments,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )
    deadline = time.monotonic() + LAUNCH_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if is_running():
            return True
        time.sleep(0.5)
    raise BrowserError(
        f"Trình duyệt chưa mở cổng điều khiển {cdp_port()}. Nếu đang có cửa sổ trình duyệt "
        "dùng cùng profile này mà mở không qua MoneyPrinterTurbo, hãy đóng nó rồi thử lại."
    )


def open_login_pages(platforms: list[str] | tuple[str, ...] = tuple(LOGIN_URLS)) -> None:
    """Mở trang đăng nhập các nền tảng trong trình duyệt đăng bài (lần đầu dùng)."""
    launch([LOGIN_URLS[name] for name in platforms if name in LOGIN_URLS])


@contextmanager
def connect():
    """
    Kết nối Playwright vào trình duyệt đăng bài (mở nếu chưa mở) và trả về context
    chứa phiên đăng nhập. Ngắt kết nối khi xong, không đóng trình duyệt.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserError("Chưa cài playwright: chạy update.bat (pip install -r requirements.txt).") from exc
    launch()
    # Proxy văn phòng (HTTP_PROXY) chặn cả 127.0.0.1: driver Playwright kế thừa biến
    # môi trường nên phải loại trừ localhost, và lấy địa chỉ websocket không qua proxy.
    for name in ("NO_PROXY", "no_proxy"):
        hosts = [host for host in os.environ.get(name, "").split(",") if host]
        os.environ[name] = ",".join(dict.fromkeys(hosts + ["127.0.0.1", "localhost"]))
    try:
        endpoint = _get_json("/json/version")["webSocketDebuggerUrl"]
    except Exception as exc:
        raise BrowserError(f"Không đọc được cổng điều khiển trình duyệt: {exc}") from exc
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(endpoint, timeout=30_000)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        yield context
    finally:
        # Chỉ dừng Playwright (ngắt CDP); trình duyệt và phiên đăng nhập vẫn mở.
        playwright.stop()


# Lỗi mạng chập chờn qua proxy văn phòng (TikTok hay bị reset vài phút rồi tự hết).
_TRANSIENT_NET_ERRORS = (
    "ERR_CONNECTION_RESET", "ERR_CONNECTION_CLOSED", "ERR_CONNECTION_REFUSED",
    "ERR_CONNECTION_TIMED_OUT", "ERR_TIMED_OUT", "ERR_EMPTY_RESPONSE", "ERR_NETWORK_CHANGED",
    "ERR_TUNNEL_CONNECTION_FAILED", "ERR_PROXY_CONNECTION_FAILED", "ERR_SOCKET_NOT_CONNECTED",
    "ERR_HTTP2_PROTOCOL_ERROR", "ERR_SSL_PROTOCOL_ERROR",
)
GOTO_RETRY_SECONDS = (5, 10, 20, 30, 45, 60)


def goto(page, url: str, wait_until: str = "domcontentloaded"):
    """``page.goto`` thử lại khi lỗi mạng tạm thời (tổng cộng chờ tối đa ~3 phút)."""
    for delay in (*GOTO_RETRY_SECONDS, None):
        try:
            return page.goto(url, wait_until=wait_until)
        except Exception as exc:
            if delay is None or not any(code in str(exc) for code in _TRANSIENT_NET_ERRORS):
                raise
            logger.warning(f"cannot open {url}, retry in {delay}s: {str(exc).splitlines()[0]}")
            page.wait_for_timeout(delay * 1000)


def login_status() -> dict[str, bool]:
    """Nền tảng nào đã đăng nhập, dựa vào cookie phiên trong profile."""
    with connect() as context:
        cookies = context.cookies()
    status = {}
    for platform, (domain, names) in LOGIN_COOKIES.items():
        status[platform] = any(
            cookie.get("name") in names and domain in (cookie.get("domain") or "")
            for cookie in cookies
        )
    return status
