"""
Trang "Tạo nhanh" của WebUI: tạo video hoặc ảnh GIF có chữ theo loại nội dung,
cùng chức năng với bot Telegram (telegram_bot.py).

Bot lệnh                      Trên trang này
/kienthuc, /dongluc...        Tạo một mục: chọn loại nội dung, gõ nội dung
#gif, #high, #45s, #ngang...  Ô chọn bên dưới, hoặc gõ thẳng vào nội dung như trên bot
hỏi lại khi thiếu thông tin   Câu hỏi bổ sung, trả lời hoặc "Tạo luôn"
ảnh/album kèm caption         Tải ảnh/video lên (sản phẩm, địa điểm)
/hangloat, /dunghangloat      Tạo hàng loạt: duyệt, sửa trực tiếp, góp ý, đề xuất lại, dừng
/trangthai                    Hàng đợi & kết quả
/thoiluong, /ngonngu          Ô thời lượng và ngôn ngữ ([telegram].default_* trong config.toml)
video/ảnh GIF gửi về chat     Xem ngay, kèm nội dung đăng bài chuẩn SEO và kịch bản
"""

from __future__ import annotations

import hashlib
import html
import math
import os
import sys
import time
from uuid import uuid4

import pandas as pd
import streamlit as st
from loguru import logger

from app.models import const
from app.services import content_presets as cp
from app.services import output_library
from app.services import quick_create as qc
from app.services import quick_jobs as qj
from app.services import social_schedule
from webui import social_page
from app.utils import utils

ASPECT_LABELS = {
    "9:16": "Dọc 9:16 (#doc)",
    "16:9": "Ngang 16:9 (#ngang)",
    "1:1": "Vuông 1:1 (#vuong)",
}
KIND_LABELS = {qj.VIDEO: "Video lồng tiếng", qj.GIF: "Ảnh GIF có chữ (#gif)"}
STATE_ICONS = {
    qj.QUEUED: "⏳",
    qj.RUNNING: "⚙️",
    qj.DONE: "✅",
    qj.FAILED: "❌",
    qj.SKIPPED: "⏭️",
}
REDO_FEEDBACK = "Đề xuất danh sách mới, các chủ đề con khác hẳn danh sách trên."
MEDIA_TYPES = const.FILE_TYPE_IMAGES + const.FILE_TYPE_VIDEOS
MAX_SHOWN_JOBS = 30
LIBRARY_PAGE_SIZE = 10


def _preset_label(preset: cp.ContentPreset) -> str:
    return f"/{preset.command} – {preset.title}"


def _notice(text: str) -> None:
    """Thông báo hiển thị ở lần chạy kế tiếp (sau st.rerun)."""
    st.session_state["quick_notice"] = text


def _show_notice() -> None:
    text = st.session_state.pop("quick_notice", "")
    if text:
        st.success(text)


def _duration_input(preset: cp.ContentPreset, key: str, disabled: bool = False) -> int:
    default = qc.default_duration() or 0
    return int(
        st.number_input(
            "Thời lượng (giây)",
            min_value=0,
            max_value=cp.MAX_DURATION_SECONDS,
            value=default,
            step=5,
            key=key,
            disabled=disabled,
            help=(
                f"0 = mặc định của loại này ({qc.format_duration(preset.default_seconds)}). "
                f"Từ {cp.MIN_DURATION_SECONDS} đến {cp.MAX_DURATION_SECONDS} giây; gõ #45s "
                "hoặc #2p trong nội dung cũng được."
            ),
        )
    )


