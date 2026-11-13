"""PostgreSQL JobRepository and WorkerRegistry.

The ``jobs`` table is both the record of every job and the queue. The SQL here
only loads, locks and saves rows; what a state change means is decided by the
Job entity. Two mechanisms make it safe with several workers:

* ``claim_next`` selects with ``FOR UPDATE SKIP LOCKED``, so concurrent
  workers each lock a different row and never wait for each other;
* ``update`` locks the row for the duration of load -> mutate -> save.
"""

from __future__ import annotations

import builtins
import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from scribe.domain.draft import Draft
from scribe.domain.job import Job, JobOptions, JobStatus
from scribe.domain.transcript import Transcript
from scribe.domain.worker import WorkerState

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            text PRIMARY KEY,
    filename      text NOT NULL,
    source        text NOT NULL,
    stored_path   text NOT NULL,
    size_bytes    bigint NOT NULL,
    created_at    timestamptz NOT NULL,
    run_after     timestamptz NOT NULL,
    rel_dir       text NOT NULL,
    options       jsonb NOT NULL,
    max_attempts  int NOT NULL,
    status        text NOT NULL,
    stage         text,
    progress      double precision NOT NULL,
    attempts      int NOT NULL,
    locked_by     text,
    heartbeat_at  timestamptz,
    error         text,
    speaker_names jsonb NOT NULL,
    outputs       jsonb NOT NULL,
    duration_s    double precision,
    language      text,
    num_speakers  int,
    started_at    timestamptz,
    finished_at   timestamptz,
    transcript    jsonb
);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS audio_complete boolean NOT NULL DEFAULT true;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS audio_at timestamptz;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS draft jsonb;
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs (created_at, id) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS jobs_newest ON jobs (created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS jobs_leases ON jobs (heartbeat_at) WHERE status = 'processing';

CREATE TABLE IF NOT EXISTS workers (
    id            text PRIMARY KEY,
    status        text NOT NULL,
    heartbeat_at  timestamptz NOT NULL,
    message       text,
    device        text NOT NULL,
    speech_model  text NOT NULL,
    speaker_model text NOT NULL
);
"""

# Every job column except the (large) transcript and draft.
_COLUMNS = (
    "id", "filename", "source", "stored_path", "size_bytes", "created_at", "run_after", "rel_dir",
    "options", "max_attempts", "status", "stage", "progress", "attempts", "locked_by", "heartbeat_at",
    "error", "speaker_names", "outputs", "duration_s", "language", "num_speakers", "started_at",
    "finished_at", "audio_complete", "audio_at",
)  # fmt: skip
_SELECT = ", ".join(_COLUMNS)
_TEXTS = ", transcript, draft"
_MIGRATION_LOCK = 727001


class Database:
    """A small connection pool; every statement is its own transaction unless
    run inside ``transaction()``."""

    def __init__(self, url: str, max_connections: int = 8) -> None:
        self._pool = ConnectionPool(
            url,
            min_size=1,
            max_size=max_connections,
            kwargs={"autocommit": True, "row_factory": dict_row},
            open=False,
        )
        self._pool.open()

    def close(self) -> None:
        self._pool.close()

    def connection(self):
        return self._pool.connection()

    def execute(self, sql: str, params: Any = ()) -> None:
        with self._pool.connection() as conn:
            conn.execute(sql, params)

    def all(self, sql: str, params: Any = ()) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            return conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: Any = ()) -> dict[str, Any] | None:
        with self._pool.connection() as conn:
            return conn.execute(sql, params).fetchone()

    def migrate(self, wait_seconds: float = 120) -> None:
        """Create the schema, waiting for the database to accept connections.
        Safe to call from several processes at once."""
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                with self._pool.connection() as conn, conn.transaction():
                    conn.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK,))
                    conn.execute(SCHEMA)
                return
            except Exception as exc:
                if time.monotonic() > deadline:
                    raise
                log.info("waiting for the database: %s", exc)
                time.sleep(2)

    def ping(self) -> bool:
        try:
            return self.one("SELECT 1 AS ok") is not None
        except Exception:
            return False


def _job_from_row(row: dict[str, Any]) -> Job:
    data = {c: row[c] for c in _COLUMNS}
    data["options"] = JobOptions.from_dict(data["options"])
    data["status"] = JobStatus(data["status"])
    transcript, draft = row.get("transcript"), row.get("draft")
    return Job(
        **data,
        transcript=None if transcript is None else Transcript.from_dict(transcript),
        draft=None if draft is None else Draft.from_dict(draft),
    )


def _job_to_params(job: Job) -> dict[str, Any]:
    params = {c: getattr(job, c) for c in _COLUMNS}
    params["options"] = Jsonb(job.options.to_dict())
    params["status"] = job.status.value
    params["speaker_names"] = Jsonb(job.speaker_names)
    params["outputs"] = Jsonb(job.outputs)
    return params


class PostgresJobRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    def add(self, job: Job) -> None:
        placeholders = ", ".join(f"%({c})s" for c in _COLUMNS)
        self._db.execute(f"INSERT INTO jobs ({_SELECT}) VALUES ({placeholders})", _job_to_params(job))

    def get(self, job_id: str, with_transcript: bool = False) -> Job | None:
        columns = _SELECT + (_TEXTS if with_transcript else "")
        row = self._db.one(f"SELECT {columns} FROM jobs WHERE id = %s", (job_id,))
        return None if row is None else _job_from_row(row)

    def list(self, status: JobStatus | None = None, limit: int = 100, offset: int = 0) -> builtins.list[Job]:
        where = "WHERE status = %(status)s" if status is not None else ""
        rows = self._db.all(
            f"SELECT {_SELECT} FROM jobs {where} ORDER BY created_at DESC, id DESC "
            "LIMIT %(limit)s OFFSET %(offset)s",
            {"status": status.value if status else None, "limit": limit, "offset": offset},
        )
        return [_job_from_row(r) for r in rows]

    def ids(self) -> set[str]:
        return {r["id"] for r in self._db.all("SELECT id FROM jobs")}

    def counts(self) -> dict[str, int]:
        result = {s.value: 0 for s in JobStatus}
        for row in self._db.all("SELECT status, count(*) AS n FROM jobs GROUP BY status"):
            result[row["status"]] = row["n"]
        return result

    def claim_next(self, worker_id: str, now: datetime) -> Job | None:
        with self._db.connection() as conn, conn.transaction():
            row = conn.execute(
                f"""SELECT {_SELECT} FROM jobs
                    WHERE status = 'queued' AND run_after <= %s
                    ORDER BY created_at, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1""",
                (now,),
            ).fetchone()
            if row is None:
                return None
            job = _job_from_row(row)
            job.start(worker_id, now)
            self._save(conn, job)
            return job

    def update(self, job_id: str, mutate: Callable[[Job], None]) -> Job | None:
        with self._db.connection() as conn, conn.transaction():
            row = conn.execute(f"SELECT {_SELECT} FROM jobs WHERE id = %s FOR UPDATE", (job_id,)).fetchone()
            if row is None:
                return None
            job = _job_from_row(row)
            mutate(job)
            self._save(conn, job)
            return job

    def stale_ids(self, heartbeat_before: datetime) -> builtins.list[str]:
        rows = self._db.all(
            "SELECT id FROM jobs WHERE status = 'processing' AND heartbeat_at < %s ORDER BY id",
            (heartbeat_before,),
        )
        return [r["id"] for r in rows]

    def delete(self, job_id: str) -> Job | None:
        row = self._db.one(f"DELETE FROM jobs WHERE id = %s RETURNING {_SELECT}", (job_id,))
        return None if row is None else _job_from_row(row)

    @staticmethod
    def _save(conn, job: Job) -> None:
        assignments = ", ".join(f"{c} = %({c})s" for c in _COLUMNS if c != "id")
        params = _job_to_params(job)
        if job.transcript is not None:
            assignments += ", transcript = %(transcript)s"
            params["transcript"] = Jsonb(job.transcript.to_dict())
        if job.draft is not None:
            assignments += ", draft = %(draft)s"
            params["draft"] = Jsonb(job.draft.to_dict())
        conn.execute(f"UPDATE jobs SET {assignments} WHERE id = %(id)s", params)


class PostgresWorkerRegistry:
    _COLUMNS = "id, status, heartbeat_at, message, device, speech_model, speaker_model"

    def __init__(self, database: Database) -> None:
        self._db = database

    def report(self, state: WorkerState) -> None:
        self._db.execute(
            f"""INSERT INTO workers ({self._COLUMNS})
                VALUES (%(id)s, %(status)s, %(heartbeat_at)s, %(message)s, %(device)s,
                        %(speech_model)s, %(speaker_model)s)
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status, heartbeat_at = EXCLUDED.heartbeat_at,
                    message = EXCLUDED.message, device = EXCLUDED.device,
                    speech_model = EXCLUDED.speech_model, speaker_model = EXCLUDED.speaker_model""",
            state.__dict__,
        )

    def remove(self, worker_id: str) -> None:
        self._db.execute("DELETE FROM workers WHERE id = %s", (worker_id,))

    def list(self) -> builtins.list[WorkerState]:
        return [WorkerState(**r) for r in self._db.all(f"SELECT {self._COLUMNS} FROM workers ORDER BY id")]
