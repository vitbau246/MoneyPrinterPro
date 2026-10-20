"""
Hàng đợi "Tạo nhanh" của WebUI: cùng cách làm việc với bot Telegram.

- Video xếp hàng và dựng lần lượt từng cái (dựng video tốn nhiều CPU/RAM).
- Ảnh GIF lẻ chạy ngay ngoài hàng đợi video, mỗi lúc một ảnh.
- Loạt (hàng loạt theo một chủ đề): AI đề xuất chủ đề con, người dùng duyệt/sửa rồi
  mới tạo; mỗi lúc loạt chỉ giữ một chỗ trong hàng đợi để yêu cầu lẻ được xen vào,
  mục lỗi được thử lại, dừng được sau mục đang tạo.

Phần tạo thật nằm ở app/services/quick_create.py (dùng chung với bot). Trạng thái
giữ trong bộ nhớ của tiến trình WebUI, nên các tab trình duyệt thấy cùng hàng đợi;
thành phẩm vẫn nằm trong storage/output sau khi khởi động lại.
"""

from __future__ import annotations

import queue
import threading
import time
import traceback
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field, replace
from uuid import uuid4

from loguru import logger

from app.config import config
from app.services import content_presets as cp
from app.services import gif_maker
from app.services import quick_create as qc

VIDEO = "video"
GIF = "gif"

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
SKIPPED = "skipped"

REVIEW = "review"
BATCH_RUNNING = "running"
FINISHED = "finished"
CANCELLED = "cancelled"

# Chỉ giữ trong bộ nhớ các yêu cầu gần nhất; thành phẩm đã nằm trong storage/output.
MAX_FINISHED_JOBS = 60
MAX_FINISHED_BATCHES = 10
PROGRESS_INTERVAL_SECONDS = 2


@dataclass
class Job:
    id: str
    kind: str
    preset_key: str
    prompt: str
    aspect: str | None = None
    duration: int | None = None
    language: str = cp.DEFAULT_LANGUAGE
    high: bool = False
    # Lên lịch đăng Facebook/TikTok/YouTube sau khi tạo; None theo đăng tự động.
    post: bool | None = None
    material_paths: list[str] = field(default_factory=list)
    batch_id: str | None = None
    # Số thứ tự (từ 1) trong loạt.
    number: int = 0
    state: str = QUEUED
    stage: str = ""
    progress: int = 0
    error: str = ""
    created: float = field(default_factory=time.time)
    started: float = 0.0
    finished: float = 0.0
    title: str = ""
    # Thành phẩm: file chính (video/ảnh GIF), bản MP4 của GIF, ảnh bìa, file .txt.
    files: list[str] = field(default_factory=list)
    cover: str | None = None
    saved_names: list[str] = field(default_factory=list)
    # Nội dung đăng bài chuẩn SEO (video) hoặc lời diễn giải (ảnh GIF).
    post_text: str = ""
    keyword: str = ""
    script: str = ""
    schedule_note: str = ""

    @property
    def preset(self) -> cp.ContentPreset:
        return cp.PRESETS[self.preset_key]

    @property
    def active(self) -> bool:
        return self.state in (QUEUED, RUNNING)


@dataclass
class Batch:
    id: str
    preset_key: str
    theme: str
    count: int
    aspect: str | None = None
    duration: int | None = None
    language: str = cp.DEFAULT_LANGUAGE
    gif: bool = False
    high: bool = False
    post: bool | None = None
    topics: list[cp.Subtopic] = field(default_factory=list)
    state: str = REVIEW
    note: str = ""
    # Cảnh (từ khoá Pixabay) các ảnh GIF trước trong loạt đã dùng, để ảnh sau chọn khác.
    used_terms: list[str] = field(default_factory=list)
    job_ids: list[str] = field(default_factory=list)
    next_index: int = 0
    sent: int = 0
    failed: list[int] = field(default_factory=list)
    stopped: bool = False
    created: float = field(default_factory=time.time)
    started: float = 0.0
    finished: float = 0.0

    @property
    def preset(self) -> cp.ContentPreset:
        return cp.PRESETS[self.preset_key]

    @property
    def unit(self) -> str:
        return "ảnh GIF" if self.gif else "video"


