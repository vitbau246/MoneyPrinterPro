import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, ImageSequence

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.services import gif_maker
from app.utils import utils

SIZE = (480, 854)
BLOCK = (300, 120)


def _plain(value: int) -> list[np.ndarray]:
    width, height = SIZE
    return [np.full((height, width, 3), value, dtype=np.uint8)]


def _striped(rows: int) -> np.ndarray:
    """Sọc trắng đen xen kẽ ở ``rows`` hàng trên cùng, phần dưới đen đều."""
    width, height = SIZE
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:rows, ::2] = 255
    return frame


class TestTextStyle(unittest.TestCase):
    def test_bright_background_gets_dark_text(self):
        style = gif_maker.choose_style(_plain(240), SIZE, BLOCK)

        self.assertEqual(style.fill, gif_maker.INK)
        self.assertEqual(style.stroke, gif_maker.WHITE)
        self.assertEqual(style.backdrop_alpha, 0)
        self.assertGreaterEqual(style.contrast, gif_maker.MIN_CONTRAST)

    def test_dark_background_gets_white_text_away_from_the_centered_subject(self):
        style = gif_maker.choose_style(_plain(20), SIZE, BLOCK)

        self.assertEqual(style.fill, gif_maker.WHITE)
        self.assertEqual(style.backdrop_alpha, 0)
        # Các vùng đọc rõ như nhau: chữ lên trên, chừa chỗ cho chủ thể ở giữa khung.
        self.assertAlmostEqual(style.center_y, round(SIZE[1] * 0.27), delta=20)

    def test_busy_background_everywhere_gets_backdrop(self):
        style = gif_maker.choose_style([_striped(SIZE[1])], SIZE, BLOCK)

        self.assertLess(style.contrast, gif_maker.MIN_CONTRAST)
        self.assertGreater(style.backdrop_alpha, 0)

    def test_text_moves_to_the_calm_part_of_the_frame(self):
        busy_rows = SIZE[1] * 2 // 3
        style = gif_maker.choose_style([_striped(busy_rows)], SIZE, BLOCK)

        self.assertGreater(style.center_y, busy_rows)
        self.assertEqual(style.fill, gif_maker.WHITE)
        self.assertEqual(style.backdrop_alpha, 0)


class TestFitText(unittest.TestCase):
    def test_long_vietnamese_text_fits_inside_frame(self):
        text = (
            "Kiên trì không phải là chưa từng gục ngã, mà là lần nào cũng đứng dậy "
            "và bước tiếp thêm một bước nữa."
        )
        font, lines, line_height = gif_maker.fit_text(text, SIZE)
        draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))

        self.assertEqual(" ".join(lines), text)
        self.assertLessEqual(len(lines), 5)
        self.assertTrue(all(draw.textlength(line, font=font) <= SIZE[0] * 0.86 + 1 for line in lines))
        self.assertLessEqual(line_height * len(lines), SIZE[1] * 0.42)


