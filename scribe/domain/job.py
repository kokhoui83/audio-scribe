"""The Job entity: one audio file on its way to a transcript.

All rules about what may happen to a job, and when, live here. Persistence
adapters only load a job, call one of these methods, and save it again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from .transcript import Transcript


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobError(Exception):
    pass


class InvalidTransition(JobError):
    """The job is not in a state that allows the requested action."""


class NotOwner(JobError):
    """The worker no longer holds this job (cancelled, deleted or re-queued)."""


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    backoff_seconds: float = 30.0

    def delay(self, attempt: int) -> timedelta:
        """Wait before the retry that follows failed attempt number ``attempt``."""
        return timedelta(seconds=self.backoff_seconds * 2 ** max(attempt - 1, 0))


@dataclass(frozen=True)
class JobOptions:
    """Per-file wishes. ``None`` means "use the system default"."""

    language: str | None = None
    diarize: bool | None = None
    num_speakers: int | None = None
    min_speakers: int | None = None
    max_speakers: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> JobOptions:
        data = data or {}
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if data.get(k) is not None})


@dataclass
class Job:
    id: str
    filename: str
    source: str  # "folder" or "upload"
    stored_path: str  # relative to the data folder
    size_bytes: int
    created_at: datetime
    run_after: datetime
    rel_dir: str = ""
    options: JobOptions = field(default_factory=JobOptions)
    max_attempts: int = 3
    status: JobStatus = JobStatus.QUEUED
    stage: str | None = None
    progress: float = 0.0
    attempts: int = 0
    locked_by: str | None = None
    heartbeat_at: datetime | None = None
    error: str | None = None
    speaker_names: dict[str, str] = field(default_factory=dict)
    outputs: list[str] = field(default_factory=list)
    duration_s: float | None = None
    language: str | None = None
    num_speakers: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Only loaded when asked for; None in listings.
    transcript: Transcript | None = None

    @classmethod
    def submit(
        cls,
        *,
        job_id: str,
        filename: str,
        source: str,
        stored_path: str,
        size_bytes: int,
        now: datetime,
        rel_dir: str = "",
        options: JobOptions | None = None,
        max_attempts: int = 3,
    ) -> Job:
        return cls(
            id=job_id,
            filename=filename,
            source=source,
            stored_path=stored_path,
            size_bytes=size_bytes,
            created_at=now,
            run_after=now,
            rel_dir=rel_dir,
            options=options or JobOptions(),
            max_attempts=max_attempts,
        )

    # ------------------------------------------------------------ queries

    def is_runnable(self, now: datetime) -> bool:
        return self.status is JobStatus.QUEUED and self.run_after <= now

    def lease_expired(self, now: datetime, lease: timedelta) -> bool:
        return (
            self.status is JobStatus.PROCESSING
            and self.heartbeat_at is not None
            and now - self.heartbeat_at > lease
        )

    def is_owned_by(self, worker_id: str) -> bool:
        return self.status is JobStatus.PROCESSING and self.locked_by == worker_id

    # ------------------------------------------------------- worker actions

    def start(self, worker_id: str, now: datetime) -> None:
        self._require(JobStatus.QUEUED, action="start")
        self.status = JobStatus.PROCESSING
        self.locked_by = worker_id
        self.heartbeat_at = self.started_at = now
        self.finished_at = None
        self.attempts += 1
        self.stage, self.progress, self.error = "starting", 0.0, None

    def renew(
        self, worker_id: str, now: datetime, stage: str | None = None, progress: float | None = None
    ) -> None:
        self._require_owner(worker_id)
        self.heartbeat_at = now
        if stage is not None:
            self.stage = stage
        if progress is not None:
            self.progress = min(max(progress, 0.0), 1.0)

    def complete(
        self,
        worker_id: str,
        now: datetime,
        *,
        outputs: list[str],
        stored_path: str,
        duration_s: float | None,
        language: str | None,
        num_speakers: int,
        transcript: Transcript | None = None,
    ) -> None:
        self._require_owner(worker_id)
        self.status = JobStatus.DONE
        self.outputs, self.stored_path = list(outputs), stored_path
        self.duration_s, self.language, self.num_speakers = duration_s, language, num_speakers
        self.transcript = transcript
        self.error = None
        self.progress = 1.0
        self._close(now)

    def fail(
        self, worker_id: str, now: datetime, error: str, *, retryable: bool, policy: RetryPolicy
    ) -> None:
        self._require_owner(worker_id)
        self.error = error
        if retryable and self.attempts < self.max_attempts:
            self._requeue(now + policy.delay(self.attempts))
        else:
            self.status = JobStatus.FAILED
            self._close(now)

    def release(self, worker_id: str, now: datetime) -> None:
        """Hand the job back untouched; the attempt does not count."""
        self._require_owner(worker_id)
        self.attempts = max(self.attempts - 1, 0)
        self._requeue(now)

    # ------------------------------------------------------ system actions

    def expire_lease(self, now: datetime) -> None:
        self._require(JobStatus.PROCESSING, action="expire the lease of")
        self.error = (
            "The worker stopped responding while processing this file "
            f"(attempt {self.attempts} of {self.max_attempts})."
        )
        if self.attempts < self.max_attempts:
            self._requeue(now)
        else:
            self.status = JobStatus.FAILED
            self._close(now)

    # ---------------------------------------------------- operator actions

    def cancel(self, now: datetime) -> None:
        self._require(JobStatus.QUEUED, JobStatus.PROCESSING, action="cancel")
        self.status = JobStatus.CANCELLED
        self._close(now)

    def retry(self, now: datetime) -> None:
        self._require(JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.DONE, action="retry")
        self.attempts = 0
        self.error = None
        self.finished_at = None
        self._requeue(now)

    def relocate(self, stored_path: str) -> None:
        """The original file was moved (archived, or set aside as failed)."""
        self.stored_path = stored_path

    def rename_speakers(self, names: dict[str, str]) -> None:
        self.speaker_names = {k: v.strip() for k, v in names.items() if v and v.strip()}

    # ------------------------------------------------------------ helpers

    def _requeue(self, run_after: datetime) -> None:
        self.status = JobStatus.QUEUED
        self.run_after = run_after
        self.locked_by = self.stage = None
        self.progress = 0.0

    def _close(self, now: datetime) -> None:
        self.locked_by = self.stage = None
        self.finished_at = now

    def _require(self, *allowed: JobStatus, action: str) -> None:
        if self.status not in allowed:
            raise InvalidTransition(f"cannot {action} a job that is {self.status}")

    def _require_owner(self, worker_id: str) -> None:
        if not self.is_owned_by(worker_id):
            raise NotOwner(f"job {self.id} is not held by {worker_id}")
