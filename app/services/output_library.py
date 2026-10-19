"""
Thư mục thành phẩm: mỗi video hoặc ảnh GIF đã tạo chỉ giữ file cuối cùng, ảnh bìa và
lời diễn giải (.txt), đặt chung một thư mục theo loại (không chia thư mục riêng từng
mục), tên file là số thứ tự kèm tiêu đề:

    storage/output/video/#012 Tiêu đề video.mp4 | .jpg (ảnh bìa) | .txt (lời thoại)
    storage/output/gif/#007 Chữ trên ảnh.gif | .mp4 (bản xem trước) | .txt (lời diễn giải)

Số thứ tự tăng dần theo thứ tự tạo, video và ảnh GIF đánh số riêng.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import tempfile
import time
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, Mapping, Sequence

from loguru import logger

from app.utils import utils

VIDEO = "video"
GIF = "gif"
# Đủ 3 chữ số để trình xem file không sắp theo số vẫn xếp đúng thứ tự.
INDEX_DIGITS = 3
# Đường dẫn Windows tối đa 260 ký tự; thư mục thành phẩm đã chiếm khoảng 90.
TITLE_LENGTH = 120
_INDEX_RE = re.compile(r"^#(\d+) ")
# Ký tự Windows không cho dùng trong tên file.
_REPLACEMENTS = {":": " -", "/": "-", "\\": "-", "|": "-"}
_FORBIDDEN_RE = re.compile(r'[<>"?*\x00-\x1f]')
# Bot và script hàng loạt có thể lưu cùng lúc: khoá để không trùng số thứ tự.
LOCK_TIMEOUT_SECONDS = 60
STALE_LOCK_SECONDS = 300
IMPORTED_FILE = "imported.json"


@dataclass
class SavedItem:
    index: int
    # "#012 Tiêu đề", không có đuôi file.
    name: str
    paths: list[str] = field(default_factory=list)


def output_dir(kind: str) -> str:
    return utils.storage_dir(os.path.join("output", kind), create=True)


def file_title(title: str, limit: int = TITLE_LENGTH) -> str:
    """Tiêu đề dùng được làm tên file Windows, giữ nguyên dấu tiếng Việt."""
    text = unicodedata.normalize("NFC", " ".join(str(title or "").split()))
    for old, new in _REPLACEMENTS.items():
        text = text.replace(old, new)
    text = " ".join(_FORBIDDEN_RE.sub("", text).split())
    if len(text) > limit:
        cut = text[: limit + 1]
        text = cut.rsplit(" ", 1)[0] if " " in cut else text[:limit]
    return text.rstrip(" .,;-") or "Không tiêu đề"


def next_index(kind: str) -> int:
    indexes = [
        int(match[1]) for name in os.listdir(output_dir(kind)) if (match := _INDEX_RE.match(name))
    ]
    return max(indexes, default=0) + 1


@contextmanager
def _locked(kind: str) -> Iterator[None]:
    path = os.path.join(utils.storage_dir("temp", create=True), f"output-{kind}.lock")
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                # Tiến trình giữ khoá bị tắt ngang thì khoá cũ không bao giờ được xoá.
                if time.time() - os.path.getmtime(path) > STALE_LOCK_SECONDS:
                    os.remove(path)
                    continue
            except OSError:
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(f"output library is locked: {path}")
            time.sleep(0.1)
    try:
        yield
    finally:
        os.close(handle)
        try:
            os.remove(path)
        except OSError:
            pass


def save(
    kind: str, title: str, sources: Sequence[str | None], text: str, copy: bool = False
) -> SavedItem:
    """
    Đưa ``sources`` vào thư mục thành phẩm với số thứ tự kế tiếp, giữ đuôi file gốc,
    và ghi ``text`` ra file .txt cùng tên.

    File đầu tiên là thành phẩm chính, bắt buộc phải có; các file sau thiếu thì bỏ qua.
    Mặc định chuyển file (nguồn mất đi); ``copy`` thì chép và giữ nguồn.
    """
    if not sources or not sources[0] or not os.path.isfile(sources[0]):
        raise FileNotFoundError(f"missing output file: {sources[0] if sources else None}")
    folder = output_dir(kind)
    with _locked(kind):
        index = next_index(kind)
        name = f"#{index:0{INDEX_DIGITS}d} {file_title(title)}"
        paths = []
        for source in sources:
            if not source or not os.path.isfile(source):
                continue
            target = os.path.join(folder, name + os.path.splitext(source)[1].lower())
            if copy:
                shutil.copy2(source, target)
            else:
                shutil.move(source, target)
            paths.append(target)
        text_path = os.path.join(folder, f"{name}.txt")
        with open(text_path, "w", encoding="utf-8") as file:
            file.write(f"{(text or title).strip()}\n")
        paths.append(text_path)
    logger.info(f"saved {kind} to output library: {name}")
    return SavedItem(index, name, paths)


def save_video(
    video_path: str, title: str, script: str, cover_path: str | None = None
) -> SavedItem:
    """Giữ video cuối, ảnh bìa và lời thoại. Thư mục task xoá riêng bằng remove_task_dir."""
    return save(VIDEO, title, [video_path, cover_path], script)


def save_gif(gif_path: str, preview_path: str | None, title: str, detail: str) -> SavedItem:
    """Giữ ảnh GIF, bản MP4 xem trước và lời diễn giải; tiêu đề là chữ trên ảnh."""
    return save(GIF, title, [gif_path, preview_path], detail)


def remove_task_dir(task_id: str) -> None:
    """Xoá storage/tasks/<task_id> (âm thanh, phụ đề, clip trung gian...) sau khi đã lưu."""
    root = os.path.realpath(utils.task_dir())
    path = os.path.realpath(os.path.join(root, task_id or ""))
    # Chỉ xoá đúng một thư mục con của storage/tasks, không bao giờ xoá thư mục khác.
    if os.path.dirname(path) == root and os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


# ------------------------------------------- chép thành phẩm tạo trước đây


@dataclass
class Existing:
    """Thành phẩm cũ còn nằm trong storage/tasks hoặc storage/gifs."""

    kind: str
    # Khoá trong imported.json: đường dẫn file chính tính từ thư mục storage.
    key: str
    created: float
    title: str
    text: str
    # File chính đứng đầu.
    sources: list[str]
    # Video chưa có ảnh bìa: tạo ảnh bìa mới khi chép.
    needs_cover: bool = False


def _storage_key(path: str) -> str:
    return os.path.relpath(path, utils.storage_dir()).replace(os.sep, "/")


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as file:
            return json.load(file)
    except (OSError, ValueError):
        return None


def existing_videos() -> list[Existing]:
    items = []
    root = utils.task_dir()
    for task_id in os.listdir(root):
        folder = os.path.join(root, task_id)
        finals = sorted(
            path
            for path in glob.glob(os.path.join(folder, "final-*.mp4"))
            if re.fullmatch(r"final-\d+\.mp4", os.path.basename(path))
        )
        if not finals:
            continue
        manifest = _read_json(os.path.join(folder, "script.json"))
        manifest = manifest if isinstance(manifest, dict) else {}
        params = manifest.get("params") if isinstance(manifest.get("params"), dict) else {}
        subject = str(params.get("video_subject") or "").strip().splitlines()
        title = str(params.get("cover_title") or "").strip() or (subject[0] if subject else task_id)
        # script.json được ghi lúc bắt đầu task, giữ đúng thứ tự tạo kể cả khi video
        # được sửa sau (ví dụ ghép ảnh bìa).
        files = [os.path.join(folder, name) for name in os.listdir(folder)]
        created = min(os.path.getmtime(path) for path in files)
        if os.path.exists(os.path.join(folder, "script.json")):
            created = os.path.getmtime(os.path.join(folder, "script.json"))
        for path in finals:
            number = re.search(r"final-(\d+)", os.path.basename(path))[1]
            cover = next(
                (
                    os.path.join(folder, name)
                    for name in (f"cover-{number}.jpg", "cover.jpg")
                    if os.path.exists(os.path.join(folder, name))
                ),
                None,
            )
            items.append(
                Existing(
                    VIDEO, _storage_key(path), created, title,
                    str(manifest.get("script") or ""), [path] + ([cover] if cover else []),
                    needs_cover=cover is None,
                )
            )
    return items


def _title_from_slug(file_name: str) -> str:
    stem = re.sub(r"-[0-9a-f]{6}$", "", os.path.splitext(file_name)[0])
    words = stem.replace("-", " ").strip()
    return words[:1].upper() + words[1:]


def existing_gifs(titles: Mapping[str, str] | None = None) -> list[Existing]:
    """
    Ảnh GIF trong storage/gifs. Tên file cũ chỉ là chữ không dấu bị cắt ngắn, nên
    ``titles`` ({tên file .gif: chữ trên ảnh}) cho tiêu đề đúng; thiếu thì lấy từ tên file.
    """
    items = []
    folder = utils.storage_dir("gifs", create=True)
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        # File rỗng là lần ffmpeg lỗi giữa chừng, không có ảnh.
        if not name.endswith(".gif") or os.path.getsize(path) == 0:
            continue
        title = str((titles or {}).get(name) or "").strip() or _title_from_slug(name)
        preview = os.path.splitext(path)[0] + ".mp4"
        items.append(
            Existing(
                GIF, _storage_key(path), os.path.getmtime(path), title, title,
                [path] + ([preview] if os.path.exists(preview) else []),
            )
        )
    return items


def _imported_path() -> str:
    return os.path.join(utils.storage_dir("output", create=True), IMPORTED_FILE)


def _save_imported(keys: set[str]) -> None:
    path = _imported_path()
    with open(path + ".tmp", "w", encoding="utf-8") as file:
        json.dump(sorted(keys), file, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)


def _copy_existing(item: Existing) -> SavedItem:
    if not item.needs_cover:
        return save(item.kind, item.title, item.sources, item.text, copy=True)
    from app.services import cover as cover_service

    temp_dir = tempfile.mkdtemp(dir=utils.storage_dir("temp", create=True))
    try:
        video = item.sources[0]
        subtitle = os.path.join(os.path.dirname(video), "subtitle.srt")
        cover = cover_service.create_cover(
            video, item.title, os.path.join(temp_dir, "cover.jpg"),
            subtitle_path=subtitle if os.path.exists(subtitle) else None,
        )
        return save(item.kind, item.title, [video, cover], item.text, copy=True)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def import_existing(
    gif_titles: Mapping[str, str] | None = None, dry_run: bool = False
) -> list[tuple[Existing, SavedItem]]:
    """
    Chép thành phẩm tạo trước đây vào thư mục thành phẩm, đánh số theo thời gian tạo.
    Chỉ chép, không xoá file gốc; mục đã chép ghi vào imported.json nên chạy lại chỉ
    chép mục mới. ``dry_run`` chỉ trả về tên dự kiến.
    """
    done = set(_read_json(_imported_path()) or [])
    results = []
    for kind, items in ((VIDEO, existing_videos()), (GIF, existing_gifs(gif_titles))):
        pending = sorted(
            (item for item in items if item.key not in done), key=lambda item: item.created
        )
        first = next_index(kind)
        for offset, item in enumerate(pending):
            if dry_run:
                index = first + offset
                name = f"#{index:0{INDEX_DIGITS}d} {file_title(item.title)}"
                results.append((item, SavedItem(index, name)))
                continue
            results.append((item, _copy_existing(item)))
            done.add(item.key)
            _save_imported(done)
    return results
