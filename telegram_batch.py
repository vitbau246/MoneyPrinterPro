"""
Tạo hàng loạt video (hoặc ảnh GIF có chữ với --gif) theo một preset, chạy tuần tự
và gửi qua Telegram ngay khi mỗi mục hoàn thành.

    python telegram_batch.py --preset dongluc --topics storage/batch/dongluc_101.txt
    python telegram_batch.py --preset dongluc --topics storage/batch/dongluc_101.txt --gif
    python telegram_batch.py ... --high      # AI dùng model [telegram].high_model

File chủ đề: mỗi dòng một chủ đề (dòng trống và dòng bắt đầu bằng # bị bỏ qua).
Tiến độ lưu ở <file chủ đề>.progress.json, loạt ảnh GIF lưu riêng ở
<file chủ đề>.gif.progress.json; chạy lại cùng lệnh sẽ bỏ qua các mục đã gửi.
Tạo file <file chủ đề>.stop để dừng sau mục đang chạy.

Thành phẩm (video cuối + ảnh bìa + lời thoại, hoặc ảnh GIF + bản MP4 + lời diễn giải)
được đánh số và lưu chung ở storage/output/video và storage/output/gif.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from loguru import logger

import telegram_bot as tg
from app.models import const
from app.services import content_presets as cp
from app.services import gif_maker
from app.services import output_library
from app.services import quick_create as qc
from app.services import social_schedule
from app.services import task as tm


def _load_topics(path: str) -> list[str]:
    with open(path, encoding="utf-8") as file:
        return [
            line.strip()
            for line in file
            if line.strip() and not line.strip().startswith("#")
        ]


def _load_progress(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as file:
            return json.load(file)
    except (OSError, ValueError):
        return {}


def _save_progress(path: str, progress: dict) -> None:
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(progress, file, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def _run_one(preset, topic: str, args) -> tuple[str, dict, cp.PostPackage | None, str]:
    """Tạo một video; trả về (task ID, kết quả, nội dung đăng bài, tiêu đề ảnh bìa)."""
    task_id = tg.utils.get_uuid()
    params = cp.build_params(
        preset,
        topic,
        video_aspect=args.aspect,
        duration_seconds=args.duration,
        language=args.language,
        voice_name=qc.language_voice(args.language),
    )
    # Viết kịch bản trước để có tiêu đề bìa và nội dung đăng bài chuẩn SEO.
    post = cp.prepare_script_and_post(preset, params)
    result = tm.start(task_id=task_id, params=params, stop_at="video")
    return task_id, result or {}, post, params.cover_title or cp.cover_title(topic)


def _run_gif_batch(
    preset, topics: list[str], progress: dict, progress_path: str, stop_path: str,
    chat_id: int, args,
) -> int:
    """Loạt ảnh GIF có chữ, không lồng tiếng: mỗi chủ đề một GIF, gửi ngay khi xong."""
    total = len(topics)
    pending = [i for i in range(total) if progress.get(str(i + 1), {}).get("status") != "sent"]
    tg.bot.send_message(
        chat_id,
        f"Bắt đầu tạo hàng loạt: {total} ảnh GIF /{preset.command} ({preset.title}), "
        f"có chữ, không lồng tiếng, ngôn ngữ: {qc.language_name(args.language)}.\n"
        f"Còn {len(pending)} ảnh GIF cần tạo. Ảnh được gửi lần lượt khi hoàn thành.",
    )
    sent_count = total - len(pending)
    failed: list[int] = []
    # Cảnh các ảnh trước trong loạt đã dùng, để AI chọn cảnh khác cho ảnh sau.
    used_terms: list[str] = []
    for index in pending:
        if os.path.exists(stop_path):
            logger.info("found stop file, stopping gif batch")
            tg.bot.send_message(
                chat_id, f"Đã dừng theo yêu cầu. Đã gửi {sent_count}/{total} ảnh GIF."
            )
            os.remove(stop_path)
            return 0

        number = index + 1
        topic = topics[index]
        label = f"#{number}/{total}"
        status = tg.bot.send_message(chat_id, f"Đang tạo ảnh GIF {label}: {topic}")
        job = tg.Job(
            chat_id=chat_id,
            reply_to=None,
            preset=preset,
            prompt=topic,
            aspect=args.aspect,
            status_message_id=status.message_id,
            language=args.language,
            gif=True,
        )
        started = time.monotonic()
        error = ""
        for attempt in range(1, args.retries + 2):
            try:
                gif_text = cp.generate_gif_text(preset, topic, args.language, used_terms[-12:])
                if gif_text is None:
                    raise gif_maker.GifError("AI chưa viết được nội dung.")
                used_terms.extend(gif_text.terms)
                result = gif_maker.create_text_gif(
                    gif_text.text, gif_text.terms, args.aspect,
                    tg.utils.storage_dir("gifs", create=True),
                )
                try:
                    # Dòng đầu caption chỉ để đánh số ảnh trong loạt, giống loạt video.
                    tg._send_gif(job, result, tg.gif_caption(f"[{number}/{total}]\n", gif_text))
                finally:
                    saved = qc.keep_gif(result, gif_text)
                error = ""
                break
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                logger.warning(f"{label} attempt {attempt} failed: {error}")

        if error:
            failed.append(number)
            progress[str(number)] = {"status": "failed", "topic": topic, "error": error}
            _save_progress(progress_path, progress)
            tg._edit_status(job, f"Ảnh GIF {label} lỗi, bỏ qua: {topic}\n{error}"[:4000])
            continue

        sent_count += 1
        seconds = time.monotonic() - started
        progress[str(number)] = {
            "status": "sent", "topic": topic, "text": gif_text.text, "detail": gif_text.detail,
            "output": saved.paths[0] if saved else result.path, "seconds": round(seconds, 1),
        }
        _save_progress(progress_path, progress)
        tg._edit_status(
            job,
            f"Đã gửi ảnh GIF {label} ({seconds:.0f} giây). Tổng: {sent_count}/{total}.\n"
            f"{qc.saved_note(saved, result.path)}",
        )

    summary = f"Hoàn tất hàng loạt ảnh GIF /{preset.command}: đã gửi {sent_count}/{total}."
    if failed:
        summary += (
            f"\nLỗi {len(failed)} ảnh GIF: {', '.join(map(str, failed))}. "
            "Chạy lại cùng lệnh để thử lại các ảnh lỗi."
        )
    tg.bot.send_message(chat_id, summary)
    logger.info(summary)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preset",
        required=True,
        # Preset bắt buộc ảnh/video riêng không chạy hàng loạt từ danh sách chủ đề.
        choices=sorted(c for c, p in cp.PRESETS_BY_COMMAND.items() if not p.requires_media),
    )
    parser.add_argument("--topics", required=True)
    parser.add_argument("--chat-id", type=int, default=None)
    parser.add_argument("--duration", type=int, default=None, help="giây, 15–180")
    parser.add_argument("--aspect", choices=["9:16", "16:9", "1:1"], default=None)
    parser.add_argument(
        "--language",
        choices=sorted(cp.LANGUAGES),
        default=None,
        help="mặc định theo /ngonngu của người nhận; en-US: lời đọc tiếng Anh, phụ đề tiếng Việt",
    )
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument(
        "--gif",
        action="store_true",
        help="tạo ảnh GIF có chữ từ clip Pixabay, không lồng tiếng, thay cho video",
    )
    parser.add_argument(
        "--high",
        action="store_true",
        help=f"AI dùng model mạnh hơn ({qc.high_model()}) cho cả loạt",
    )
    parser.add_argument(
        "--dang",
        dest="post",
        action="store_const",
        const=True,
        default=None,
        help="lên lịch đăng Facebook/TikTok/YouTube từng video vào các khung giờ trống",
    )
    parser.add_argument(
        "--khong-dang",
        dest="post",
        action="store_const",
        const=False,
        help="không đăng kể cả khi đang bật đăng tự động",
    )
    args = parser.parse_args()
    with qc.llm_model(args.high):
        return _run(args)


def _run(args) -> int:
    preset = cp.PRESETS_BY_COMMAND[args.preset]
    # Mặc định gửi cho quản trị viên, không phải người dùng được duyệt qua bot.
    chat_id = args.chat_id or next(iter(sorted(tg.ADMIN_USER_IDS)), None)
    if not chat_id:
        logger.error("Không có chat ID: truyền --chat-id hoặc cấu hình [telegram].allowed_user_ids")
        return 2
    if args.duration is None:
        args.duration = tg._get_user_duration(chat_id)
    if args.language is None:
        args.language = tg._get_user_language(chat_id)

    topics = _load_topics(args.topics)
    total = len(topics)
    # Loạt ảnh GIF lưu tiến độ riêng: cùng một danh sách có thể đã chạy xong bản video.
    suffix = ".gif" if args.gif else ""
    progress_path = args.topics + suffix + ".progress.json"
    stop_path = args.topics + ".stop"
    progress = _load_progress(progress_path)
    logger.add(args.topics + suffix + ".log", encoding="utf-8", level="INFO")
    if args.gif:
        return _run_gif_batch(preset, topics, progress, progress_path, stop_path, chat_id, args)

    seconds = args.duration or preset.default_seconds
    pending = [i for i in range(total) if progress.get(str(i + 1), {}).get("status") != "sent"]
    tg.bot.send_message(
        chat_id,
        f"Bắt đầu tạo hàng loạt: {total} video /{preset.command} ({preset.title}), "
        f"mỗi video khoảng {qc.format_duration(seconds)}, "
        f"ngôn ngữ: {qc.language_name(args.language)}.\n"
        f"Còn {len(pending)} video cần tạo. Video sẽ được gửi lần lượt khi hoàn thành.",
    )

    batch_started = time.monotonic()
    sent_count = total - len(pending)
    failed: list[int] = []
    for processed, index in enumerate(pending, start=1):
        if os.path.exists(stop_path):
            logger.info("found stop file, stopping batch")
            tg.bot.send_message(chat_id, f"Đã dừng theo yêu cầu. Đã gửi {sent_count}/{total} video.")
            os.remove(stop_path)
            return 0

        number = index + 1
        topic = topics[index]
        label = f"#{number}/{total}"
        status = tg.bot.send_message(chat_id, f"Đang tạo video {label}: {topic}")
        job = tg.Job(
            chat_id=chat_id,
            reply_to=None,
            preset=preset,
            prompt=topic,
            aspect=args.aspect,
            duration=args.duration,
            status_message_id=status.message_id,
            language=args.language,
        )

        started = time.monotonic()
        result, task_id, post, title = {}, "", None, topic
        for attempt in range(1, args.retries + 2):
            try:
                task_id, result, post, title = _run_one(preset, topic, args)
            except Exception as exc:
                logger.exception(f"{label} crashed: {exc}")
                result = {"state": const.TASK_STATE_FAILED, "error": f"{type(exc).__name__}: {exc}"}
            if result.get("state") != const.TASK_STATE_FAILED and result.get("videos"):
                break
            logger.warning(f"{label} attempt {attempt} failed: {result.get('error')}")

        if result.get("state") == const.TASK_STATE_FAILED or not result.get("videos"):
            failed.append(number)
            progress[str(number)] = {"status": "failed", "topic": topic, "error": result.get("error")}
            _save_progress(progress_path, progress)
            tg._edit_status(job, f"Video {label} lỗi, bỏ qua: {topic}\n{result.get('error', '')}"[:4000])
            continue

        video_path = result["videos"][0]
        script = (result.get("script") or "").strip()
        cover_path = qc.make_cover(preset, topic, video_path, result)
        send_error = ""
        try:
            tg._send_video(
                job,
                video_path,
                # Caption là nội dung đăng bài chuẩn SEO; dòng đầu chỉ để đánh số video.
                tg.post_caption(
                    post, script, f"[{number}/{total}]\n" if post else f"{label} – {topic}\n\n"
                ),
                float(result.get("audio_duration") or 0),
                cover_path,
            )
        except Exception as exc:
            logger.exception(f"{label} send failed: {exc}")
            send_error = str(exc)
        # Lưu cả khi gửi lỗi, rồi xoá thư mục task (âm thanh, phụ đề, clip trung gian).
        saved = qc.keep_video(video_path, title, script, cover_path)
        if saved:
            output_library.remove_task_dir(task_id)
        output = saved.paths[0] if saved else video_path
        note = qc.saved_note(saved, video_path)
        if saved:
            post_title, post_description, post_tags = qc.post_text(post, title)
            social_schedule.remember_post(output, post_title, post_description, post_tags)
            if qc.should_post(args.post):
                entry = social_schedule.schedule_created_video(
                    output, post_title, post_description, post_tags,
                    source="telegram", chat_id=chat_id,
                )
                note += "\n" + qc.schedule_note([entry] if entry else [])

        if send_error:
            failed.append(number)
            progress[str(number)] = {
                "status": "failed", "topic": topic, "task_id": task_id,
                "output": output, "error": f"send: {send_error}",
            }
            _save_progress(progress_path, progress)
            tg._edit_status(job, f"Video {label} tạo xong nhưng gửi lỗi: {send_error}\n{note}")
            continue

        sent_count += 1
        minutes = (time.monotonic() - started) / 60
        progress[str(number)] = {
            "status": "sent", "topic": topic, "task_id": task_id,
            "output": output, "minutes": round(minutes, 1),
        }
        _save_progress(progress_path, progress)

        elapsed = time.monotonic() - batch_started
        remaining = len(pending) - processed
        eta_hours = elapsed / processed * remaining / 3600
        tg._edit_status(
            job,
            f"Đã gửi {label} ({minutes:.1f} phút). Tổng: {sent_count}/{total}. "
            f"Còn lại khoảng {eta_hours:.1f} giờ.\n{note}",
        )

    summary = f"Hoàn tất hàng loạt /{preset.command}: đã gửi {sent_count}/{total} video."
    if failed:
        summary += (
            f"\nLỗi {len(failed)} video: {', '.join(map(str, failed))}. "
            "Chạy lại cùng lệnh để thử lại các video lỗi."
        )
    tg.bot.send_message(chat_id, summary)
    logger.info(summary)
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
