"""
Tab "Đăng bài" của trang Tạo nhanh: lên lịch đăng video lên Facebook Reels, TikTok và
YouTube Shorts, cùng chức năng với các lệnh /dangnhap, /dang, /lichdang, /tudongdang
của bot Telegram (lịch và thiết lập dùng chung, xem app/services/social_schedule.py).
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from datetime import datetime, timedelta

import streamlit as st

from app.services import social_accounts
from app.services import social_browser
from app.services import social_publish as sp
from app.services import social_schedule as ss

STATUS_ICONS = {
    ss.PENDING: "⏳",
    ss.RUNNING: "⚙️",
    ss.DONE: "✅",
    ss.FAILED: "❌",
    ss.CANCELLED: "🚫",
    ss.TRIED: "🧪",
}
WHEN_NEXT = "next"
WHEN_NOW = "now"
WHEN_AT = "at"
WHEN_LABELS = {
    WHEN_NEXT: "Khung giờ trống kế tiếp",
    WHEN_NOW: "Đăng ngay",
    WHEN_AT: "Chọn thời điểm",
}
MAX_SHOWN = 40


def _notice(text: str) -> None:
    st.session_state["social_notice"] = text


def _check_login() -> dict:
    """
    Đọc trang/kênh đang đăng nhập và lưu làm tài khoản đăng bài, ở luồng riêng
    (Playwright đồng bộ không chạy trong vòng asyncio).
    """
    result: dict = {}

    def work():
        try:
            result["status"] = social_accounts.check_and_save()
        except Exception as exc:
            result["error"] = str(exc)

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(90)
    if worker.is_alive():
        return {"error": "Quá thời gian kiểm tra (90 giây)."}
    return result


def _render_browser() -> None:
    st.markdown("**Trình duyệt đăng bài**")
    running = social_browser.is_running()
    runner = "web này" if ss.is_runner() else "tiến trình khác (bot Telegram) hoặc chưa chạy"
    st.caption(
        "Đăng bài bằng Chrome/Edge với profile riêng, điều khiển qua CDP. Lần đầu: mở trình "
        "duyệt, đăng nhập Facebook, TikTok, YouTube trong cửa sổ đó; các lần sau dùng lại "
        f"phiên đăng nhập. Profile: `{social_browser.profile_dir()}` · Trình duyệt: "
        f"{'đang mở' if running else 'chưa mở'} · Vòng đăng theo lịch chạy ở: {runner}."
    )
    open_col, check_col = st.columns(2)
    if open_col.button("Mở trình duyệt để đăng nhập", key="social_open", width="stretch"):
        try:
            social_browser.open_login_pages()
            st.success("Đã mở trình duyệt với các trang đăng nhập. Đăng nhập xong không cần đóng.")
        except social_browser.BrowserError as exc:
            st.error(str(exc))
    if check_col.button(
        "Kiểm tra đăng nhập & xác nhận trang/kênh",
        key="social_check",
        width="stretch",
        help="Đọc tài khoản đang đăng nhập trên từng nền tảng và lưu làm trang/kênh đăng bài. "
        "Lần đăng sau mà trình duyệt đang ở tài khoản khác thì sẽ không đăng.",
    ):
        with st.spinner("Đang kiểm tra (khoảng 30 giây)..."):
            st.session_state["social_login"] = _check_login()
    login = st.session_state.pop("social_login", None)
    if login and login.get("error"):
        st.error(login["error"])
    elif login:
        for name in sp.PLATFORMS:
            value = login["status"].get(name)
            if isinstance(value, str):
                st.warning(f"{sp.PLATFORM_NAMES[name]}: không đọc được tài khoản ({value}); giữ xác nhận cũ.")
            elif value is None:
                st.warning(f"{sp.PLATFORM_NAMES[name]}: chưa đăng nhập.")
    _render_accounts()


def _render_accounts() -> None:
    """Trang/kênh đã xác nhận – bài chỉ được đăng lên đúng các tài khoản này."""
    accounts = social_accounts.confirmed()
    lines = []
    for name in sp.PLATFORMS:
        account = accounts.get(name)
        if account:
            lines.append(f"✅ **{sp.PLATFORM_NAMES[name]}**: {account.label()}")
        else:
            lines.append(f"⚠️ **{sp.PLATFORM_NAMES[name]}**: chưa xác nhận – sẽ không đăng")
    st.markdown("Trang/kênh đăng bài đã xác nhận:  \n" + "  \n".join(lines))


def _render_new() -> None:
    st.markdown("**Lên lịch đăng**")
    if st.session_state.pop("social_reset_new", False):
        st.session_state.pop("social_videos", None)
    videos = ss.library_videos()
    if not videos:
        st.info("Chưa có video trong thư mục thành phẩm.")
        return
    names = {path: name for _, name, path in videos}
    selected = st.multiselect(
        "Video (mới nhất trước)",
        list(names),
        format_func=names.get,
        key="social_videos",
        placeholder="Chọn một hoặc nhiều video",
    )
    settings = ss.get_settings()
    platforms = st.multiselect(
        "Nền tảng",
        list(sp.PLATFORMS),
        default=settings["platforms"],
        format_func=sp.PLATFORM_NAMES.get,
        key="social_platforms",
    )
    when = st.radio(
        "Thời điểm",
        list(WHEN_LABELS),
        format_func=WHEN_LABELS.get,
        horizontal=True,
        key="social_when",
        help="Khung giờ trống: mỗi video một khung giờ trong thiết lập đăng tự động bên dưới.",
    )
    run_at = None
    if when == WHEN_AT:
        soon = datetime.now() + timedelta(hours=1)
        date_col, time_col = st.columns(2)
        day = date_col.date_input("Ngày", value=soon.date(), key="social_date", format="DD/MM/YYYY")
        moment = time_col.time_input("Giờ", value=soon.time().replace(second=0, microsecond=0), key="social_time")
        run_at = datetime.combine(day, moment).timestamp()
    missing = [name for name in platforms if name not in social_accounts.confirmed()]
    if missing:
        st.warning(
            "Chưa xác nhận trang/kênh cho "
            + ", ".join(sp.PLATFORM_NAMES[name] for name in missing)
            + ": bài cho nền tảng đó sẽ báo lỗi. Bấm “Kiểm tra đăng nhập & xác nhận trang/kênh” ở trên."
        )
    title = description = tags = None
    if len(selected) == 1:
        title, description, tags = _render_post_fields(selected[0])
    elif selected:
        st.caption(
            "Nhiều video: mỗi video dùng tiêu đề, mô tả, hashtag và thẻ AI đã viết khi tạo; video "
            "cũ chưa có thì AI tự viết từ lời thoại trước khi đăng."
        )
    dry_run = st.checkbox(
        "Chạy thử: điền xong nhưng không bấm Đăng (để tab mở cho bạn xem lại)",
        key="social_dry_run",
    )
    if not st.button("Lên lịch", type="primary", key="social_schedule", width="stretch", disabled=not selected):
        return
    if not platforms:
        st.error("Chọn ít nhất một nền tảng.")
        return
    if run_at is not None and run_at < datetime.now().timestamp() - 60:
        st.error("Thời điểm đã qua.")
        return
    scheduled = []
    for video in selected:
        scheduled.append(
            ss.schedule(
                video,
                platforms,
                time.time() if when == WHEN_NOW else run_at,
                title=title,
                description=description,
                tags=tags,
                source="web",
                dry_run=dry_run,
            )
        )
    times = ", ".join(ss.format_time(entry["run_at"]) for entry in scheduled[:5])
    _notice(f"Đã lên lịch {len(scheduled)} video: {times}{'…' if len(scheduled) > 5 else ''}.")
    st.session_state["social_reset_new"] = True
    st.rerun()


def _render_post_fields(video: str):
    """Tiêu đề, mô tả kèm hashtag và thẻ YouTube của một video, sửa được trước khi đăng."""
    key = hashlib.md5(video.encode("utf-8")).hexdigest()[:8]
    fields = (f"social_title_{key}", f"social_description_{key}", f"social_tags_{key}")
    if st.session_state.pop("social_reset_fields", None) == key:
        for name in fields:
            st.session_state.pop(name, None)
    saved_title, saved_description, saved_tags = ss.caption_for(video)
    cover = os.path.splitext(video)[0] + ".jpg"
    preview_col, text_col = st.columns([1, 2])
    if os.path.exists(cover):
        preview_col.image(cover)
    if not ss.has_post_info(video):
        preview_col.caption("Video này chưa có mô tả/hashtag do AI viết.")
        if preview_col.button("✨ Viết bằng AI", key=f"social_ai_{key}", width="stretch"):
            with st.spinner("AI đang viết tiêu đề, mô tả, hashtag và thẻ từ lời thoại..."):
                try:
                    generated = ss.generate_post_info(video)
                except Exception as exc:
                    generated = False
                    st.error(f"Không viết được: {exc}")
            if generated:
                st.session_state["social_reset_fields"] = key
                st.rerun()
            elif generated is None:
                st.error("AI chưa trả lời, thử lại sau ít phút.")
    title = text_col.text_input(
        "Tiêu đề (YouTube dùng làm tiêu đề, tối đa 100 ký tự)",
        value=saved_title,
        key=fields[0],
    )
    description = text_col.text_area(
        "Mô tả và hashtag (Facebook, TikTok dùng tiêu đề + phần này)",
        value=saved_description,
        key=fields[1],
        height=130,
    )
    tags_text = text_col.text_input(
        "Thẻ YouTube (phân cách bằng dấu phẩy)",
        value=", ".join(saved_tags),
        key=fields[2],
    )
    tags = [tag.strip() for tag in tags_text.split(",") if tag.strip()]
    return title, description, tags


def _render_entry(entry: dict) -> None:
    status = ss.entry_status(entry)
    with st.container(border=True):
        test = " · chạy thử" if entry.get("dry_run") else ""
        st.markdown(
            f"{STATUS_ICONS.get(status, '')} **{entry['name']}**  \n"
            f"{ss.format_time(entry['run_at'])}{test} · tạo từ {entry.get('source', 'web')}"
        )
        for platform, target in entry["targets"].items():
            line = f"{STATUS_ICONS.get(target['status'], '')} {sp.PLATFORM_NAMES[platform]}: {ss.STATUS_NAMES[target['status']]}"
            if target.get("account"):
                line += f" · {target['account']}"
            if target.get("url"):
                line += f" – {target['url']}"
            if target["status"] == ss.PENDING and target.get("error"):
                line += " (sẽ thử lại)"
            st.caption(line)
            if target.get("error") and target["status"] in (ss.FAILED, ss.PENDING):
                st.code(target["error"][:800], language=None, wrap_lines=True)
        now_col, cancel_col, remove_col = st.columns(3)
        can_run = any(t["status"] in (ss.PENDING, ss.FAILED, ss.CANCELLED) for t in entry["targets"].values())
        now_col.button(
            "▶ Đăng ngay" if status == ss.PENDING else "↻ Đăng lại",
            key=f"social_now_{entry['id']}",
            on_click=ss.run_now,
            args=(entry["id"],),
            disabled=not can_run,
            width="stretch",
        )
        cancel_col.button(
            "✖ Huỷ",
            key=f"social_cancel_{entry['id']}",
            on_click=ss.cancel,
            args=(entry["id"],),
            disabled=status != ss.PENDING,
            width="stretch",
        )
        remove_col.button(
            "🗑 Xoá khỏi lịch",
            key=f"social_remove_{entry['id']}",
            on_click=ss.remove,
            args=(entry["id"],),
            disabled=status == ss.RUNNING,
            width="stretch",
        )


@st.fragment(run_every="10s")
def _render_schedule() -> None:
    entries = ss.entries()
    upcoming = [e for e in entries if ss.entry_status(e) in (ss.PENDING, ss.RUNNING)]
    finished = [e for e in reversed(entries) if e not in upcoming]
    st.markdown(f"**Lịch đăng** – {len(upcoming)} bài đang chờ")
    if not entries:
        st.caption("Chưa có bài nào trong lịch.")
    for entry in (upcoming + finished)[:MAX_SHOWN]:
        _render_entry(entry)


def _render_auto() -> None:
    settings = ss.get_settings()
    if st.session_state.pop("social_reset_auto", False):
        for key in ("social_auto", "social_auto_platforms", "social_slots"):
            st.session_state.pop(key, None)
    with st.expander("Đăng tự động & khung giờ", expanded=False):
        auto = st.toggle(
            "Tự đăng mọi video mới tạo (bot và web)",
            value=settings["auto_post"],
            key="social_auto",
            help="Từng yêu cầu vẫn đổi được bằng #dang / #khongdang.",
        )
        platforms = st.multiselect(
            "Nền tảng mặc định",
            list(sp.PLATFORMS),
            default=settings["platforms"],
            format_func=sp.PLATFORM_NAMES.get,
            key="social_auto_platforms",
        )
        slots = st.text_input(
            "Khung giờ đăng mỗi ngày",
            value=", ".join(settings["slots"]),
            key="social_slots",
            help="Ví dụ: 8:00, 12:00, 19:30. Bỏ trống: đăng ngay khi tạo xong.",
        )
        if st.button("Lưu thiết lập", key="social_save_auto"):
            values = [value for value in slots.replace(";", ",").split(",") if value.strip()]
            normalized = ss.normalize_slots(values)
            if len(normalized) != len(values):
                st.error("Khung giờ không hợp lệ; dùng dạng 8:00 hoặc 19h30.")
                return
            ss.save_settings(auto_post=auto, platforms=platforms or None, slots=normalized)
            _notice("Đã lưu thiết lập đăng tự động (bot dùng chung, /tudongdang).")
            st.session_state["social_reset_auto"] = True
            st.rerun()


def render() -> None:
    text = st.session_state.pop("social_notice", "")
    if text:
        st.success(text)
    _render_browser()
    st.divider()
    _render_new()
    _render_auto()
    st.divider()
    _render_schedule()