def _common_options(prefix: str, preset: cp.ContentPreset, gif: bool):
    """Khung hình, ngôn ngữ, thời lượng và #high, dùng chung cho một mục và hàng loạt."""
    aspect_col, language_col = st.columns(2)
    aspect = aspect_col.selectbox(
        "Khung hình",
        list(ASPECT_LABELS),
        format_func=ASPECT_LABELS.get,
        key=f"{prefix}_aspect",
    )
    languages = list(cp.LANGUAGES)
    language = language_col.selectbox(
        "Ngôn ngữ",
        languages,
        index=languages.index(qc.default_language()),
        format_func=qc.language_name,
        key=f"{prefix}_language",
        help="#en: lời đọc tiếng Anh, phụ đề tiếng Việt; #vi: tiếng Việt.",
    )
    duration = _duration_input(preset, f"{prefix}_duration", disabled=gif)
    high = st.checkbox(
        f"#high – AI dùng model mạnh hơn ({qc.high_model()})",
        key=f"{prefix}_high",
        help="Mặc định dùng model trong Cài đặt; #high cho logic và chất lượng tốt hơn.",
    )
    post = None
    if not gif:
        post = st.checkbox(
            "#dang – lên lịch đăng Facebook, TikTok, YouTube sau khi tạo",
            value=social_schedule.get_settings()["auto_post"],
            key=f"{prefix}_post",
            help=(
                "Video được xếp vào khung giờ đăng trống kế tiếp (xem tab Đăng bài). "
                "Gõ #dang / #khongdang trong nội dung cũng được."
            ),
        )
    return aspect, language, duration, high, post


def _kind_input(key: str, preset: cp.ContentPreset) -> bool:
    """True nếu chọn ảnh GIF. Sản phẩm cần ảnh thật nên chỉ tạo được video."""
    if preset.requires_media:
        st.caption(f"/{preset.command} cần ảnh/video thật của bạn nên chỉ tạo video.")
        return False
    kind = st.segmented_control(
        "Thành phẩm",
        list(KIND_LABELS),
        format_func=KIND_LABELS.get,
        default=qj.VIDEO,
        key=key,
    )
    return kind == qj.GIF


def _save_uploads(files) -> list[str]:
    folder = utils.storage_dir("local_videos", create=True)
    paths = []
    for index, file in enumerate(files or [], start=1):
        extension = os.path.splitext(file.name)[1].lower()
        if extension.lstrip(".") not in MEDIA_TYPES:
            continue
        path = os.path.join(folder, f"web-{uuid4().hex}-{index}{extension}")
        with open(path, "wb") as output:
            output.write(file.getbuffer())
        paths.append(path)
    return paths


# ------------------------------------------------------------------ một mục


def _submit(jobs: qj.QuickJobs, request: dict) -> None:
    job = jobs.submit(**request)
    st.session_state.pop("quick_draft", None)
    st.session_state["quick_clear_inputs"] = True
    kind = "ảnh GIF" if request.get("gif") else "video"
    position = jobs.waiting() - 1
    note = f" Đang chờ {position} video phía trước." if kind == "video" and position > 0 else ""
    _notice(f"Đã nhận yêu cầu {kind}: {job.title}.{note} Theo dõi ở cột Hàng đợi & kết quả.")
    st.rerun()


def _render_draft(jobs: qj.QuickJobs, draft: dict) -> None:
    preset = cp.PRESETS[draft["preset_key"]]
    kind = preset.title.split("/")[0].strip().lower()
    with st.container(border=True):
        st.markdown(f"**Để video {kind} hay và đúng hơn, bạn cho mình biết thêm:**")
        for index, question in enumerate(draft["questions"], start=1):
            st.markdown(f"{index}. {question}")
        st.caption(f"Yêu cầu: {cp.cover_title(draft['prompt'], 200)}")
        answer = st.text_area(
            "Trả lời tất cả trong một lần",
            key="quick_answer",
            height=110,
            help="Có thể thêm tuỳ chọn như #45s, #ngang, #en, #high.",
        )
        send_col, go_col, cancel_col = st.columns(3)
        if send_col.button("Gửi trả lời & tạo", type="primary", width="stretch"):
            text, options = qc.parse_options(answer)
            error = qc.duration_error(options.duration)
            if error:
                st.error(error)
                return
            request = {key: value for key, value in draft.items() if key != "questions"}
            request.update(
                high=request["high"] or options.high,
                aspect=options.aspect or request["aspect"],
                language=options.language or request["language"],
                duration=options.duration or request["duration"],
                post=request["post"] if options.post is None else options.post,
            )
            if text:
                request["prompt"] = cp.merge_answers(request["prompt"], draft["questions"], text)
            _submit(jobs, request)
        if go_col.button("Tạo luôn", width="stretch"):
            _submit(jobs, {key: value for key, value in draft.items() if key != "questions"})
        if cancel_col.button("Huỷ", width="stretch"):
            st.session_state.pop("quick_draft", None)
            st.rerun()