class TestFindClip(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        config.app["pixabay_api_keys"] = ["pixabay-key"]
        self._clear_used_clips()

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        self._clear_used_clips()

    @staticmethod
    def _clear_used_clips():
        try:
            os.remove(gif_maker._used_clips_path())
        except OSError:
            pass

    @staticmethod
    def _hit(clip_id, tags, page=None):
        return {
            "id": clip_id, "tags": tags, "duration": 10, "pageURL": page or f"page-{clip_id}",
            "videos": {"large": {"url": f"{clip_id}.mp4", "width": 1080, "height": 1920}},
        }

    def test_used_clips_lose_to_unused_and_are_reused_only_as_last_resort(self):
        """Lỗi thật: loạt GIF từng dùng cùng một clip cho mọi ảnh."""
        results = {
            "calm lake": [self._hit(1, "calm lake, water"), self._hit(2, "lake, calm, forest")],
            gif_maker.FALLBACK_TERM: [],
        }

        def fake_get(url, params, **kwargs):
            return SimpleNamespace(status_code=200, json=lambda: {"hits": results[params["q"]]})

        with patch("app.services.gif_maker.requests.get", side_effect=fake_get):
            first = gif_maker.find_clip(["calm lake"], "9:16", avoid=set())
            second = gif_maker.find_clip(["calm lake"], "9:16", avoid={"1"})
            reused = gif_maker.find_clip(["calm lake"], "9:16", avoid={"1", "2"})

        self.assertEqual((first.clip_id, second.clip_id), ("1", "2"))
        # Hết clip chưa dùng (kể cả nhóm dự phòng) thì mới dùng lại clip hợp nhất.
        self.assertEqual(reused.clip_id, "1")

    def test_fallback_term_is_tried_before_reusing_a_clip(self):
        results = {
            "calm lake": [self._hit(1, "calm lake, water")],
            gif_maker.FALLBACK_TERM: [self._hit(9, "nature, forest, river")],
        }

        def fake_get(url, params, **kwargs):
            return SimpleNamespace(status_code=200, json=lambda: {"hits": results[params["q"]]})

        with patch("app.services.gif_maker.requests.get", side_effect=fake_get):
            clip = gif_maker.find_clip(["calm lake"], "9:16", avoid={"1"})

        self.assertEqual(clip.clip_id, "9")

    def test_used_clip_history_keeps_recent_unique_ids(self):
        with patch.object(gif_maker, "USED_CLIPS_LIMIT", 3):
            for clip_id in ("1", "2", "3", "2", "4"):
                gif_maker.remember_clip(clip_id)

        self.assertEqual(gif_maker.used_clip_ids(), ["3", "2", "4"])

    def test_create_text_gif_remembers_the_clip_it_used(self):
        clip = gif_maker.Clip("u", "page", 480, 854, 10, "calm lake", clip_id="77")
        rendered = gif_maker.Rendered(
            gif_maker.TextStyle(gif_maker.WHITE, gif_maker.INK, 231, 4.0), 480, 854, 4.0, None
        )
        with (
            patch.object(gif_maker, "find_clip", return_value=clip),
            patch.object(gif_maker, "_download"),
            patch.object(gif_maker, "make_gif", return_value=rendered),
            tempfile.TemporaryDirectory() as output_dir,
        ):
            gif_maker.create_text_gif("Chữ", ["calm lake"], "9:16", output_dir)

        self.assertIn("77", gif_maker.used_clip_ids())

    def test_pick_smallest_rendition_that_still_covers_the_frame(self):
        videos = {
            "large": {"url": "L", "width": 3840, "height": 2160},
            "medium": {"url": "M", "width": 1920, "height": 1080},
            "small": {"url": "S", "width": 1280, "height": 720},
            "tiny": {"url": "T", "width": 960, "height": 540},
        }

        self.assertEqual(gif_maker.pick_rendition(videos, 480, 854)[0], "M")
        self.assertEqual(gif_maker.pick_rendition(videos, 640, 360)[0], "T")
        self.assertIsNone(gif_maker.pick_rendition({"tiny": {"url": "", "width": 0}}, 480, 854))

    def test_prefers_full_tag_match_then_orientation(self):
        def hit(page, tags, width, height):
            return {
                "tags": tags, "duration": 10, "pageURL": page,
                "videos": {"large": {"url": f"{page}.mp4", "width": width, "height": height}},
            }

        hits = [
            hit("forest", "nature, forest", 1080, 1920),
            hit("lake-wide", "calm lake, water", 1920, 1080),
            hit("lake-tall", "lake, calm, mountain", 1080, 1920),
        ]
        response = SimpleNamespace(status_code=200, json=lambda: {"hits": hits})
        with patch("app.services.gif_maker.requests.get", return_value=response) as get:
            clip = gif_maker.find_clip(["calm lake"], "9:16")

        self.assertEqual(clip.page_url, "lake-tall")
        self.assertEqual(clip.term, "calm lake")
        self.assertEqual(get.call_args.kwargs["params"]["safesearch"], "true")

    def test_generic_words_and_homonyms_lose_to_clip_matching_all_terms(self):
        """Lỗi thật: "octopus closeup" từng chọn clip tinh thể thạch anh "closeup"."""
        def hit(page, tags):
            return {
                "tags": tags, "duration": 10, "pageURL": page,
                "videos": {"large": {"url": f"{page}.mp4", "width": 1920, "height": 1080}},
            }

        results = {
            "octopus closeup": [
                hit("amethyst", "amethyst, crystal, purple, closeup, mineral"),
                hit("carousel", "fair, folk festival, octopus, carousel, ride"),
            ],
            "octopus swimming": [
                hit("octopus", "octopus, creature, tentacles, underwater, ocean, swimming"),
            ],
        }

        def fake_get(url, params, **kwargs):
            return SimpleNamespace(status_code=200, json=lambda: {"hits": results[params["q"]]})

        with patch("app.services.gif_maker.requests.get", side_effect=fake_get):
            clip = gif_maker.find_clip(["octopus closeup", "octopus swimming"], "9:16")

        self.assertEqual(clip.page_url, "octopus")

    def test_no_result_tries_fallback_then_raises(self):
        response = SimpleNamespace(status_code=200, json=lambda: {"hits": []})
        with patch("app.services.gif_maker.requests.get", return_value=response) as get:
            with self.assertRaises(gif_maker.GifError):
                gif_maker.find_clip(["calm lake", "rain window"], "9:16")

        searched = [call.kwargs["params"]["q"] for call in get.call_args_list]
        self.assertEqual(searched, ["calm lake", "rain window", gif_maker.FALLBACK_TERM])


class TestMakeGif(unittest.TestCase):
    def test_makes_looping_portrait_gif_from_landscape_clip(self):
        ffmpeg = utils.get_ffmpeg_binary()
        if not shutil.which(ffmpeg) and not os.path.exists(ffmpeg):
            self.skipTest("ffmpeg not available")
        temp_dir = tempfile.mkdtemp()
        try:
            source = os.path.join(temp_dir, "source.mp4")
            subprocess.run(
                [ffmpeg, "-hide_banner", "-y", "-f", "lavfi",
                 "-i", "testsrc2=size=640x360:rate=25:duration=3",
                 "-pix_fmt", "yuv420p", source],
                capture_output=True, check=True,
            )
            output = os.path.join(temp_dir, "out.gif")
            rendered = gif_maker.make_gif(
                source, "Mỗi ngày tiến bộ một chút là đủ.", output, "9:16"
            )

            with open(output, "rb") as file:
                self.assertEqual(file.read(4), b"GIF8")
            with Image.open(output) as image:
                self.assertEqual(image.size, gif_maker.OUTPUT_SIZES["9:16"])
                frames = sum(1 for _ in ImageSequence.Iterator(image))
            self.assertGreaterEqual(frames, 20)
            self.assertLessEqual(os.path.getsize(output), gif_maker.MAX_GIF_BYTES)
            self.assertEqual((rendered.width, rendered.height), gif_maker.OUTPUT_SIZES["9:16"])
            self.assertAlmostEqual(rendered.seconds, 3.0, delta=0.2)
            self.assertIn(rendered.style.fill, (gif_maker.WHITE, gif_maker.INK))
            self.assertTrue(rendered.preview_path.endswith(".mp4"))
            self.assertGreater(os.path.getsize(rendered.preview_path), 0)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_clip_with_reserved_color_tags_still_renders(self):
        """Lỗi thật 07/10/2026: clip gắn màu "reserved" làm PNG/GIF báo -129, không ra khung nào."""
        ffmpeg = utils.get_ffmpeg_binary()
        if not shutil.which(ffmpeg) and not os.path.exists(ffmpeg):
            self.skipTest("ffmpeg not available")
        temp_dir = tempfile.mkdtemp()
        try:
            source = os.path.join(temp_dir, "reserved.mp4")
            subprocess.run(
                [ffmpeg, "-hide_banner", "-y", "-f", "lavfi",
                 "-i", "testsrc2=size=640x360:rate=25:duration=2",
                 "-pix_fmt", "yuv420p", "-c:v", "libx264",
                 "-color_primaries", "3", "-color_trc", "3", source],
                capture_output=True, check=True,
            )
            output = os.path.join(temp_dir, "out.gif")
            rendered = gif_maker.make_gif(source, "Màu lạ vẫn dựng được.", output, "1:1")

            with Image.open(output) as image:
                frames = sum(1 for _ in ImageSequence.Iterator(image))
            self.assertGreaterEqual(frames, 10)
            self.assertIsNotNone(rendered.preview_path)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_file_name_is_ascii_slug(self):
        name = gif_maker._file_name("Đừng bỏ cuộc: mỗi ngày một bước!")

        self.assertRegex(name, r"^dung-bo-cuoc-moi-ngay-mot-buoc-[0-9a-f]{6}\.gif$")


if __name__ == "__main__":
    unittest.main()
