import time
import unittest
from unittest.mock import patch

from app.services import content_presets as cp
from app.services import output_library
from app.services import quick_create as qc
from app.services import quick_jobs as qj


def _ok(*args, **kwargs):
    saved = output_library.SavedItem(1, "#001 Video", ["#001 Video.mp4"])
    output = qc.VideoOutput("final-1.mp4", None, saved, True)
    return qc.VideoResult("task", "Video", "Kịch bản", None, 30.0, 1.0, [output])


class TestRetryFailedJobs(unittest.TestCase):
    def _wait(self, check):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not check():
            time.sleep(0.02)
        self.assertTrue(check())

    def test_retry_failed_batch_items_reopens_and_finishes_batch(self):
        jobs = qj.QuickJobs(retries=0)
        topics = [cp.Subtopic("Chủ đề 1", "ý"), cp.Subtopic("Chủ đề 2", "ý")]
        with patch.object(cp, "generate_subtopics", return_value=topics):
            batch = jobs.propose_batch("facts", "chủ đề", 2)
        outcomes = [RuntimeError("boom"), _ok(), _ok()]

        def create(*args, **kwargs):
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with patch.object(qc, "create_video", side_effect=create):
            jobs.approve_batch(batch.id)
            self._wait(lambda: jobs.get_batch(batch.id).state == qj.FINISHED)
            done = jobs.get_batch(batch.id)
            self.assertEqual((done.sent, done.failed), (1, [1]))

            self.assertEqual(jobs.retry_failed(batch.id), 1)
            self._wait(lambda: jobs.get_batch(batch.id).state == qj.FINISHED)

        final = jobs.get_batch(batch.id)
        self.assertEqual((final.sent, final.failed), (2, []))
        self.assertEqual({job.state for job in jobs.jobs()}, {qj.DONE})

    def test_retry_only_applies_to_failed_jobs(self):
        jobs = qj.QuickJobs(retries=0)
        with patch.object(qc, "create_video", side_effect=_ok):
            job = jobs.submit("facts", "5 sự thật")
            self._wait(lambda: jobs.jobs()[0].state == qj.DONE)
        self.assertFalse(jobs.retry_job(job.id))
        self.assertFalse(jobs.retry_job("missing"))


if __name__ == "__main__":
    unittest.main()
