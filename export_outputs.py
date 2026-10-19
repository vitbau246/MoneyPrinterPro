"""
Chép video và ảnh GIF đã tạo trước đây vào thư mục thành phẩm, đánh số theo thời gian
tạo: storage/output/video (video cuối + ảnh bìa + lời thoại) và storage/output/gif
(ảnh GIF + bản MP4 + lời diễn giải). Video/GIF mới tạo từ bot và telegram_batch.py đã
tự vào đây, script này chỉ dành cho thành phẩm cũ.

    python export_outputs.py --dry-run          # xem tên sẽ đặt, chưa chép
    python export_outputs.py --gif-titles gif_titles.json

Chỉ chép, không xoá file gốc. Mục đã chép ghi vào storage/output/imported.json nên
chạy lại chỉ chép mục mới. Không chạy khi đang có loạt video/GIF tạo dở.

--gif-titles: JSON {tên file .gif: chữ trên ảnh}. Ảnh GIF cũ không lưu lại chữ, tên
file chỉ là chữ không dấu bị cắt ngắn; thiếu thì tiêu đề lấy từ tên file.
"""

from __future__ import annotations

import argparse
import json
import sys

from loguru import logger

from app.services import output_library


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gif-titles", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    titles = {}
    if args.gif_titles:
        with open(args.gif_titles, encoding="utf-8") as file:
            titles = json.load(file)

    results = output_library.import_existing(titles, dry_run=args.dry_run)
    for item, saved in results:
        logger.info(f"{item.kind}: {saved.name}  <-  {item.key}")
    videos = sum(item.kind == output_library.VIDEO for item, _ in results)
    verb = "would copy" if args.dry_run else "copied"
    logger.info(f"{verb} {videos} videos, {len(results) - videos} gifs")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