def _render_single(jobs: qj.QuickJobs) -> None:
    draft = st.session_state.get("quick_draft")
    if draft:
        _render_draft(jobs, draft)
        return
    if st.session_state.pop("quick_clear_inputs", False):
        for key in ("quick_prompt", "quick_answer", "quick_files"):
            st.session_state.pop(key, None)

    presets = list(cp.PRESETS)
    preset = cp.PRESETS[
        st.selectbox(
            "Loại nội dung",
            presets,
            format_func=lambda key: _preset_label(cp.PRESETS[key]),
            key="quick_preset",
        )
    ]
    st.caption(f"{preset.description}  \nVí dụ trên bot: `{preset.example}`")
    prompt = st.text_area(
        "Nội dung",
        key="quick_prompt",
        height=130,
        placeholder=preset.example.split(" ", 1)[-1],
        help=(
            "Gõ được tuỳ chọn như trên bot: #gif, #high, #45s / #2p, #doc / #ngang / "
            "#vuong, #en / #vi. Tuỳ chọn gõ trong nội dung được ưu tiên hơn ô chọn."
        ),
    )
    gif = _kind_input("quick_kind", preset)
    aspect, language, duration, high, post = _common_options("quick", preset, gif)
    files = []
    if preset.accepts_media and not gif:
        required = " (bắt buộc)" if preset.requires_media else ""
        files = st.file_uploader(
            f"Ảnh/video của bạn{required}",
            type=MEDIA_TYPES,
            accept_multiple_files=True,
            key="quick_files",
            help="Mỗi tệp hiển thị tối đa 10 giây; giữ đúng thứ tự tải lên.",
        ) or []

    if not st.button("Tạo", type="primary", key="quick_submit", width="stretch"):
        return
    text, options = qc.parse_options(prompt)
    gif = gif or options.gif
    duration = options.duration if options.duration is not None else (duration or None)
    error = qc.duration_error(duration) or qc.request_error(preset, text, len(files), gif)
    if error:
        st.error(error)
        return
    request = {
        "preset_key": preset.key,
        "prompt": text,
        "gif": gif,
        "aspect": options.aspect or aspect,
        "duration": None if gif else duration,
        "language": options.language or language,
        "high": high or options.high,
        "post": None if gif else (post if options.post is None else options.post),
        "material_paths": _save_uploads(files),
    }
    seconds = duration or preset.default_seconds
    needed = -(-seconds // 10)
    if request["material_paths"] and len(request["material_paths"]) < needed:
        st.warning(
            f"Nên gửi ít nhất {needed} tệp cho video {qc.format_duration(seconds)} "
            "để hình ảnh không bị lặp."
        )
    if not gif and preset.clarify:
        with st.spinner("Đang xem yêu cầu của bạn..."):
            try:
                with qc.llm_model(request["high"]):
                    questions = cp.clarifying_questions(
                        preset, text, len(request["material_paths"])
                    )
            except Exception:
                logger.exception("failed to check request for clarifying questions")
                questions = []
        if questions:
            st.session_state["quick_draft"] = {**request, "questions": questions}
            st.rerun()
    _submit(jobs, request)


# ---------------------------------------------------------------- hàng loạt


def _cell(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return " ".join(str(value).split())


def _render_plan(jobs: qj.QuickJobs, batch: qj.Batch) -> None:
    preset = batch.preset
    seconds = batch.duration or preset.default_seconds
    shape = (
        "Ảnh GIF có chữ, không lồng tiếng"
        if batch.gif
        else f"Mỗi video khoảng {qc.format_duration(seconds)}"
    )
    if st.session_state.get("quick_clear_feedback") == batch.id:
        st.session_state.pop("quick_clear_feedback")
        st.session_state.pop(f"quick_feedback_{batch.id}", None)
    with st.container(border=True):
        st.markdown(
            f"**Đề xuất {len(batch.topics)} {batch.unit} /{preset.command} ({preset.title})**  \n"
            f"Chủ đề: {cp.cover_title(batch.theme, 200)}  \n"
            f"{shape}, khung hình {batch.aspect or '9:16'}, "
            f"{qc.language_name(batch.language)}"
            + (f", model {qc.high_model()} (#high)" if batch.high else "")
        )
        if batch.note:
            st.warning(batch.note)
        version = hashlib.md5(
            repr([(topic.title, topic.content) for topic in batch.topics]).encode("utf-8")
        ).hexdigest()[:8]
        edited = st.data_editor(
            pd.DataFrame(
                [{"Chủ đề con": t.title, "Ý chính": t.content} for t in batch.topics],
                columns=["Chủ đề con", "Ý chính"],
            ),
            num_rows="dynamic",
            width="stretch",
            key=f"quick_plan_{batch.id}_{version}",
            column_config={
                "Chủ đề con": st.column_config.TextColumn(width="medium", required=True),
                "Ý chính": st.column_config.TextColumn(width="large"),
            },
        )
        topics = [
            cp.Subtopic(_cell(row.get("Chủ đề con")), _cell(row.get("Ý chính")))
            for row in edited.to_dict("records")
        ]
        topics = [topic for topic in topics if topic.title]
        st.caption("Sửa thẳng trong bảng (thêm/xoá dòng được), hoặc nhắn góp ý để AI sửa.")
        feedback = st.text_input(
            "Góp ý cho AI",
            key=f"quick_feedback_{batch.id}",
            placeholder="Ví dụ: bỏ số 3, thêm chủ đề về tiền điện",
        )
        go_col, revise_col, redo_col, cancel_col = st.columns(4)
        if go_col.button(
            f"✅ Duyệt & tạo {len(topics)}", type="primary", key=f"quick_go_{batch.id}",
            width="stretch", disabled=not topics,
        ):
            jobs.set_topics(batch.id, topics)
            try:
                jobs.approve_batch(batch.id)
            except ValueError as exc:
                st.error(str(exc))
                return
            _notice(f"Đã duyệt, bắt đầu tạo {len(topics)} {batch.unit}.")
            st.rerun()
        revise = revise_col.button(
            "✏️ Sửa theo góp ý", key=f"quick_revise_{batch.id}", width="stretch",
            disabled=not feedback.strip(),
        )
        redo = redo_col.button("🔄 Đề xuất lại", key=f"quick_redo_{batch.id}", width="stretch")
        if revise or redo:
            # Giữ phần người dùng đã tự sửa trong bảng trước khi AI sửa tiếp.
            jobs.set_topics(batch.id, topics)
            with st.spinner("Đang sửa danh sách chủ đề con..."):
                try:
                    jobs.revise_batch(batch.id, feedback if revise else REDO_FEEDBACK)
                except Exception as exc:
                    st.error(str(exc))
                    return
            st.session_state["quick_clear_feedback"] = batch.id
            st.rerun()
        if cancel_col.button("❌ Huỷ", key=f"quick_cancel_{batch.id}", width="stretch"):
            jobs.cancel_batch(batch.id)
            st.rerun()


def _render_batch(jobs: qj.QuickJobs) -> None:
    if st.session_state.pop("quick_clear_batch_theme", False):
        st.session_state.pop("quick_batch_theme", None)
    for batch in jobs.batches():
        if batch.state == qj.REVIEW:
            _render_plan(jobs, batch)

    st.markdown("**Đề xuất loạt mới**")
    st.caption(
        "AI đề xuất các chủ đề con kèm ý chính, bạn duyệt xong mới tạo và lưu lần lượt "
        "từng mục, giống /hangloat trên bot. Không gồm sản phẩm và tin tức."
    )
    commands = list(qc.BATCH_PRESETS)
    preset = qc.BATCH_PRESETS[
        st.selectbox(
            "Loại nội dung",
            commands,
            format_func=lambda command: _preset_label(qc.BATCH_PRESETS[command]),
            key="quick_batch_preset",
        )
    ]
    theme = st.text_area(
        "Chủ đề lớn",
        key="quick_batch_theme",
        height=90,
        placeholder="Ví dụ: tiết kiệm tiền cho sinh viên",
        help="Gõ được tuỳ chọn như /hangloat: #15, #gif, #high, #45s, #ngang, #en.",
    )
    count = int(
        st.number_input(
            "Số lượng",
            min_value=1,
            max_value=cp.MAX_BATCH_TOPICS,
            value=qc.DEFAULT_BATCH_SIZE,
            key="quick_batch_count",
        )
    )
    gif = _kind_input("quick_batch_kind", preset)
    aspect, language, duration, high, post = _common_options("quick_batch", preset, gif)
    if not st.button("Đề xuất chủ đề con", type="primary", key="quick_batch_propose", width="stretch"):
        return
    text, options = qc.parse_options(theme, batch=True)
    gif = gif or options.gif
    count = options.count if options.count is not None else count
    duration = options.duration if options.duration is not None else (duration or None)
    error = qc.duration_error(duration)
    if not error and not 1 <= count <= cp.MAX_BATCH_TOPICS:
        error = f"Số lượng phải từ 1 đến {cp.MAX_BATCH_TOPICS}."
    if not error and len(text) < preset.min_prompt_length:
        error = "Hãy nhập chủ đề lớn cụ thể hơn."
    if error:
        st.error(error)
        return
    with st.spinner(f"Đang đề xuất {count} chủ đề con cho /{preset.command}..."):
        try:
            jobs.propose_batch(
                preset.key,
                text,
                count,
                gif=gif,
                aspect=options.aspect or aspect,
                duration=None if gif else duration,
                language=options.language or language,
                high=high or options.high,
                post=None if gif else (post if options.post is None else options.post),
            )
        except Exception as exc:
            logger.exception("failed to propose batch subtopics")
            st.error(str(exc))
            return
    st.session_state["quick_clear_batch_theme"] = True
    st.rerun()


# --------------------------------------------------------- hàng đợi & kết quả


def _has_active(jobs: qj.QuickJobs) -> bool:
    return any(job.active for job in jobs.jobs()) or any(
        batch.state == qj.BATCH_RUNNING for batch in jobs.batches()
    )


def _elapsed(seconds: float) -> str:
    if seconds >= 60:
        return f"{seconds / 60:.1f} phút"
    return f"{seconds:.0f} giây"


def _render_batch_status(jobs: qj.QuickJobs, batch: qj.Batch) -> None:
    total = len(batch.topics)
    done = batch.sent + len(batch.failed)
    lines = [
        f"**Loạt {total} {batch.unit} /{batch.preset.command}** – "
        f"{cp.cover_title(batch.theme, 80)}",
        f"Đã xong {batch.sent}/{total}"
        + (
            f", lỗi {len(batch.failed)} (số {', '.join(map(str, batch.failed))})"
            if batch.failed
            else ""
        ),
    ]
    if batch.state == qj.FINISHED:
        lines.append("Đã dừng theo yêu cầu." if batch.stopped else "Đã hoàn tất.")
    elif batch.stopped:
        lines.append(f"Sẽ dừng sau {batch.unit} đang tạo.")
    elif done:
        minutes = (time.time() - batch.started) / done * (total - done) / 60
        eta = f"{minutes / 60:.1f} giờ" if minutes >= 60 else f"{max(round(minutes), 1)} phút"
        lines.append(f"Còn lại khoảng {eta}.")
    with st.container(border=True):
        st.markdown("  \n".join(lines))
        if total:
            st.progress(min(done / total, 1.0))
        if batch.state == qj.BATCH_RUNNING and not batch.stopped:
            st.button(
                f"⏹ Dừng sau {batch.unit} đang tạo",
                key=f"quick_stop_{batch.id}",
                on_click=jobs.stop_batch,
                args=(batch.id,),
            )


def _render_result(job: qj.Job) -> None:
    media = next(
        (
            path
            for path in job.files
            if path.lower().endswith(".gif" if job.kind == qj.GIF else ".mp4")
        ),
        None,
    )
    tabs = st.tabs(["Thành phẩm", "Nội dung đăng bài" if job.kind == qj.VIDEO else "Diễn giải", "Kịch bản"])
    with tabs[0]:
        if media and os.path.exists(media):
            if job.kind == qj.GIF:
                st.image(media)
            else:
                st.video(media)
        else:
            st.caption("Không tìm thấy file (có thể đã được chuyển hoặc xoá).")
        for path in job.files:
            st.caption(path)
    with tabs[1]:
        if job.keyword:
            st.caption(f"Từ khoá chính: {job.keyword}")
        st.code(job.post_text or "(không có)", language=None, wrap_lines=True)
    with tabs[2]:
        st.code(job.script or "(không có)", language=None, wrap_lines=True)


def _render_job(job: qj.Job) -> None:
    preset = job.preset
    number = f"[{job.number}] " if job.batch_id else ""
    details = [
        "Ảnh GIF" if job.kind == qj.GIF else "Video",
        f"/{preset.command}",
        qc.language_name(job.language),
    ]
    if job.aspect:
        details.append(job.aspect)
    if job.high:
        details.append(f"#high ({qc.high_model()})")
    with st.container(border=True):
        title = html.escape(cp.cover_title(job.title, 120))
        st.markdown(
            f"{STATE_ICONS.get(job.state, '')} {number}<b>{title}</b><br>"
            f"<small>{html.escape(' · '.join(details))}</small>",
            unsafe_allow_html=True,
        )
        if job.state == qj.QUEUED:
            st.caption("Đang chờ trong hàng đợi.")
        elif job.state == qj.RUNNING:
            if job.kind == qj.VIDEO:
                st.progress(min(max(job.progress, 0), 100), text=job.stage or "Đang tạo...")
            else:
                st.caption(job.stage or "Đang tạo...")
        elif job.state == qj.FAILED:
            st.error(job.error[:2000])
        elif job.state == qj.SKIPPED:
            st.caption(job.stage)
        elif job.state == qj.DONE:
            saved = ", ".join(job.saved_names) or "chưa lưu được vào thư mục thành phẩm"
            st.caption(f"Xong sau {_elapsed(job.finished - job.started)} · Đã lưu: {saved}")
            if job.schedule_note:
                st.caption(f"📅 {job.schedule_note}")
            # Chỉ nạp video khi người dùng mở xem, vì danh sách tự làm mới liên tục.
            if st.toggle("Xem thành phẩm", key=f"quick_show_{job.id}"):
                _render_result(job)


def _queue_body(jobs: qj.QuickJobs) -> None:
    all_jobs = jobs.jobs()
    running = sum(1 for job in all_jobs if job.state == qj.RUNNING)
    waiting = sum(1 for job in all_jobs if job.state == qj.QUEUED)
    st.caption(f"Đang tạo: {running} · Đang chờ: {waiting}")
    for batch in jobs.batches():
        if batch.state in (qj.BATCH_RUNNING, qj.FINISHED):
            _render_batch_status(jobs, batch)
    if not all_jobs:
        st.info("Chưa có yêu cầu nào. Thành phẩm cũ xem ở tab Thư viện thành phẩm.")
        return
    for job in all_jobs[:MAX_SHOWN_JOBS]:
        _render_job(job)
    if any(not job.active for job in all_jobs):
        st.button(
            "Xoá các mục đã xong khỏi danh sách",
            key="quick_clear_finished",
            on_click=jobs.remove_finished,
            help="Chỉ xoá khỏi danh sách này; thành phẩm vẫn nằm trong thư mục.",
        )


@st.fragment(run_every="2s")
def _queue_live(jobs: qj.QuickJobs) -> None:
    if not _has_active(jobs):
        # Hết việc thì vẽ lại cả trang một lần để chuyển sang danh sách tĩnh.
        st.rerun(scope="app")
    _queue_body(jobs)


@st.fragment
def _queue_static(jobs: qj.QuickJobs) -> None:
    _queue_body(jobs)


# ------------------------------------------------------- thư viện thành phẩm


def _library_items(kind: str) -> list[tuple[str, dict[str, str]]]:
    """Các mục "#NNN tiêu đề" trong storage/output/<kind>, mới nhất trước."""
    folder = output_library.output_dir(kind)
    groups: dict[str, dict[str, str]] = {}
    for name in os.listdir(folder):
        stem, extension = os.path.splitext(name)
        if stem.startswith("#"):
            groups.setdefault(stem, {})[extension.lower()] = os.path.join(folder, name)

    def index(stem: str) -> int:
        number = stem[1:].split(" ", 1)[0]
        return int(number) if number.isdigit() else 0

    return sorted(groups.items(), key=lambda item: index(item[0]), reverse=True)


def _read_text(path: str | None, limit: int = 1500) -> str:
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as file:
            return file.read(limit)
    except OSError:
        return ""


def _render_library() -> None:
    kind = st.segmented_control(
        "Loại thành phẩm",
        [qj.VIDEO, qj.GIF],
        format_func={qj.VIDEO: "Video", qj.GIF: "Ảnh GIF"}.get,
        default=qj.VIDEO,
        key="quick_library_kind",
    ) or qj.VIDEO
    folder = output_library.output_dir(kind)
    items = _library_items(kind)
    st.caption(f"{len(items)} mục trong {folder}. Bot Telegram và trang này lưu chung một nơi.")
    if sys.platform == "win32" and st.button("Mở thư mục", key="quick_open_library"):
        os.startfile(folder)  # noqa: S606 - chỉ mở thư mục thành phẩm trên máy này
    if not items:
        return
    pages = max(math.ceil(len(items) / LIBRARY_PAGE_SIZE), 1)
    page = int(
        st.number_input("Trang", min_value=1, max_value=pages, value=1, key="quick_library_page")
    )
    for stem, files in items[(page - 1) * LIBRARY_PAGE_SIZE : page * LIBRARY_PAGE_SIZE]:
        with st.container(border=True):
            preview_col, text_col = st.columns([1, 2])
            preview = files.get(".gif") if kind == qj.GIF else files.get(".jpg")
            if preview:
                preview_col.image(preview)
            with text_col:
                st.markdown(f"**{stem}**")
                text = _read_text(files.get(".txt"))
                if text:
                    st.caption(text[:400] + ("…" if len(text) > 400 else ""))
                video = files.get(".mp4")
                if kind == qj.VIDEO and video and st.toggle("Xem video", key=f"quick_lib_{stem}"):
                    st.video(video)


# ------------------------------------------------------------------- trang


def render() -> None:
    jobs = qj.shared()
    st.caption(
        "Tạo video hoặc ảnh GIF có chữ theo loại nội dung, giống bot Telegram: cùng cú "
        "pháp (#gif, #high, #45s, #ngang, #en), cùng kịch bản, nội dung đăng bài chuẩn SEO, "
        "ảnh bìa và cùng lưu vào thư mục thành phẩm storage/output. Giọng đọc, phụ đề, nhạc "
        "nền, nguồn video và LLM lấy theo chế độ Tuỳ chỉnh chi tiết và Cài đặt — bot cũng "
        "dùng chính các thiết lập này."
    )
    _show_notice()
    create_col, queue_col = st.columns([1, 1.15], gap="large")
    with create_col:
        single_tab, batch_tab, library_tab, social_tab = st.tabs(
            ["Tạo một mục", "Tạo hàng loạt", "Thư viện thành phẩm", "Đăng bài"]
        )
        with single_tab:
            _render_single(jobs)
        with batch_tab:
            _render_batch(jobs)
        with library_tab:
            _render_library()
        with social_tab:
            social_page.render()
    with queue_col:
        st.markdown("#### Hàng đợi & kết quả")
        if _has_active(jobs):
            _queue_live(jobs)
        else:
            _queue_static(jobs)
