import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models import schema
from app.models.schema import SubtitleRequest, VideoAspect, VideoFitMode, VideoParams


class TestVideoAspect(unittest.TestCase):
    def test_to_resolution_known_aspects(self):
        self.assertEqual(VideoAspect.landscape.to_resolution(), (1920, 1080))
        self.assertEqual(VideoAspect.portrait.to_resolution(), (1080, 1920))
        self.assertEqual(VideoAspect.square.to_resolution(), (1080, 1080))

    def test_to_resolution_rejects_unsupported_value(self):
        with self.assertRaises(ValueError):
            VideoAspect.to_resolution("4:5")


class TestVideoParams(unittest.TestCase):
    def test_video_fit_mode_defaults_to_cover_and_validates_values(self):
        self.assertEqual(
            VideoParams(video_subject="Coffee").video_fit_mode,
            VideoFitMode.cover,
        )
        self.assertEqual(
            VideoParams(
                video_subject="Coffee", video_fit_mode="contain"
            ).video_fit_mode,
            VideoFitMode.contain,
        )
        with self.assertRaises(ValidationError):
            VideoParams(video_subject="Coffee", video_fit_mode="stretch")

    def test_rejects_non_positive_generation_counts(self):
        for field_name in ("video_clip_duration", "video_count"):
            for value in (0, -1, None):
                with self.subTest(field_name=field_name, value=value):
                    with self.assertRaises(ValidationError):
                        VideoParams(video_subject="Coffee", **{field_name: value})

    def test_accepts_positive_generation_counts(self):
        params = VideoParams(
            video_subject="Coffee", video_clip_duration=1, video_count=1
        )

        self.assertEqual(params.video_clip_duration, 1)
        self.assertEqual(params.video_count, 1)

    def test_subtitle_modes_accept_only_supported_api_values(self):
        """新增字幕参数必须拒绝拼写错误，避免请求成功后静默降级。"""
        params = VideoParams(
            video_subject="Coffee",
            subtitle_display_mode="word_by_word",
            subtitle_animation="pop_spring",
        )
        request = SubtitleRequest(
            video_script="Coffee",
            subtitle_display_mode="word_by_word",
            subtitle_animation="pop_spring",
        )

        self.assertEqual(params.subtitle_display_mode, "word_by_word")
        self.assertEqual(params.subtitle_animation, "pop_spring")
        self.assertEqual(request.subtitle_display_mode, "word_by_word")
        self.assertEqual(request.subtitle_animation, "pop_spring")

        invalid_cases = (
            ("subtitle_display_mode", "word-by-word"),
            ("subtitle_display_mode", "invalid"),
            ("subtitle_display_mode", None),
            ("subtitle_animation", "pop-spring"),
            ("subtitle_animation", "invalid"),
            ("subtitle_animation", None),
        )
        for field_name, value in invalid_cases:
            with self.subTest(model="VideoParams", field=field_name, value=value):
                with self.assertRaises(ValidationError):
                    VideoParams(video_subject="Coffee", **{field_name: value})
            with self.subTest(model="SubtitleRequest", field=field_name, value=value):
                with self.assertRaises(ValidationError):
                    SubtitleRequest(video_script="Coffee", **{field_name: value})

    def test_invalid_saved_subtitle_mode_falls_back_during_upgrade(self):
        """旧配置包含无效值时应回退默认值，而不是阻止服务启动。"""
        with patch.object(
            schema.config,
            "ui",
            {
                "subtitle_display_mode": "word-by-word",
                "subtitle_animation": "pop-spring",
            },
        ):
            self.assertEqual(
                schema._get_valid_ui_choice(
                    "subtitle_display_mode",
                    schema._SUBTITLE_DISPLAY_MODES,
                    "sentence",
                ),
                "sentence",
            )
            self.assertEqual(
                schema._get_valid_ui_choice(
                    "subtitle_animation",
                    schema._SUBTITLE_ANIMATIONS,
                    "none",
                ),
                "none",
            )


class TestRequestUpperBounds(unittest.TestCase):
    """异常大的参数会耗尽内存或付费额度，必须在入口处拒绝。"""

    def test_oversized_video_params_are_rejected(self):
        oversized = {
            "font_size": 1_000_000,
            "stroke_width": 1_000.0,
            "n_threads": 100_000,
            "video_count": 1_000_000,
            "video_clip_duration": 10_000,
            "video_script": "x" * (schema.MAX_VIDEO_SCRIPT_LENGTH + 1),
        }
        for field, value in oversized.items():
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    VideoParams(video_subject="x", **{field: value})
        with self.assertRaises(ValidationError):
            VideoParams(video_subject="x" * (schema.MAX_VIDEO_SUBJECT_LENGTH + 1))
        with self.assertRaises(ValidationError):
            schema.VideoTermsRequest(amount=10_000)
        with self.assertRaises(ValidationError):
            SubtitleRequest(video_script="x", font_size=1_000_000)

    def test_webui_ranges_remain_valid(self):
        params = VideoParams(
            video_subject="x",
            font_size=100,
            stroke_width=10.0,
            video_count=5,
            video_clip_duration=15,
        )
        self.assertEqual(params.font_size, 100)


if __name__ == "__main__":
    unittest.main()
