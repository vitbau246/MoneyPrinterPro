import os
import shutil
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from app.services import content_presets as cp
from app.services import output_library
from app.services import quick_create as qc
from app.services import social_publish as sp
from app.services import social_schedule as ss
from app.utils import utils


def _clean_social():
    shutil.rmtree(utils.storage_dir("social"), ignore_errors=True)


class SocialTestCase(unittest.TestCase):
    def setUp(self):
        _clean_social()
        self.addCleanup(_clean_social)
        folder = output_library.output_dir(output_library.VIDEO)
        self.videos = []
        for number, title in ((7, "Mẹo ngủ ngon"), (12, "Sự thật đại dương")):
            path = os.path.join(folder, f"#{number:03d} {title}.mp4")
            with open(path, "wb") as file:
                file.write(b"video")
            self.videos.append(path)
            self.addCleanup(os.remove, path)


class TestSettingsAndTime(SocialTestCase):
    def test_normalize(self):
        self.assertEqual(ss.normalize_slots(["19h30", "8:00", "7h", "25:00", "x", "8:00"]), ["07:00", "08:00", "19:30"])
        self.assertEqual(ss.normalize_platforms(["yt", "fb", "nope", "TikTok"]), ["facebook", "tiktok", "youtube"])

    def test_settings_roundtrip(self):
        self.assertFalse(ss.get_settings()["auto_post"])
        saved = ss.save_settings(auto_post=True, platforms=["tt"], slots=["9:15"])
        self.assertEqual(saved, {"auto_post": True, "platforms": ["tiktok"], "slots": ["09:15"]})
        self.assertEqual(ss.get_settings(), saved)

    def test_parse_when(self):
        now = datetime(2026, 10, 19, 15, 0).timestamp()
        self.assertEqual(ss.parse_when("ngay", now), now)
        self.assertEqual(ss.parse_when("20:00", now), datetime(2026, 10, 19, 20, 0).timestamp())
        self.assertEqual(ss.parse_when("9h30", now), datetime(2026, 10, 20, 9, 30).timestamp())
        self.assertEqual(ss.parse_when("21/10 8:00", now), datetime(2026, 10, 21, 8, 0).timestamp())
        self.assertIsNone(ss.parse_when("31/02 8:00", now))
        self.assertIsNone(ss.parse_when("mai", now))

    def test_next_free_slot_skips_taken(self):
        ss.save_settings(slots=["08:00", "20:00"])
        now = datetime(2026, 10, 19, 15, 0).timestamp()
        first = ss.next_free_slot(now)
        self.assertEqual(first, datetime(2026, 10, 19, 20, 0).timestamp())
        second = ss.next_free_slot(now, taken=[first])
        self.assertEqual(second, datetime(2026, 10, 20, 8, 0).timestamp())
        ss.save_settings(slots=[])
        self.assertEqual(ss.next_free_slot(now), now)


class TestScheduleStore(SocialTestCase):
    def test_library_lookup_and_captions(self):
        self.assertEqual([number for number, _, _ in ss.library_videos()], [12, 7])
        self.assertEqual(ss.find_video(7), self.videos[0])
        self.assertIsNone(ss.find_video(99))
        self.assertEqual(ss.caption_for(self.videos[0]), ("Mẹo ngủ ngon", ""))
        ss.remember_post(self.videos[0], "Tiêu đề SEO", "Mô tả #a")
        self.assertEqual(ss.caption_for(self.videos[0]), ("Tiêu đề SEO", "Mô tả #a"))

    def test_batch_gets_separate_slots(self):
        ss.save_settings(slots=["08:00", "12:00", "19:30"], platforms=["yt", "tt"])
        first = ss.schedule(self.videos[0])
        second = ss.schedule(self.videos[1])
        self.assertNotEqual(first["run_at"], second["run_at"])
        self.assertEqual(list(first["targets"]), ["tiktok", "youtube"])
        self.assertEqual(len(ss.entries()), 2)

    def test_cancel_run_now_remove(self):
        entry = ss.schedule(self.videos[0], ["fb"], time.time() + 3600)
        ss.cancel(entry["id"])
        self.assertEqual(ss.entry_status(ss.get(entry["id"])), ss.CANCELLED)
        ss.run_now(entry["id"])
        updated = ss.get(entry["id"])
        self.assertEqual(ss.entry_status(updated), ss.PENDING)
        self.assertLessEqual(updated["run_at"], time.time())
        ss.remove(entry["id"])
        self.assertIsNone(ss.get(entry["id"]))

    def test_rejects_missing_video_or_platform(self):
        with self.assertRaises(ValueError):
            ss.schedule("không-có.mp4", ["fb"])
        with self.assertRaises(ValueError):
            ss.schedule(self.videos[0], ["myspace"])


