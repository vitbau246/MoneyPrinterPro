import os
import tempfile
import unittest
from unittest.mock import patch

from app.models.schema import VideoParams
from app.services import video as vd
from app.utils import file_security


class TestResolvePathWithinDirectory(unittest.TestCase):
    """路径白名单必须在访问文件系统之前拒绝越界路径。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base_dir = self._tmp.name
        os.makedirs(os.path.join(self.base_dir, "sub"))
        self.inner_file = os.path.join(self.base_dir, "sub", "a.ttf")
        with open(self.inner_file, "wb") as file:
            file.write(b"x")

    def tearDown(self):
        self._tmp.cleanup()

    def test_paths_inside_directory_are_resolved(self):
        for candidate in ("sub/a.ttf", self.inner_file):
            with self.subTest(candidate=candidate):
                resolved = file_security.resolve_path_within_directory(
                    self.base_dir, candidate
                )
                self.assertEqual(
                    os.path.normcase(resolved),
                    os.path.normcase(os.path.realpath(self.inner_file)),
                )

    def test_outside_paths_are_rejected_before_realpath(self):
        outside = [
            "../outside.ttf",
            "sub/../../outside.ttf",
            os.path.abspath(os.path.join(self.base_dir, "..", "outside.ttf")),
            r"\\attacker.example\share\x.ttf",
            "//attacker.example/share/x.ttf",
        ]
        real_realpath = os.path.realpath
        touched = []

        def tracking_realpath(path, *args, **kwargs):
            touched.append(path)
            return real_realpath(path, *args, **kwargs)

        for candidate in outside:
            with self.subTest(candidate=candidate):
                touched.clear()
                with patch.object(
                    file_security.os.path, "realpath", side_effect=tracking_realpath
                ):
                    with self.assertRaises(ValueError):
                        file_security.resolve_path_within_directory(
                            self.base_dir, candidate, require_file=False
                        )
                # 只允许解析基准目录本身，不能解析（打开）越界候选路径。
                self.assertTrue(
                    all(
                        os.path.normcase(path) == os.path.normcase(self.base_dir)
                        for path in touched
                    ),
                    touched,
                )


class TestFontNameConfinement(unittest.TestCase):
    def test_font_name_outside_font_dir_is_rejected(self):
        for font_name in (
            "../../config.toml",
            r"\\attacker.example\share\x.ttf",
            os.path.abspath(__file__),
        ):
            with self.subTest(font_name=font_name):
                params = VideoParams(video_subject="x", font_name=font_name)
                with self.assertRaisesRegex(ValueError, "invalid font_name"):
                    vd.generate_video(
                        video_path="video.mp4",
                        audio_path="audio.mp3",
                        subtitle_path="",
                        output_file=os.path.join(tempfile.gettempdir(), "out.mp4"),
                        params=params,
                    )


if __name__ == "__main__":
    unittest.main()
