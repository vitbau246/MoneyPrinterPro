"""
Ghép cover vào đầu các video đã tạo bởi telegram_batch.py (và xoá khung đen).

    python add_covers.py --progress storage/batch/dongluc_101.txt.progress.json --label "Động lực"

Bản gốc được giữ thành final-N.orig.mp4; video đã có bản .orig bị bỏ qua nên
chạy lại an toàn. Video mới tạo từ bot/batch đã tự có cover, không cần script này.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

from loguru import logger

from app.services import cover


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--progress", required=True)
    parser.add_argument("--label", default="")
    parser.add_argument("--seconds", type=float, default=1.0)
    args = parser.parse_args()

    with open(args.progress, encoding="utf-8") as file:
        progress = json.load(file)

    done = skipped = failed = 0
    for number, item in sorted(progress.items(), key=lambda pair: int(pair[0])):
        video_path = item.get("video")
        if item.get("status") != "sent" or not video_path or not os.path.exists(video_path):
            continue
        original_path = os.path.splitext(video_path)[0] + ".orig.mp4"
        if os.path.exists(original_path):
            skipped += 1
            continue

        task_dir = os.path.dirname(video_path)
        cover_path = next(
            (
                os.path.join(task_dir, name)
                for name in ("cover-1.jpg", "cover.jpg")
                if os.path.exists(os.path.join(task_dir, name))
            ),
            None,
        )
        if cover_path is None:
            subtitle_path = os.path.join(task_dir, "subtitle.srt")
            cover_path = cover.create_cover(
                video_path,
                item.get("topic", ""),
                os.path.join(task_dir, "cover.jpg"),
                label=args.label,
                subtitle_path=subtitle_path if os.path.exists(subtitle_path) else None,
            )
        if not cover_path:
            failed += 1
            logger.error(f"#{number}: cannot create cover")
            continue

        shutil.copy2(video_path, original_path)
        if cover.prepend_cover(video_path, cover_path, args.seconds):
            done += 1
            logger.info(f"#{number}: cover added ({done} done)")
        else:
            # Khôi phục bản gốc, xoá .orig để lần chạy sau thử lại.
            shutil.copy2(original_path, video_path)
            os.remove(original_path)
            failed += 1
            logger.error(f"#{number}: failed to add cover")

    logger.info(f"finished: added={done}, already_done={skipped}, failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
