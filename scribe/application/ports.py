"""Interfaces the use cases need from the outside world.

Use cases depend only on these; the adapters package implements them.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Protocol

from scribe.domain.job import Job, JobOptions, JobStatus
from scribe.domain.transcript import SpeakerTurn, Word
from scribe.domain.worker import WorkerState

# Called with a fraction 0..1. May raise to abort the running step.
Progress = Callable[[float], None]


class Clock(Protocol):
    def now(self) -> datetime: ...


class JobRepository(Protocol):
    """Durable job store that doubles as the work queue."""

    def add(self, job: Job) -> None: ...

    def get(self, job_id: str, with_transcript: bool = False) -> Job | None: ...

    def list(self, status: JobStatus | None = None, limit: int = 100, offset: int = 0) -> list[Job]:
        """Newest first, without transcripts."""
        ...

    def ids(self) -> set[str]: ...

    def counts(self) -> dict[str, int]:
        """Number of jobs per status (every status present)."""
        ...

    def claim_next(self, worker_id: str, now: datetime) -> Job | None:
        """Atomically start the oldest runnable job. No two callers ever get
        the same job."""
        ...

    def update(self, job_id: str, mutate: Callable[[Job], None]) -> Job | None:
        """Atomically load the job, apply ``mutate`` and save it. Returns None
        if the job does not exist. If ``mutate`` raises, nothing is saved and
        the exception propagates."""
        ...

    def stale_ids(self, heartbeat_before: datetime) -> list[str]:
        """Processing jobs whose last heartbeat is older than the given time."""
        ...

    def delete(self, job_id: str) -> Job | None: ...


class WorkerRegistry(Protocol):
    def report(self, state: WorkerState) -> None: ...

    def remove(self, worker_id: str) -> None: ...

    def list(self) -> list[WorkerState]: ...


@dataclass(frozen=True)
class InboxFile:
    path: str  # relative to the inbox
    size: int
    modified: float


class FileStore(Protocol):
    """The data folder: inbox, staging area, outputs, archive, failed."""

    def inbox_files(self) -> list[InboxFile]: ...

    def stage_from_inbox(self, inbox_path: str, job_id: str) -> str:
        """Move a file out of the inbox; returns its stored path."""
        ...

    def return_to_inbox(self, stored_path: str, inbox_path: str) -> None: ...

    def stage_upload(self, job_id: str, filename: str, content: BinaryIO) -> tuple[str, int]:
        """Save an upload; returns (stored path, size in bytes)."""
        ...

    def local_path(self, stored_path: str) -> Path: ...

    def exists(self, stored_path: str) -> bool: ...

    def write_outputs(self, job: Job, documents: dict[str, str]) -> list[str]:
        """Write one document per format; returns the paths written."""
        ...

    def rewrite_outputs(self, job: Job, render: Callable[[str], str]) -> None:
        """Re-render the job's existing output files; ``render`` maps a format to text."""
        ...

    def archive_original(self, job: Job) -> str:
        """Called after success; returns the new stored path."""
        ...

    def fail_original(self, job: Job, error: str) -> str:
        """Called after final failure; returns the new stored path."""
        ...

    def discard(self, job: Job) -> None:
        """Remove whatever is still staged for the job."""
        ...

    def recover_orphans(self, known_job_ids: set[str]) -> list[str]:
        """Return staged files that belong to no job to the inbox."""
        ...


class UnreadableAudio(Exception):
    """The file is not something audio can be decoded from. Not worth retrying."""


class Audio(Protocol):
    """Decoded audio; opaque to the use cases apart from its length."""

    @property
    def duration(self) -> float: ...


@dataclass(frozen=True)
class Recognition:
    language: str | None
    words: Sequence[Word]


class AudioDecoder(Protocol):
    def decode(self, path: Path) -> Audio:
        """Raises UnreadableAudio."""
        ...


class SpeechRecognizer(Protocol):
    def recognize(self, audio: Audio, language: str | None, progress: Progress) -> Recognition: ...


class Diarizer(Protocol):
    def diarize(self, audio: Audio, options: JobOptions, progress: Progress) -> Sequence[SpeakerTurn]: ...
