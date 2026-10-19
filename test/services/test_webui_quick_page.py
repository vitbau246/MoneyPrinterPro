import time
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import content_presets as cp
from app.services import output_library
from app.services import quick_create as qc
from app.services import quick_jobs as qj

WEBUI_MAIN = str(Path(__file__).parent.parent.parent / "webui" / "Main.py")


def _video_result(*args, **kwargs):
    saved = output_library.SavedItem(1, "#001 Video", ["#001 Video.mp4"])
    output = qc.VideoOutput("final-1.mp4", None, saved, True)
    return qc.VideoResult("task", "Video", "Kịch bản", None, 30.0, 1.0, [output])


class TestWebuiQuickPage(unittest.TestCase):
    def setUp(self):
        # Lựa chọn chế độ được lưu vào config.ui; trả lại mặc định cho các test WebUI khác.
        self.addCleanup(config.ui.pop, "webui_mode", None)
        self.jobs = qj.QuickJobs()
        patcher = patch.object(qj, "shared", return_value=self.jobs)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run_quick(self) -> AppTest:
        app = AppTest.from_file(WEBUI_MAIN, default_timeout=90)
        app.run()
        self.assertFalse(app.exception, [str(item.value) for item in app.exception])
        self.assertEqual(app.radio(key="webui_mode").value, "advanced")
        app.radio(key="webui_mode").set_value("quick").run()
        self.assertFalse(app.exception, [str(item.value) for item in app.exception])
        return app

    def test_quick_mode_shows_bot_features(self):
        app = self._run_quick()
        labels = [tab.label for tab in app.tabs]
        for label in ("Tạo một mục", "Tạo hàng loạt", "Thư viện thành phẩm"):
            self.assertIn(label, labels)
        self.assertEqual(config.ui.get("webui_mode"), "quick")
        options = app.selectbox(key="quick_preset").options
        self.assertEqual(len(options), len(cp.PRESETS))
        # Bản này không kiểm tra phiên bản trên GitHub.
        self.assertNotIn("api.github.com", str(app))

    def test_submit_video_enqueues_with_inline_options(self):
        app = self._run_quick()
        app.selectbox(key="quick_preset").set_value("facts")
        app.text_area(key="quick_prompt").set_value("5 sự thật về đại dương #90s #ngang #high")
        with patch.object(qc, "create_video", side_effect=_video_result) as create:
            app.button(key="quick_submit").click().run()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not create.called:
                time.sleep(0.05)
        self.assertFalse(app.exception, [str(item.value) for item in app.exception])
        jobs = self.jobs.jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].prompt, "5 sự thật về đại dương")
        self.assertEqual((jobs[0].duration, jobs[0].aspect, jobs[0].high), (90, "16:9", True))
        self.assertTrue(create.called)

    def test_invalid_duration_is_rejected(self):
        app = self._run_quick()
        app.selectbox(key="quick_preset").set_value("facts")
        app.text_area(key="quick_prompt").set_value("5 sự thật về đại dương #5s")
        app.button(key="quick_submit").click().run()
        self.assertTrue(any("Thời lượng" in item.value for item in app.error))
        self.assertEqual(self.jobs.jobs(), [])

    def test_batch_propose_then_approve(self):
        app = self._run_quick()
        app.text_area(key="quick_batch_theme").set_value("tiết kiệm tiền cho sinh viên #2")
        topics = [cp.Subtopic("Chủ đề 1", "ý"), cp.Subtopic("Chủ đề 2", "ý")]
        with patch.object(cp, "generate_subtopics", return_value=topics):
            app.button(key="quick_batch_propose").click().run()
        self.assertFalse(app.exception, [str(item.value) for item in app.exception])
        batches = self.jobs.batches()
        self.assertEqual(len(batches), 1)
        self.assertEqual((batches[0].count, batches[0].state), (2, qj.REVIEW))
        with patch.object(qc, "create_video", side_effect=_video_result):
            app.button(key=f"quick_go_{batches[0].id}").click().run()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and self.jobs.batches()[0].state != qj.FINISHED:
                time.sleep(0.05)
        self.assertFalse(app.exception, [str(item.value) for item in app.exception])
        self.assertEqual(self.jobs.batches()[0].sent, 2)


class TestWebuiSocialTab(unittest.TestCase):
    def setUp(self):
        import os
        import shutil

        from app.utils import utils

        self.addCleanup(config.ui.pop, "webui_mode", None)
        social = utils.storage_dir("social")
        shutil.rmtree(social, ignore_errors=True)
        self.addCleanup(shutil.rmtree, social, True)
        self.video = os.path.join(output_library.output_dir(output_library.VIDEO), "#003 Thử đăng.mp4")
        with open(self.video, "wb") as file:
            file.write(b"video")
        self.addCleanup(os.remove, self.video)

    def test_schedule_from_web(self):
        from app.services import social_schedule as ss

        app = AppTest.from_file(WEBUI_MAIN, default_timeout=90)
        app.run()
        app.radio(key="webui_mode").set_value("quick").run()
        self.assertIn("Đăng bài", [tab.label for tab in app.tabs])
        app.multiselect(key="social_videos").set_value([self.video]).run()
        self.assertEqual(app.text_input(key=next(
            key for key in app.session_state.filtered_state if str(key).startswith("social_title_")
        )).value, "Thử đăng")
        app.multiselect(key="social_platforms").set_value(["tiktok", "youtube"])
        app.radio(key="social_when").set_value("now")
        app.checkbox(key="social_dry_run").check()
        app.button(key="social_schedule").click().run()
        self.assertFalse(app.exception, [str(item.value) for item in app.exception])
        entries = ss.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(list(entries[0]["targets"]), ["tiktok", "youtube"])
        self.assertTrue(entries[0]["dry_run"])
        self.assertTrue(any("Đã lên lịch 1 video" in item.value for item in app.success))


if __name__ == "__main__":
    unittest.main()
