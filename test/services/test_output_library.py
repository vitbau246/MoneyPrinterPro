import json
import os
import sys
import tempfile
import time
import unicodedata
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import cover as cover_service
from app.services import output_library as library
from app.utils import utils


def _write(path: str, content: str = "x", mtime: float | None = None) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        file.write(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


class LibraryTestCase(unittest.TestCase):
    def setUp(self):
        # Mỗi test một thư mục storage riêng để số thứ tự không phụ thuộc test khác.
        self._temp = tempfile.TemporaryDirectory()
        self.storage = os.path.join(self._temp.name, "storage")
        patcher = patch.dict(os.environ, {"MPT_STORAGE_DIR": self.storage})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._temp.cleanup)

    def names(self, kind: str) -> list[str]:
        return sorted(os.listdir(library.output_dir(kind)))


class TestFileTitle(LibraryTestCase):
    def test_windows_forbidden_characters_are_replaced_and_accents_kept(self):
        self.assertEqual(
            library.file_title(' Bà Nà Hills:  "Cầu Vàng" có gì? 24/7 <vui>\n'),
            "Bà Nà Hills - Cầu Vàng có gì 24-7 vui",
        )

    def test_decomposed_text_is_normalized_and_long_title_cut_at_word(self):
        title = library.file_title(unicodedata.normalize("NFD", "Tiết kiệm " * 20), limit=30)

        self.assertEqual(title, "Tiết kiệm Tiết kiệm Tiết kiệm")
        self.assertTrue(unicodedata.is_normalized("NFC", title))

    def test_empty_title_has_placeholder(self):
        self.assertEqual(library.file_title(" ?* "), "Không tiêu đề")


class TestSave(LibraryTestCase):
    def test_files_move_out_with_next_index_title_and_text(self):
        source = os.path.join(self.storage, "work")
        video = _write(os.path.join(source, "final-1.mp4"), "video")
        cover = _write(os.path.join(source, "cover-1.JPG"), "cover")
        _write(os.path.join(library.output_dir(library.VIDEO), "#005 Cũ.mp4"))

        saved = library.save_video(video, "Kiên trì: mỗi ngày", "Lời thoại\n", cover)

        self.assertEqual(saved.index, 6)
        self.assertEqual(saved.name, "#006 Kiên trì - mỗi ngày")
        self.assertEqual(
            self.names(library.VIDEO),
            ["#005 Cũ.mp4", "#006 Kiên trì - mỗi ngày.jpg", "#006 Kiên trì - mỗi ngày.mp4",
             "#006 Kiên trì - mỗi ngày.txt"],
        )
        self.assertFalse(os.path.exists(video) or os.path.exists(cover))
        with open(saved.paths[-1], encoding="utf-8") as file:
            self.assertEqual(file.read(), "Lời thoại\n")

    def test_gif_without_preview_or_detail_keeps_title_as_text(self):
        gif = _write(os.path.join(self.storage, "gifs", "a.gif"))

        first = library.save_gif(gif, None, "Chữ trên ảnh", "")
        second = library.save_gif(
            _write(os.path.join(self.storage, "gifs", "b.gif")),
            _write(os.path.join(self.storage, "gifs", "b.mp4")),
            "Ảnh hai",
            "Diễn giải",
        )

        self.assertEqual((first.index, second.index), (1, 2))
        self.assertEqual(
            self.names(library.GIF),
            ["#001 Chữ trên ảnh.gif", "#001 Chữ trên ảnh.txt",
             "#002 Ảnh hai.gif", "#002 Ảnh hai.mp4", "#002 Ảnh hai.txt"],
        )
        with open(first.paths[-1], encoding="utf-8") as file:
            self.assertEqual(file.read(), "Chữ trên ảnh\n")

    def test_missing_main_file_raises_and_copy_keeps_source(self):
        with self.assertRaises(FileNotFoundError):
            library.save(library.VIDEO, "x", [os.path.join(self.storage, "none.mp4")], "")
        source = _write(os.path.join(self.storage, "keep.mp4"))

        library.save(library.VIDEO, "Giữ", [source], "", copy=True)

        self.assertTrue(os.path.exists(source))
        self.assertIn("#001 Giữ.mp4", self.names(library.VIDEO))

    def test_stale_lock_from_a_killed_process_is_taken_over(self):
        lock = _write(os.path.join(self.storage, "temp", "output-gif.lock"), mtime=time.time() - 3600)

        library.save(library.GIF, "Ảnh", [_write(os.path.join(self.storage, "a.gif"))], "")

        self.assertFalse(os.path.exists(lock))

    def test_remove_task_dir_only_deletes_one_task_folder(self):
        task = _write(os.path.join(utils.task_dir(), "abc", "audio.mp3"))
        other = _write(os.path.join(self.storage, "keep.txt"))

        for task_id in ("", "..", "../..", os.path.join("abc", "..")):
            library.remove_task_dir(task_id)
        self.assertTrue(os.path.exists(task) and os.path.exists(other))

        library.remove_task_dir("abc")
        self.assertFalse(os.path.exists(os.path.dirname(task)))
        self.assertTrue(os.path.isdir(utils.task_dir()))


