import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

import toml

from app.config import config
from app.models import const
from app.services import content_presets as cp
from app.services import gif_maker
from app.services import output_library
from app.services import quick_create as qc
from app.services import quick_jobs as qj


class TestParseOptions(unittest.TestCase):
    def test_extracts_bot_flags(self):
        text, options = qc.parse_options("5 mẹo ngủ ngon #90s #ngang #en #high #gif")
        self.assertEqual(text, "5 mẹo ngủ ngon")
        self.assertEqual(options.duration, 90)
        self.assertEqual(options.aspect, "16:9")
        self.assertEqual(options.language, "en-US")
        self.assertTrue(options.high)
        self.assertTrue(options.gif)
        self.assertIsNone(options.count)

    def test_batch_count_only_in_batch_mode(self):
        text, options = qc.parse_options("meo tiết kiệm tiền #15 #2p", batch=True)
        self.assertEqual(text, "meo tiết kiệm tiền")
        self.assertEqual(options.count, 15)
        self.assertEqual(options.duration, 120)
        text, options = qc.parse_options("top #15 sự thật")
        self.assertIsNone(options.count)
        self.assertIn("#15", text)

    def test_duration_error(self):
        self.assertEqual(qc.duration_error(None), "")
        self.assertEqual(qc.duration_error(45), "")
        self.assertIn("Thời lượng", qc.duration_error(5))
        self.assertIn("Thời lượng", qc.duration_error(cp.MAX_DURATION_SECONDS + 1))

    def test_request_error(self):
        product = next(p for p in cp.PRESETS.values() if p.requires_media)
        facts = cp.PRESETS["facts"]
        self.assertIn("GIF", qc.request_error(product, "áo thun cotton", 1, gif=True))
        self.assertIn("Pixabay", qc.request_error(facts, "sự thật về đại dương", 2, gif=True))
        self.assertIn("không dùng ảnh", qc.request_error(facts, "sự thật về đại dương", 2))
        self.assertEqual(qc.request_error(facts, "sự thật về đại dương"), "")

    def test_shared_settings_follow_config(self):
        with patch.dict(
            config._cfg,
            {"telegram": {"high_model": "model-x", "voices": {"en-US": "voice-y"}}},
        ):
            self.assertEqual(qc.high_model(), "model-x")
            self.assertEqual(qc.language_voice("en-US"), "voice-y")
            self.assertIsNone(qc.language_voice("vi-VN"))
        with patch.dict(config._cfg, {"telegram": {}}):
            self.assertEqual(qc.high_model(), qc.DEFAULT_HIGH_MODEL)
            self.assertEqual(qc.default_language(), cp.DEFAULT_LANGUAGE)
            self.assertIsNone(qc.default_duration())


class TestReloadConfig(unittest.TestCase):
    def test_reload_updates_sections_in_place(self):
        app_section, ui_section = config.app, config.ui
        original_app, original_ui = dict(config.app), dict(config.ui)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "config.toml")
            data = {
                "app": {**original_app, "video_source": "pixabay-reloaded"},
                "ui": {"voice_name": "vi-VN-NamMinhNeural-Male"},
                "telegram": {"high_model": "model-reloaded"},
            }
            with open(path, "w", encoding="utf-8") as file:
                toml.dump(data, file)
            try:
                with patch.object(config, "config_file", path):
                    self.assertTrue(config.reload_config())
                self.assertIs(config.app, app_section)
                self.assertIs(config.ui, ui_section)
                self.assertEqual(config.app["video_source"], "pixabay-reloaded")
                self.assertEqual(dict(config.ui), {"voice_name": "vi-VN-NamMinhNeural-Male"})
                self.assertEqual(qc.high_model(), "model-reloaded")
            finally:
                config.reload_config()
                config.app.clear()
                config.app.update(original_app)
                config.ui.clear()
                config.ui.update(original_ui)

    def test_invalid_file_keeps_current_config(self):
        before = dict(config.app)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "config.toml")
            with open(path, "w", encoding="utf-8") as file:
                file.write("[app\nbroken")
            with patch.object(config, "config_file", path):
                self.assertFalse(config.reload_config())
        self.assertEqual(dict(config.app), before)


def _saved(name):
    return output_library.SavedItem(1, name, [f"{name}.mp4", f"{name}.jpg", f"{name}.txt"])


