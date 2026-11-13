"""Use case: keep the queue healthy when workers die or the system restarts."""

from __future__ import annotations

import logging
from datetime import timedelta

from scribe.domain.job import Job, JobStatus

from .ports import Clock, FileStore, JobRepository

log = logging.getLogger(__name__)


class Housekeeper:
    def __init__(self, *, jobs: JobRepository, files: FileStore, clock: Clock, lease: timedelta) -> None:
        self._jobs = jobs
        self._files = files
        self._clock = clock
        self._lease = lease

    def reap(self) -> list[Job]:
        """Take back jobs whose worker stopped renewing its lease: re-queue
        them, or fail them once they are out of attempts."""
        now = self._clock.now()
        reaped = []
        for job_id in self._jobs.stale_ids(now - self._lease):
            expired = False

            def expire(job: Job) -> None:
                nonlocal expired
                # Checked again under the row lock: the worker may have
                # renewed or finished since the list was read.
                if job.lease_expired(now, self._lease):
                    job.expire_lease(now)
                    expired = True

            job = self._jobs.update(job_id, expire)
            if job is None or not expired:
                continue
            log.warning("job %s (%s): worker stopped responding -> %s", job.id, job.filename, job.status)
            if job.status is JobStatus.FAILED:
                stored_path = self._files.fail_original(job, job.error or "failed")
                self._jobs.update(job.id, lambda j, path=stored_path: j.relocate(path))
            reaped.append(job)
        return reaped

    def recover_orphans(self) -> list[str]:
        """Files that left the inbox but never became a job go back to it."""
        recovered = self._files.recover_orphans(self._jobs.ids())
        for name in recovered:
            log.warning("%s was staged without a job; returned to the inbox", name)
        return recovered
