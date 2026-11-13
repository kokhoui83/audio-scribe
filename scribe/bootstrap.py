"""Composition root: the only place that knows which adapter implements
which port. Entrypoints call these factories; nothing else imports adapters."""

from __future__ import annotations

import os
import socket
import uuid
from datetime import timedelta
from functools import cache

from scribe.adapters.clock import SystemClock
from scribe.adapters.filesystem import LocalFileStore
from scribe.adapters.postgres import Database, PostgresJobRepository, PostgresWorkerRegistry
from scribe.application.intake import InboxWatcher
from scribe.application.maintenance import Housekeeper
from scribe.application.management import JobService
from scribe.application.processing import Engines
from scribe.application.worker import Worker
from scribe.domain.job import RetryPolicy
from scribe.settings import Settings

# A worker that has not reported for this long is shown as not running.
WORKER_TIMEOUT = timedelta(seconds=45)


@cache
def settings() -> Settings:
    return Settings.from_env(os.environ)


@cache
def database() -> Database:
    db = Database(settings().database_url)
    db.migrate()
    return db


@cache
def files() -> LocalFileStore:
    return LocalFileStore(settings().data_dir, archive_originals=settings().archive_originals)


def _new_id() -> str:
    return str(uuid.uuid4())


def job_service() -> JobService:
    return JobService(
        jobs=PostgresJobRepository(database()),
        files=files(),
        workers=PostgresWorkerRegistry(database()),
        clock=SystemClock(),
        new_id=_new_id,
        max_attempts=settings().max_attempts,
        worker_timeout=WORKER_TIMEOUT,
        database_ok=database().ping,
    )


def inbox_watcher() -> InboxWatcher:
    s = settings()
    return InboxWatcher(
        files=files(),
        jobs=PostgresJobRepository(database()),
        clock=SystemClock(),
        new_id=_new_id,
        extensions=s.audio_extensions,
        stable_seconds=s.stable_seconds,
        max_attempts=s.max_attempts,
    )


def housekeeper() -> Housekeeper:
    return Housekeeper(
        jobs=PostgresJobRepository(database()),
        files=files(),
        clock=SystemClock(),
        lease=timedelta(seconds=settings().lease_seconds),
    )


def load_engines() -> Engines:
    """Load the speech models. Imported lazily: only the worker image has them."""
    from scribe.adapters import pyannote, whisper, whispercpp
    from scribe.adapters.ffmpeg import FfmpegDecoder

    s = settings()
    if s.speech_engine == "whisper-cpp":
        recognizer = whispercpp.load(
            binary=s.whisper_cpp_binary,
            model=s.whisper_model,
            device=s.device,
            gpu_index=s.gpu_index,
            cpu_threads=s.cpu_threads,
            cache_dir=s.models_dir / "whisper-cpp",
        )
    else:
        recognizer = whisper.load(
            model=s.whisper_model,
            device=s.device,
            compute_type=s.compute_type,
            batch_size=s.batch_size,
            cpu_threads=s.cpu_threads,
            cache_dir=s.models_dir / "whisper",
        )
    diarizer = None
    if s.diarize:
        diarizer = pyannote.load(model=s.diarization_model, token=s.hf_token, device=s.diarization_device)
    return Engines(
        decoder=FfmpegDecoder(),
        recognizer=recognizer,
        diarizer=diarizer,
        device=s.device,
        speech_model=s.whisper_model,
        speaker_model=s.diarization_model if s.diarize else "off",
    )


def worker() -> Worker:
    s = settings()
    return Worker(
        worker_id=socket.gethostname(),
        jobs=PostgresJobRepository(database()),
        files=files(),
        registry=PostgresWorkerRegistry(database()),
        clock=SystemClock(),
        load_engines=load_engines,
        policy=RetryPolicy(max_attempts=s.max_attempts, backoff_seconds=s.retry_backoff_seconds),
        output_formats=s.output_formats,
        default_language=s.default_language,
        heartbeat=timedelta(seconds=s.heartbeat_seconds),
    )