class TestCreateVideo(unittest.TestCase):
    def setUp(self):
        self.params = MagicMock(cover_title="Tiêu đề SEO")
        patches = [
            patch.object(cp, "build_params", return_value=self.params),
            patch.object(
                cp,
                "prepare_script_and_post",
                return_value=cp.PostPackage("từ khoá", "Tiêu đề SEO", "Mô tả", ["#a"]),
            ),
            patch.object(qc, "make_cover", return_value="cover.jpg"),
            patch.object(output_library, "save_video", side_effect=lambda *a: _saved("#001 Tiêu đề")),
            patch.object(output_library, "remove_task_dir"),
        ]
        self.mocks = [item.start() for item in patches]
        for item in patches:
            self.addCleanup(item.stop)
        self.remove_task_dir = self.mocks[-1]

    def test_delivers_then_saves_and_cleans_task(self):
        order = []
        self.mocks[3].side_effect = lambda *args: order.append("save") or _saved("#001")
        result_payload = {
            "state": const.TASK_STATE_COMPLETE,
            "videos": ["task/final-1.mp4"],
            "script": " Kịch bản ",
            "audio_duration": 42,
        }
        stages = []
        with patch("app.services.task.start", return_value=result_payload):
            result = qc.create_video(
                cp.PRESETS["facts"],
                "sự thật về đại dương",
                on_stage=stages.append,
                deliver=lambda res, path, cover: order.append("deliver") or True,
            )
        self.assertEqual(order, ["deliver", "save"])
        self.assertEqual(stages, ["script", "render", "deliver"])
        self.assertEqual(result.title, "Tiêu đề SEO")
        self.assertEqual(result.script, "Kịch bản")
        self.assertEqual(result.audio_duration, 42)
        self.assertTrue(result.delivered)
        self.assertEqual(result.outputs[0].cover_path, "cover.jpg")
        self.remove_task_dir.assert_called_once_with(result.task_id)

    def test_pipeline_failure_raises(self):
        failed = {"state": const.TASK_STATE_FAILED, "failed_stage": "audio", "error": "tts"}
        with patch("app.services.task.start", return_value=failed):
            with self.assertRaises(qc.VideoFailed) as caught:
                qc.create_video(cp.PRESETS["facts"], "sự thật về đại dương")
        self.assertIn("bước audio", caught.exception.describe())
        self.remove_task_dir.assert_not_called()

    def test_high_uses_high_model(self):
        seen = []
        with patch.object(qc, "high_model", return_value="model-high"), patch.object(
            qc.llm, "use_model", side_effect=lambda name: seen.append(name) or MagicMock()
        ), patch(
            "app.services.task.start",
            return_value={"state": const.TASK_STATE_COMPLETE, "videos": ["v.mp4"]},
        ):
            qc.create_video(cp.PRESETS["facts"], "sự thật về đại dương", high=True)
        self.assertEqual(seen, ["model-high"])


class TestCreateGif(unittest.TestCase):
    def test_records_used_terms_and_saves(self):
        gif_text = cp.GifText("Kiên trì mỗi ngày", ["mountain climber"], "Diễn giải")
        gif = gif_maker.GifResult("a.gif", "a.mp4", 480, 854, 4.0, MagicMock(), MagicMock())
        used = ["ocean"]
        with patch.object(cp, "generate_gif_text", return_value=gif_text) as generate, patch.object(
            gif_maker, "create_text_gif", return_value=gif
        ), patch.object(output_library, "save_gif", return_value=_saved("#002")) as save:
            output = qc.create_gif(cp.PRESETS["motivation"], "kiên trì", used_terms=used)
        self.assertEqual(generate.call_args.args[3], ["ocean"])
        self.assertEqual(used, ["ocean", "mountain climber"])
        save.assert_called_once_with("a.gif", "a.mp4", "Kiên trì mỗi ngày", "Diễn giải")
        self.assertEqual(output.saved.name, "#002")

    def test_missing_text_is_user_error(self):
        with patch.object(cp, "generate_gif_text", return_value=None):
            with self.assertRaises(gif_maker.GifError):
                qc.create_gif(cp.PRESETS["motivation"], "kiên trì")


def _wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _video_result(*args, **kwargs):
    saved = _saved("#010 Video")
    output = qc.VideoOutput("task/final-1.mp4", "cover.jpg", saved, True)
    return qc.VideoResult(
        "task-id", "Tiêu đề", "Kịch bản", None, 30.0, 1.0, [output]
    )