class QuickJobs:
    """Hàng đợi dùng chung cho mọi phiên WebUI trong cùng tiến trình."""

    def __init__(
        self,
        render_lock: Callable[[], AbstractContextManager] | None = None,
        retries: int = qc.BATCH_RETRIES,
    ):
        # Khoá giữ trong lúc dựng video; WebUI truyền khoá cấu hình để không dựng
        # chồng với chế độ tuỳ chỉnh chi tiết và không đổi cấu hình giữa chừng.
        self._render_lock = render_lock or nullcontext
        self._retries = retries
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._batches: dict[str, Batch] = {}
        self._queue: queue.Queue[str] = queue.Queue()
        self._gif_lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._running_id: str | None = None

    # ------------------------------------------------------------ đọc trạng thái

    def jobs(self) -> list[Job]:
        """Bản sao các yêu cầu, mới nhất trước."""
        with self._lock:
            return [replace(job) for job in reversed(self._jobs.values())]

    def batches(self) -> list[Batch]:
        with self._lock:
            return [
                replace(batch, topics=list(batch.topics), failed=list(batch.failed))
                for batch in reversed(self._batches.values())
            ]

    def get_batch(self, batch_id: str) -> Batch | None:
        with self._lock:
            batch = self._batches.get(batch_id)
            return replace(batch, topics=list(batch.topics)) if batch else None

    def waiting(self) -> int:
        """Số video đang chờ hoặc đang dựng."""
        with self._lock:
            return sum(1 for job in self._jobs.values() if job.kind == VIDEO and job.active)

    # ---------------------------------------------------------------- yêu cầu lẻ

    def submit(
        self,
        preset_key: str,
        prompt: str,
        *,
        gif: bool = False,
        aspect: str | None = None,
        duration: int | None = None,
        language: str | None = None,
        high: bool = False,
        material_paths: Sequence[str] = (),
        post: bool | None = None,
    ) -> Job:
        job = Job(
            id=uuid4().hex[:12],
            kind=GIF if gif else VIDEO,
            preset_key=preset_key,
            prompt=prompt.strip(),
            aspect=aspect,
            duration=duration,
            language=language or qc.default_language(),
            high=high,
            post=post,
            material_paths=list(material_paths),
            title=cp.cover_title(prompt),
        )
        with self._lock:
            self._jobs[job.id] = job
            self._trim()
        if gif:
            # Ảnh GIF chỉ mất vài chục giây nên không xếp sau video dài, như bot.
            threading.Thread(target=self._run_standalone_gif, args=(job,), daemon=True).start()
        else:
            self._enqueue(job)
        return job

    def remove_finished(self) -> None:
        """Xoá các yêu cầu đã xong khỏi danh sách (thành phẩm vẫn giữ nguyên)."""
        with self._lock:
            for job_id in [key for key, job in self._jobs.items() if not job.active]:
                del self._jobs[job_id]
            for batch_id in [
                key
                for key, batch in self._batches.items()
                if batch.state in (FINISHED, CANCELLED)
            ]:
                del self._batches[batch_id]

    # -------------------------------------------------------------------- loạt

    def propose_batch(
        self,
        preset_key: str,
        theme: str,
        count: int,
        *,
        gif: bool = False,
        aspect: str | None = None,
        duration: int | None = None,
        language: str | None = None,
        high: bool = False,
        post: bool | None = None,
    ) -> Batch:
        """Gọi AI đề xuất chủ đề con (mất vài giây) và giữ loạt chờ duyệt."""
        batch = Batch(
            id=uuid4().hex[:12],
            preset_key=preset_key,
            theme=theme.strip(),
            count=min(max(int(count), 1), cp.MAX_BATCH_TOPICS),
            aspect=aspect,
            duration=duration,
            language=language or qc.default_language(),
            gif=gif,
            high=high,
            post=post,
        )
        with qc.llm_model(high):
            topics = cp.generate_subtopics(batch.preset, batch.theme, batch.count)
        if not topics:
            raise RuntimeError("AI không đề xuất được chủ đề con, thử lại sau ít phút.")
        batch.topics = topics
        if len(topics) < batch.count:
            batch.note = f"AI chỉ đề xuất được {len(topics)}/{batch.count} chủ đề con."
        with self._lock:
            self._batches[batch.id] = batch
            self._trim()
        return replace(batch, topics=list(batch.topics))

    def revise_batch(self, batch_id: str, feedback: str) -> Batch:
        """Sửa danh sách theo góp ý; lỗi AI thì giữ danh sách cũ và ném RuntimeError."""
        batch = self._reviewing(batch_id)
        with qc.llm_model(batch.high):
            topics = cp.generate_subtopics(
                batch.preset, batch.theme, len(batch.topics), list(batch.topics), feedback
            )
        if not topics:
            raise RuntimeError("Chưa sửa được danh sách, vẫn giữ danh sách trước.")
        with self._lock:
            if batch.state == REVIEW:
                batch.topics = topics
                batch.note = ""
        return replace(batch, topics=list(batch.topics))

    def set_topics(self, batch_id: str, topics: Sequence[cp.Subtopic]) -> None:
        """Lưu danh sách người dùng tự sửa trên web."""
        cleaned = [
            cp.Subtopic(topic.title.strip(), topic.content.strip())
            for topic in topics
            if topic.title and topic.title.strip()
        ][: cp.MAX_BATCH_TOPICS]
        with self._lock:
            batch = self._batches.get(batch_id)
            if batch and batch.state == REVIEW:
                batch.topics = cleaned

    def approve_batch(self, batch_id: str) -> None:
        with self._lock:
            batch = self._reviewing(batch_id)
            if not batch.topics:
                raise ValueError("Danh sách chủ đề con đang trống.")
            batch.state = BATCH_RUNNING
            batch.started = time.time()
        logger.info(
            f"webui batch {batch.id}: {len(batch.topics)} {batch.unit} "
            f"/{batch.preset.command} – {batch.theme[:100]}"
        )
        self._continue_batch(batch)

    def cancel_batch(self, batch_id: str) -> None:
        with self._lock:
            batch = self._batches.get(batch_id)
            if batch and batch.state == REVIEW:
                batch.state = CANCELLED
                batch.finished = time.time()

    def stop_batch(self, batch_id: str) -> None:
        """Dừng loạt sau mục đang tạo; mục còn chờ bị bỏ."""
        with self._lock:
            batch = self._batches.get(batch_id)
            if not batch or batch.state != BATCH_RUNNING:
                return
            batch.stopped = True
            running = any(
                self._jobs[job_id].state == RUNNING
                for job_id in batch.job_ids
                if job_id in self._jobs
            )
        if not running:
            self._finish_batch(batch)

    def _reviewing(self, batch_id: str) -> Batch:
        with self._lock:
            batch = self._batches.get(batch_id)
            if batch is None or batch.state != REVIEW:
                raise ValueError("Loạt này đã duyệt, đã huỷ hoặc không còn.")
            return batch

    def _continue_batch(self, batch: Batch) -> None:
        """Xếp mục kế tiếp của loạt; hết mục hoặc đã dừng thì kết thúc loạt."""
        with self._lock:
            if batch.stopped or batch.next_index >= len(batch.topics):
                done = True
            else:
                done = False
                topic = batch.topics[batch.next_index]
                batch.next_index += 1
                job = Job(
                    id=uuid4().hex[:12],
                    kind=GIF if batch.gif else VIDEO,
                    preset_key=batch.preset_key,
                    prompt=topic.prompt(),
                    aspect=batch.aspect,
                    duration=batch.duration,
                    language=batch.language,
                    high=batch.high,
                    post=batch.post,
                    batch_id=batch.id,
                    number=batch.next_index,
                    title=topic.title,
                )
                self._jobs[job.id] = job
                batch.job_ids.append(job.id)
        if done:
            self._finish_batch(batch)
        else:
            self._enqueue(job)

    def _finish_batch(self, batch: Batch) -> None:
        with self._lock:
            if batch.state != BATCH_RUNNING:
                return
            batch.state = FINISHED
            batch.finished = time.time()
        logger.info(
            f"webui batch {batch.id} finished: {batch.sent}/{len(batch.topics)} "
            f"{batch.unit}, failed {batch.failed}, stopped={batch.stopped}"
        )

    # ------------------------------------------------------------------ chạy job

    def _enqueue(self, job: Job) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(
                    target=self._work, name="mpt-quick-create", daemon=True
                )
                self._worker.start()
        self._queue.put(job.id)

    def _work(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                self._run_queued(job_id)
            except Exception:
                logger.exception(f"quick create worker failed on job {job_id}")
            finally:
                self._queue.task_done()

    def _run_queued(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            batch = self._batches.get(job.batch_id) if job and job.batch_id else None
            if job is None:
                return
            if batch and batch.stopped:
                job.state = SKIPPED
                job.stage = "Đã bỏ vì loạt đã dừng."
                job.finished = time.time()
            else:
                job.state = RUNNING
                job.started = time.time()
        if job.state == RUNNING:
            ok = False
            for attempt in range(1 + (self._retries if batch else 0)):
                if attempt:
                    logger.warning(f"retrying batch item {job.number}: {job.title}")
                    with self._lock:
                        job.state, job.error, job.progress = RUNNING, "", 0
                ok = self._run_gif(job, batch) if job.kind == GIF else self._run_video(job)
                if ok or (batch and batch.stopped):
                    break
            if batch:
                with self._lock:
                    if ok:
                        batch.sent += 1
                    else:
                        batch.failed.append(job.number)
        if batch:
            self._continue_batch(batch)

    def _set(self, job: Job, **values) -> None:
        with self._lock:
            for key, value in values.items():
                setattr(job, key, value)

    def _fail(self, job: Job, error: str) -> bool:
        self._set(job, state=FAILED, error=error, stage="", finished=time.time())
        return False

    def _run_video(self, job: Job) -> bool:
        stages = {
            "script": "Đang viết kịch bản và nội dung đăng bài...",
            "render": "Đang dựng video...",
            "deliver": "Đang làm ảnh bìa và lưu vào thư mục thành phẩm...",
        }
        try:
            result = qc.create_video(
                job.preset,
                job.prompt,
                aspect=job.aspect,
                duration=job.duration,
                language=job.language,
                high=job.high,
                material_paths=job.material_paths or None,
                on_stage=lambda stage: self._set(job, stage=stages.get(stage, stage)),
                on_progress=lambda progress: self._set(job, progress=progress),
                progress_interval=PROGRESS_INTERVAL_SECONDS,
                render_lock=self._render_lock(),
            )
        except qc.VideoFailed as exc:
            return self._fail(job, exc.describe())
        except Exception as exc:
            logger.error(f"quick create video failed: {exc}\n{traceback.format_exc()}")
            return self._fail(job, f"{type(exc).__name__}: {exc}")

        files: list[str] = []
        names: list[str] = []
        cover = None
        for output in result.outputs:
            if output.saved:
                files.extend(output.saved.paths)
                names.append(output.saved.name)
                cover = next(
                    (path for path in output.saved.paths if path.lower().endswith(".jpg")),
                    cover,
                )
            else:
                files.append(output.path)
                cover = cover or output.cover_path
        post = result.post
        try:
            scheduled = qc.schedule_outputs(result, job.post, source="web")
        except Exception:
            logger.exception("cannot schedule social posts")
            scheduled = []
        self._set(
            job,
            schedule_note=qc.schedule_note(scheduled),
            state=DONE,
            stage="",
            progress=100,
            finished=time.time(),
            title=result.title,
            files=files,
            cover=cover,
            saved_names=names,
            post_text=(
                post.text(5000) + (f"\n\nThẻ YouTube: {', '.join(post.tags)}" if post.tags else "")
                if post
                else ""
            ),
            keyword=post.keyword if post else "",
            script=result.script,
        )
        return True

    def _run_standalone_gif(self, job: Job) -> None:
        with self._gif_lock:
            self._set(job, state=RUNNING, started=time.time())
            self._run_gif(job, None)

    def _run_gif(self, job: Job, batch: Batch | None) -> bool:
        stages = {
            "text": "Đang viết chữ cho ảnh GIF...",
            "clip": "Đang tìm clip Pixabay và chèn chữ",
            "deliver": "Đang lưu vào thư mục thành phẩm...",
        }

        def on_stage(stage: str, text: str) -> None:
            label = stages.get(stage, stage)
            self._set(job, stage=f"{label}: {text}" if text else label)

        try:
            output = qc.create_gif(
                job.preset,
                job.prompt,
                aspect=job.aspect,
                language=job.language,
                high=job.high,
                used_terms=batch.used_terms if batch else None,
                on_stage=on_stage,
            )
        except gif_maker.GifError as exc:
            return self._fail(job, f"Không tạo được ảnh GIF: {exc}")
        except Exception as exc:
            logger.error(f"quick create gif failed: {exc}\n{traceback.format_exc()}")
            return self._fail(job, f"{type(exc).__name__}: {exc}")
        saved = output.saved
        self._set(
            job,
            state=DONE,
            stage="",
            progress=100,
            finished=time.time(),
            title=output.text.text,
            files=list(saved.paths) if saved else [
                path for path in (output.gif.path, output.gif.preview_path) if path
            ],
            saved_names=[saved.name] if saved else [],
            post_text=output.text.detail,
        )
        return True

    def _trim(self) -> None:
        """Bỏ bớt yêu cầu và loạt đã xong lâu nhất để bộ nhớ không tăng mãi."""
        finished = [key for key, job in self._jobs.items() if not job.active]
        for key in finished[: max(len(finished) - MAX_FINISHED_JOBS, 0)]:
            del self._jobs[key]
        closed = [
            key
            for key, batch in self._batches.items()
            if batch.state in (FINISHED, CANCELLED)
        ]
        for key in closed[: max(len(closed) - MAX_FINISHED_BATCHES, 0)]:
            del self._batches[key]


_shared: QuickJobs | None = None
_shared_lock = threading.Lock()


def shared() -> QuickJobs:
    """
    Hàng đợi chung của tiến trình WebUI. Video dựng dưới khoá cấu hình giống chế độ
    tuỳ chỉnh chi tiết, nên hai chế độ không dựng chồng lên nhau.
    """
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = QuickJobs(render_lock=config.runtime_config_lock)
        return _shared
