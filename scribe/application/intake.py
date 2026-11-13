"""Use case: turn files that appear in the inbox into queued jobs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from scribe.domain.job import Job

from .ports import Clock, FileStore, InboxFile, JobRepository

log = logging.getLogger(__name__)

# Left behind by browsers and copy tools while a file is still arriving.
TEMPORARY_SUFFIXES = (".part", ".partial", ".tmp", ".crdownload", ".download", ".filepart")


@dataclass(frozen=True)
class _Sighting:
    size: int
    modified: float
    since: datetime


class InboxWatcher:
    """Call ``scan`` regularly. A file is queued once it has looked the same
    (size and modification time) for ``stable_seconds``, so files that are
    still being copied are left alone."""

    def __init__(
        self,
        *,
        files: FileStore,
        jobs: JobRepository,
        clock: Clock,
        new_id: Callable[[], str],
        extensions: frozenset[str],
        stable_seconds: float,
        max_attempts: int,
    ) -> None:
        self._files = files
        self._jobs = jobs
        self._clock = clock
        self._new_id = new_id
        self._extensions = extensions
        self._stable_seconds = stable_seconds
        self._max_attempts = max_attempts
        self._seen: dict[str, _Sighting] = {}

    def scan(self) -> list[Job]:
        now = self._clock.now()
        present = {f.path: f for f in self._files.inbox_files() if self._is_audio(f.path)}
        self._seen = {path: s for path, s in self._seen.items() if path in present}
        queued = []
        for path, file in present.items():
            seen = self._seen.get(path)
            if seen is None or (seen.size, seen.modified) != (file.size, file.modified):
                self._seen[path] = _Sighting(file.size, file.modified, now)
                continue
            if file.size == 0 or (now - seen.since).total_seconds() < self._stable_seconds:
                continue
            job = self._enqueue(file, now)
            if job is not None:
                queued.append(job)
                del self._seen[path]
        return queued

    def _is_audio(self, path: str) -> bool:
        parts = PurePosixPath(path).parts
        name = parts[-1]
        if any(p.startswith(".") for p in parts) or name.startswith("~"):
            return False
        if name.lower().endswith(TEMPORARY_SUFFIXES) or "." not in name:
            return False
        return name.rsplit(".", 1)[1].lower() in self._extensions

    def _enqueue(self, file: InboxFile, now: datetime) -> Job | None:
        job_id = self._new_id()
        try:
            stored_path = self._files.stage_from_inbox(file.path, job_id)
        except OSError as exc:  # locked or already gone; look again next scan
            log.warning("cannot take %s from the inbox yet: %s", file.path, exc)
            return None
        rel_dir = PurePosixPath(file.path).parent.as_posix()
        job = Job.submit(
            job_id=job_id,
            filename=PurePosixPath(file.path).name,
            source="folder",
            stored_path=stored_path,
            size_bytes=file.size,
            now=now,
            rel_dir="" if rel_dir == "." else rel_dir,
            max_attempts=self._max_attempts,
        )
        try:
            self._jobs.add(job)
        except Exception:
            self._files.return_to_inbox(stored_path, file.path)
            raise
        log.info("queued %s as job %s", file.path, job_id)
        return job
