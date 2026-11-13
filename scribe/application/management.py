"""Use cases behind the web page and the HTTP API."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import BinaryIO

from scribe.domain.job import Job, JobOptions, JobStatus
from scribe.domain.rendering import render
from scribe.domain.worker import WorkerState

from .ports import Clock, FileStore, JobRepository, WorkerRegistry


class JobNotFound(Exception):
    pass


class TranscriptNotReady(Exception):
    pass


class OriginalMissing(Exception):
    """The audio file is gone, so the job cannot be run again."""


class EmptyUpload(Exception):
    pass


@dataclass(frozen=True)
class WorkerView:
    state: WorkerState
    alive: bool


@dataclass(frozen=True)
class Health:
    database_ok: bool
    jobs: dict[str, int]
    workers: list[WorkerView]


class JobService:
    def __init__(
        self,
        *,
        jobs: JobRepository,
        files: FileStore,
        workers: WorkerRegistry,
        clock: Clock,
        new_id: Callable[[], str],
        max_attempts: int,
        worker_timeout: timedelta,
        database_ok: Callable[[], bool],
    ) -> None:
        self._jobs = jobs
        self._files = files
        self._workers = workers
        self._clock = clock
        self._new_id = new_id
        self._max_attempts = max_attempts
        self._worker_timeout = worker_timeout
        self._database_ok = database_ok

    def submit_upload(self, filename: str, content: BinaryIO, options: JobOptions | None = None) -> Job:
        job_id = self._new_id()
        stored_path, size = self._files.stage_upload(job_id, filename, content)
        job = Job.submit(
            job_id=job_id,
            filename=stored_path.rsplit("/", 1)[-1],
            source="upload",
            stored_path=stored_path,
            size_bytes=size,
            now=self._clock.now(),
            options=options,
            max_attempts=self._max_attempts,
        )
        try:
            if size == 0:
                raise EmptyUpload("the uploaded file is empty")
            self._jobs.add(job)
        except Exception:
            self._files.discard(job)
            raise
        return job

    def list(self, status: JobStatus | None = None, limit: int = 100, offset: int = 0) -> list[Job]:
        return self._jobs.list(status, limit, offset)

    def get(self, job_id: str) -> Job:
        return self._found(self._jobs.get(job_id))

    def transcript_text(self, job_id: str, fmt: str) -> str:
        """Raises ValueError for an unknown format."""
        job = self._found(self._jobs.get(job_id, with_transcript=True))
        if job.status is not JobStatus.DONE or job.transcript is None:
            raise TranscriptNotReady(f"job is {job.status}")
        return render(job.transcript, fmt, job.speaker_names)

    def retry(self, job_id: str) -> Job:
        job = self.get(job_id)
        if not self._files.exists(job.stored_path):
            raise OriginalMissing("the original audio file is no longer available")
        return self._found(self._jobs.update(job_id, lambda j: j.retry(self._clock.now())))

    def cancel(self, job_id: str) -> Job:
        return self._found(self._jobs.update(job_id, lambda j: j.cancel(self._clock.now())))

    def delete(self, job_id: str) -> None:
        """Forget the job and its staged file. Transcripts and archived
        originals stay on disk."""
        job = self._found(self._jobs.delete(job_id))
        self._files.discard(job)

    def rename_speakers(self, job_id: str, names: dict[str, str]) -> Job:
        self._found(self._jobs.update(job_id, lambda j: j.rename_speakers(names)))
        job = self._found(self._jobs.get(job_id, with_transcript=True))
        transcript = job.transcript
        if job.status is JobStatus.DONE and transcript is not None:
            self._files.rewrite_outputs(job, lambda fmt: render(transcript, fmt, job.speaker_names))
        return job

    def health(self) -> Health:
        database_ok = self._database_ok()
        if not database_ok:
            return Health(False, {}, [])
        now = self._clock.now()
        workers = [
            WorkerView(state, alive=now - state.heartbeat_at <= self._worker_timeout)
            for state in self._workers.list()
        ]
        return Health(True, self._jobs.counts(), workers)

    @staticmethod
    def _found(job: Job | None) -> Job:
        if job is None:
            raise JobNotFound()
        return job
