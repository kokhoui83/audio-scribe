"""Use case: a worker's life. Load the speech models, then process jobs; while
the models cannot be loaded, say why and leave the queue alone."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta

from scribe.domain.job import RetryPolicy
from scribe.domain.worker import ERROR, READY, WorkerState

from .ports import Clock, FileStore, JobRepository, WorkerRegistry
from .processing import Engines, JobProcessor

log = logging.getLogger(__name__)


class Worker:
    def __init__(
        self,
        *,
        worker_id: str,
        jobs: JobRepository,
        files: FileStore,
        registry: WorkerRegistry,
        clock: Clock,
        load_engines: Callable[[], Engines],
        policy: RetryPolicy,
        output_formats: tuple[str, ...],
        default_language: str | None,
        heartbeat: timedelta,
    ) -> None:
        self._id = worker_id
        self._registry = registry
        self._clock = clock
        self._load_engines = load_engines
        self._make_processor = lambda engines: JobProcessor(
            worker_id=worker_id, jobs=jobs, files=files, engines=engines, clock=clock, policy=policy,
            output_formats=output_formats, default_language=default_language, heartbeat=heartbeat,
        )  # fmt: skip
        self._processor: JobProcessor | None = None
        self._engines: Engines | None = None
        self._stopping = False
        self._problem: str | None = None

    @property
    def ready(self) -> bool:
        return self._processor is not None

    def tick(self) -> bool:
        """Do one unit of work. Returns False when there was nothing to do
        (queue empty, models not loaded, or stopping) so the caller can wait."""
        if self._stopping:
            return False
        if self._processor is None and not self._load():
            return False
        self._report()
        return self._processor.process_next() is not None

    def keep_alive(self) -> None:
        """Call every few seconds from a timer thread."""
        if self._processor is not None:
            self._processor.keep_alive()
        self._report()

    def request_stop(self) -> None:
        self._stopping = True
        if self._processor is not None:
            self._processor.request_stop()

    def sign_off(self) -> None:
        self._registry.remove(self._id)

    def _load(self) -> bool:
        try:
            self._engines = self._load_engines()
        except Exception as exc:
            self._problem = str(exc) or type(exc).__name__
            log.error("cannot load the speech models: %s", self._problem)
            self._report()
            return False
        self._problem = None
        self._processor = self._make_processor(self._engines)
        return True

    def _report(self) -> None:
        engines = self._engines
        self._registry.report(
            WorkerState(
                id=self._id,
                status=ERROR if self._problem else READY,
                heartbeat_at=self._clock.now(),
                message=self._problem,
                device=engines.device if engines else "",
                speech_model=engines.speech_model if engines else "",
                speaker_model=engines.speaker_model if engines else "",
            )
        )