class TestProcessOnce(SocialTestCase):
    def setUp(self):
        super().setUp()
        self.notes = []
        self.notify = lambda chat_id, text: self.notes.append((chat_id, text))

    def test_publishes_due_platforms_in_order(self):
        ss.remember_post(self.videos[0], "Tiêu đề", "Mô tả")
        entry = ss.schedule(self.videos[0], ["fb", "yt"], time.time() - 1, chat_id=42)
        calls = []

        def publish(platform, content, dry_run, label):
            calls.append((platform, content.title, content.description, dry_run))
            return sp.Outcome(url="https://youtu.be/x" if platform == "youtube" else "")

        self.assertTrue(ss.process_once(publish, self.notify))
        self.assertTrue(ss.process_once(publish, self.notify))
        self.assertFalse(ss.process_once(publish, self.notify))
        self.assertEqual(calls, [("facebook", "Tiêu đề", "Mô tả", False), ("youtube", "Tiêu đề", "Mô tả", False)])
        done = ss.get(entry["id"])
        self.assertEqual(ss.entry_status(done), ss.DONE)
        self.assertEqual(done["targets"]["youtube"]["url"], "https://youtu.be/x")
        self.assertEqual([chat for chat, _ in self.notes], [42, 42])

    def test_future_entries_wait(self):
        ss.schedule(self.videos[0], ["fb"], time.time() + 3600)
        self.assertFalse(ss.process_once(MagicMock(), self.notify))

    def test_not_logged_in_fails_without_retry(self):
        entry = ss.schedule(self.videos[0], ["tt"], time.time() - 1)
        publish = MagicMock(side_effect=sp.NotLoggedIn("Chưa đăng nhập TikTok"))
        ss.process_once(publish, self.notify)
        self.assertEqual(ss.get(entry["id"])["targets"]["tiktok"]["status"], ss.FAILED)
        self.assertIn("Chưa đăng nhập", self.notes[0][1])

    def test_error_retries_later_then_fails(self):
        entry = ss.schedule(self.videos[0], ["yt"], time.time() - 1)
        publish = MagicMock(side_effect=sp.PublishError("mạng lỗi"))
        ss.process_once(publish, self.notify)
        target = ss.get(entry["id"])["targets"]["youtube"]
        self.assertEqual(target["status"], ss.PENDING)
        self.assertGreater(target["retry_at"], time.time())
        self.assertFalse(ss.process_once(publish, self.notify))
        ss.process_once(publish, self.notify, now=time.time() + ss.RETRY_DELAY_SECONDS + 1)
        self.assertEqual(ss.get(entry["id"])["targets"]["youtube"]["status"], ss.FAILED)
        self.assertEqual(len(self.notes), 1)

    def test_dry_run(self):
        entry = ss.schedule(self.videos[0], ["fb"], time.time() - 1, dry_run=True)
        publish = MagicMock(return_value=sp.Outcome(dry_run=True))
        ss.process_once(publish, self.notify)
        self.assertTrue(publish.call_args.kwargs["dry_run"])
        self.assertEqual(ss.entry_status(ss.get(entry["id"])), ss.TRIED)

    def test_interrupted_posts_are_reset(self):
        entry = ss.schedule(self.videos[0], ["fb"], time.time() - 1)
        ss._claim_due(time.time())
        self.assertEqual(ss.get(entry["id"])["targets"]["facebook"]["status"], ss.RUNNING)
        ss._reset_running()
        self.assertEqual(ss.get(entry["id"])["targets"]["facebook"]["status"], ss.PENDING)

    def test_runner_not_started_in_tests(self):
        with patch.object(ss.threading, "Thread") as thread:
            ss.start_runner()
        thread.assert_not_called()


class TestQuickCreatePosting(SocialTestCase):
    def _result(self, post=None):
        saved = output_library.SavedItem(1, "#007 Mẹo ngủ ngon", [self.videos[0]])
        return qc.VideoResult(
            "t", "Mẹo ngủ ngon", "kịch bản", post, 10.0, 1.0,
            [qc.VideoOutput("final.mp4", None, saved, True)],
        )

    def test_parse_post_flags(self):
        self.assertEqual(qc.parse_options("abc #dang")[1].post, True)
        self.assertEqual(qc.parse_options("abc #khongdang")[1].post, False)
        self.assertEqual(qc.parse_options("abc #không dang")[1].post, False)
        text, options = qc.parse_options("abc #dangnhap")
        self.assertIsNone(options.post)

    def test_schedule_outputs_follows_flag_and_setting(self):
        post = cp.PostPackage("kw", "Tiêu đề SEO", "Mô tả", ["#a", "#b"])
        self.assertEqual(qc.schedule_outputs(self._result(post), None, source="web"), [])
        entries = qc.schedule_outputs(self._result(post), True, source="telegram", chat_id=5)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Tiêu đề SEO")
        self.assertEqual(entries[0]["description"], "Mô tả\n\n#a #b")
        self.assertEqual(entries[0]["chat_id"], 5)
        self.assertIn("Lịch đăng:", qc.schedule_note(entries))
        ss.save_settings(auto_post=True)
        self.assertEqual(len(qc.schedule_outputs(self._result(), None, source="web")), 1)
        self.assertEqual(qc.schedule_outputs(self._result(), False, source="web"), [])


if __name__ == "__main__":
    unittest.main()