class TestQuickJobs(unittest.TestCase):
    def test_video_job_runs_and_keeps_result(self):
        jobs = qj.QuickJobs()
        with patch.object(qc, "create_video", side_effect=_video_result) as create:
            job = jobs.submit("facts", "sự thật về đại dương", duration=45, high=True)
            self.assertTrue(_wait(lambda: jobs.jobs()[0].state == qj.DONE))
        done = jobs.jobs()[0]
        self.assertEqual(done.id, job.id)
        self.assertEqual(done.saved_names, ["#010 Video"])
        self.assertIn("#010 Video.mp4", done.files)
        self.assertEqual(done.cover, "#010 Video.jpg")
        self.assertEqual(create.call_args.kwargs["duration"], 45)
        self.assertTrue(create.call_args.kwargs["high"])

    def test_failed_video_reports_stage(self):
        jobs = qj.QuickJobs()
        with patch.object(qc, "create_video", side_effect=qc.VideoFailed("audio", "tts")):
            jobs.submit("facts", "sự thật về đại dương")
            self.assertTrue(_wait(lambda: jobs.jobs()[0].state == qj.FAILED))
        self.assertIn("bước audio", jobs.jobs()[0].error)

    def test_batch_review_approve_and_retry(self):
        jobs = qj.QuickJobs(retries=1)
        topics = [cp.Subtopic(f"Chủ đề {index}", "ý chính") for index in range(1, 4)]
        calls = []

        def create(preset, prompt, **kwargs):
            calls.append(prompt)
            # Mục thứ hai lỗi lần đầu, được thử lại một lần.
            if prompt.startswith("Chủ đề 2") and calls.count(prompt) == 1:
                raise qc.VideoFailed("render", "lỗi tạm")
            return _video_result()

        with patch.object(cp, "generate_subtopics", return_value=topics):
            batch = jobs.propose_batch("tips", "tiết kiệm tiền", 3)
        self.assertEqual(batch.state, qj.REVIEW)
        jobs.set_topics(batch.id, topics + [cp.Subtopic("  ", "bỏ dòng trống")])
        self.assertEqual(len(jobs.get_batch(batch.id).topics), 3)
        with patch.object(qc, "create_video", side_effect=create):
            jobs.approve_batch(batch.id)
            self.assertTrue(
                _wait(lambda: jobs.get_batch(batch.id).state == qj.FINISHED)
            )
        finished = jobs.get_batch(batch.id)
        self.assertEqual(finished.sent, 3)
        self.assertEqual(finished.failed, [])
        self.assertEqual(len(calls), 4)
        with self.assertRaises(ValueError):
            jobs.approve_batch(batch.id)

    def test_stop_batch_skips_remaining(self):
        jobs = qj.QuickJobs(retries=0)
        topics = [cp.Subtopic(f"Chủ đề {index}") for index in range(1, 4)]
        started = __import__("threading").Event()
        release = __import__("threading").Event()

        def create(*args, **kwargs):
            started.set()
            release.wait(5)
            return _video_result()

        with patch.object(cp, "generate_subtopics", return_value=topics):
            batch = jobs.propose_batch("tips", "tiết kiệm tiền", 3)
        with patch.object(qc, "create_video", side_effect=create):
            jobs.approve_batch(batch.id)
            self.assertTrue(started.wait(5))
            jobs.stop_batch(batch.id)
            release.set()
            self.assertTrue(
                _wait(lambda: jobs.get_batch(batch.id).state == qj.FINISHED)
            )
        finished = jobs.get_batch(batch.id)
        self.assertTrue(finished.stopped)
        self.assertEqual(finished.sent, 1)

    def test_gif_batch_shares_used_terms(self):
        jobs = qj.QuickJobs()
        topics = [cp.Subtopic("A"), cp.Subtopic("B")]
        seen = []

        def create_gif(preset, prompt, **kwargs):
            seen.append(list(kwargs["used_terms"]))
            kwargs["used_terms"].append(prompt)
            text = cp.GifText(prompt, [prompt], "chi tiết")
            gif = gif_maker.GifResult("x.gif", None, 1, 1, 1.0, None, None)
            return qc.GifOutput(text, gif, None, 1.0)

        with patch.object(cp, "generate_subtopics", return_value=topics):
            batch = jobs.propose_batch("motivation", "kiên trì", 2, gif=True)
        with patch.object(qc, "create_gif", side_effect=create_gif):
            jobs.approve_batch(batch.id)
            self.assertTrue(_wait(lambda: jobs.get_batch(batch.id).state == qj.FINISHED))
        self.assertEqual(seen, [[], ["A"]])

    def test_cancel_and_remove_finished(self):
        jobs = qj.QuickJobs()
        with patch.object(cp, "generate_subtopics", return_value=[cp.Subtopic("A")]):
            batch = jobs.propose_batch("tips", "tiết kiệm tiền", 1)
        jobs.cancel_batch(batch.id)
        self.assertEqual(jobs.get_batch(batch.id).state, qj.CANCELLED)
        jobs.remove_finished()
        self.assertIsNone(jobs.get_batch(batch.id))

    def test_propose_without_topics_raises(self):
        jobs = qj.QuickJobs()
        with patch.object(cp, "generate_subtopics", return_value=[]):
            with self.assertRaises(RuntimeError):
                jobs.propose_batch("tips", "tiết kiệm tiền", 3)
        self.assertEqual(jobs.batches(), [])


if __name__ == "__main__":
    unittest.main()
