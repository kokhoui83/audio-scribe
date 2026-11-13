"""In-memory JobRepository and WorkerRegistry.

Used by the test suite (it passes the same contract tests as the PostgreSQL
adapter) and handy for experiments; nothing survives a restart.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from scribe.domain.job import Job, JobStatus
from scribe.domain.worker import WorkerState


class InMemoryJobRepository:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()

    def add(self, job: Job) -> None:
        with self._lock:
            if job.id in self._jobs:
                raise ValueError(f"job {job.id} already exists")
            self._jobs[job.id] = copy.deepcopy(job)

    def get(self, job_id: str, with_transcript: bool = False) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else self._copy(job, with_transcript)

    def list(self, status: JobStatus | None = None, limit: int = 100, offset: int = 0) -> list[Job]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: (j.created_at, j.id), reverse=True)
            if status is not None:
                jobs = [j for j in jobs if j.status is status]
            return [self._copy(j, False) for j in jobs[offset : offset + limit]]

    def ids(self) -> set[str]:
        with self._lock:
            return set(self._jobs)

    def counts(self) -> dict[str, int]:
        with self._lock:
            result = {s.value: 0 for s in JobStatus}
            for job in self._jobs.values():
                result[job.status.value] += 1
            return result

    def claim_next(self, worker_id: str, now: datetime) -> Job | None:
        with self._lock:
            runnable = [j for j in self._jobs.values() if j.is_runnable(now)]
            if not runnable:
                return None
            job = min(runnable, key=lambda j: (j.created_at, j.id))
            job.start(worker_id, now)
            return self._copy(job, False)

    def update(self, job_id: str, mutate: Callable[[Job], None]) -> Job | None:
        with self._lock:
            stored = self._jobs.get(job_id)
            if stored is None:
                return None
            job = self._copy(stored, False)
            mutate(job)
            saved = copy.deepcopy(job)
            if saved.transcript is None:
                saved.transcript = stored.transcript
            self._jobs[job_id] = saved
            return job

    def stale_ids(self, heartbeat_before: datetime) -> list[str]:
        with self._lock:
            return sorted(
                j.id
                for j in self._jobs.values()
                if j.status is JobStatus.PROCESSING and j.heartbeat_at and j.heartbeat_at < heartbeat_before
            )

    def delete(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.pop(job_id, None)
            return None if job is None else self._copy(job, False)

    @staticmethod
    def _copy(job: Job, with_transcript: bool) -> Job:
        clone = copy.deepcopy(job)
        return clone if with_transcript else replace(clone, transcript=None)


class InMemoryWorkerRegistry:
    def __init__(self) -> None:
        self._workers: dict[str, WorkerState] = {}

    def report(self, state: WorkerState) -> None:
        self._workers[state.id] = state

    def remove(self, worker_id: str) -> None:
        self._workers.pop(worker_id, None)

    def list(self) -> list[WorkerState]:
        return [self._workers[k] for k in sorted(self._workers)]