class TestImportExisting(LibraryTestCase):
    def setUp(self):
        super().setUp()
        tasks, gifs = utils.task_dir(), utils.storage_dir("gifs", create=True)
        now = time.time()
        # Task mới hơn: có tiêu đề ảnh bìa từ nội dung đăng bài.
        new = os.path.join(tasks, "new")
        _write(os.path.join(new, "script.json"), json.dumps({
            "script": "Lời thoại mới", "params": {"cover_title": "Tiêu đề: mới", "video_subject": "x"},
        }), mtime=now - 100)
        for name in ("final-1.mp4", "final-1.orig.mp4", "final-1-telegram.mp4", "cover-1.jpg"):
            _write(os.path.join(new, name), mtime=now)
        # Task cũ hơn (ảnh bìa ghép sau nên video có mtime mới): tiêu đề là chủ đề.
        old = os.path.join(tasks, "old")
        _write(os.path.join(old, "script.json"), json.dumps({
            "script": "Lời thoại cũ", "params": {"video_subject": "Chủ đề cũ\ndòng hai"},
        }), mtime=now - 500)
        _write(os.path.join(old, "final-1.mp4"), mtime=now + 50)
        _write(os.path.join(old, "cover.jpg"))
        # Task lỗi, không có video.
        _write(os.path.join(tasks, "failed", "script.json"), "{}")
        # Video thử nghiệm chưa có ảnh bìa và script.json.
        _write(os.path.join(tasks, "test", "final-1.mp4"), mtime=now - 900)

        _write(os.path.join(gifs, "kien-tri-moi-ngay-a1b2c3.gif"), mtime=now - 20)
        _write(os.path.join(gifs, "kien-tri-moi-ngay-a1b2c3.mp4"))
        _write(os.path.join(gifs, "dung-bo-cuoc-d4e5f6.gif"), mtime=now - 10)
        _write(os.path.join(gifs, "loi-ffmpeg-000000.gif"), "")
        _write(os.path.join(gifs, "used_clips.json"), "[]")
        self.titles = {"kien-tri-moi-ngay-a1b2c3.gif": "Kiên trì mỗi ngày."}

    def fake_cover(self, video, title, output_path, **kwargs):
        return _write(output_path, "cover")

    def test_dry_run_lists_names_in_creation_order_without_copying(self):
        results = library.import_existing(self.titles, dry_run=True)

        self.assertEqual(
            [saved.name for _, saved in results],
            ["#001 test", "#002 Chủ đề cũ", "#003 Tiêu đề - mới",
             "#001 Kiên trì mỗi ngày", "#002 Dung bo cuoc"],
        )
        self.assertEqual(self.names(library.VIDEO), [])

    def test_copies_video_cover_script_and_gif_once(self):
        with patch.object(cover_service, "create_cover", side_effect=self.fake_cover) as create:
            first = library.import_existing(self.titles)
            again = library.import_existing(self.titles)

        self.assertEqual(len(first), 5)
        self.assertEqual(again, [])
        create.assert_called_once()
        self.assertEqual(
            self.names(library.VIDEO),
            ["#001 test.jpg", "#001 test.mp4", "#001 test.txt",
             "#002 Chủ đề cũ.jpg", "#002 Chủ đề cũ.mp4", "#002 Chủ đề cũ.txt",
             "#003 Tiêu đề - mới.jpg", "#003 Tiêu đề - mới.mp4", "#003 Tiêu đề - mới.txt"],
        )
        self.assertEqual(
            self.names(library.GIF),
            ["#001 Kiên trì mỗi ngày.gif", "#001 Kiên trì mỗi ngày.mp4",
             "#001 Kiên trì mỗi ngày.txt", "#002 Dung bo cuoc.gif", "#002 Dung bo cuoc.txt"],
        )
        folder = library.output_dir(library.VIDEO)
        with open(os.path.join(folder, "#003 Tiêu đề - mới.txt"), encoding="utf-8") as file:
            self.assertEqual(file.read(), "Lời thoại mới\n")
        # Chỉ chép: file gốc vẫn còn.
        self.assertTrue(os.path.exists(os.path.join(utils.task_dir(), "new", "final-1.mp4")))
        self.assertTrue(os.path.exists(os.path.join(utils.storage_dir("gifs"), "dung-bo-cuoc-d4e5f6.gif")))


if __name__ == "__main__":
    unittest.main()
