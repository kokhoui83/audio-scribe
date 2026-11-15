"""The world the feature steps act on: real use cases and a real data folder
(in a temp directory), with an in-memory queue, a fake clock and fake models."""

from __future__ import annotations

import io
import uuid
from datetime import timedelta
from functools import cached_property
from pathlib import Path

import pytest

from scribe.adapters.filesystem import LocalFileStore
from scribe.adapters.memory import InMemoryJobRepository, InMemoryWorkerRegistry
from scribe.application.intake import InboxWatcher
from scribe.application.maintenance import Housekeeper
from scribe.application.management import JobService
from scribe.application.worker import Engines, Worker
from scribe.domain.job import Job, RecordingPolicy, RetryPolicy
from tests.fakes import FakeClock, FakeDecoder, FakeDiarizer, FakeRecognizer, WorkerCrash

STABLE_SECONDS = 5
LEASE_SECONDS = 120
EXTENSIONS = frozenset({"mp3", "wav", "m4a", "flac", "ogg", "opus", "aac", "wma", "mp4", "webm"})


class World:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.clock = FakeClock()
        self.jobs = InMemoryJobRepository()
        self.registry = InMemoryWorkerRegistry()
        self.recognizer = FakeRecognizer()
        self.diarizer = FakeDiarizer()
        self.policy = RetryPolicy(max_attempts=3, backoff_seconds=30)
        self.recording = RecordingPolicy()
        self.last_piece: tuple[int, bytes] | None = None
        # Settings a scenario may change before the components are first used.
        self.output_formats: tuple[str, ...] = ("md",)
        self.archive_originals = True
        self.diarize = True
        self.default_language: str | None = None
        self.engines_error: str | None = None
        self.response: str | None = None
        self.refusal: Exception | None = None

    # ---------------------------------------------------------- components

    @cached_property
    def files(self) -> LocalFileStore:
        return LocalFileStore(self.data_dir, archive_originals=self.archive_originals)

    @cached_property
    def watcher(self) -> InboxWatcher:
        return InboxWatcher(
            files=self.files,
            jobs=self.jobs,
            clock=self.clock,
            new_id=lambda: str(uuid.uuid4()),
            extensions=EXTENSIONS,
            stable_seconds=STABLE_SECONDS,
            max_attempts=self.policy.max_attempts,
        )

    @cached_property
    def housekeeper(self) -> Housekeeper:
        return Housekeeper(
            jobs=self.jobs, files=self.files, clock=self.clock, lease=timedelta(seconds=LEASE_SECONDS)
        )

    @cached_property
    def service(self) -> JobService:
        return JobService(
            jobs=self.jobs,
            files=self.files,
            workers=self.registry,
            clock=self.clock,
            new_id=lambda: str(uuid.uuid4()),
            max_attempts=self.policy.max_attempts,
            worker_timeout=timedelta(seconds=45),
            database_ok=lambda: True,
        )

    @cached_property
    def worker(self) -> Worker:
        return self.make_worker("worker-1", self.recognizer)

    def make_worker(self, worker_id: str, recognizer) -> Worker:
        def load_engines() -> Engines:
            if self.engines_error:
                raise RuntimeError(self.engines_error)
            return Engines(
                decoder=FakeDecoder(),
                recognizer=recognizer,
                diarizer=self.diarizer if self.diarize else None,
                device="cpu",
                speech_model="fake",
                speaker_model="fake" if self.diarize else "off",
            )

        return Worker(
            worker_id=worker_id,
            jobs=self.jobs,
            files=self.files,
            registry=self.registry,
            clock=self.clock,
            load_engines=load_engines,
            policy=self.policy,
            output_formats=self.output_formats,
            default_language=self.default_language,
            heartbeat=timedelta(seconds=10),
            recording=self.recording,
        )

    # ------------------------------------------------------------- helpers

    def drop(self, name: str, content: str) -> Path:
        path = self.data_dir / "inbox" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def settle_inbox(self) -> None:
        self.watcher.scan()
        self.clock.advance(STABLE_SECONDS)
        self.watcher.scan()

    def queue_recording(self, name: str, content: str) -> None:
        self.drop(name, content)
        self.settle_inbox()

    def send_audio(self, name: str, content: str, skip: int = 0) -> None:
        """Send the next piece of a recording, as the web page does."""
        job = self.job(name)
        self.last_piece = (job.size_bytes + skip, content.encode())
        self.send_again(name)

    def send_again(self, name: str) -> None:
        offset, piece = self.last_piece
        self.service.add_audio(self.job(name).id, offset, io.BytesIO(piece))

    def work(self, limit: int = 50) -> None:
        for _ in range(limit):
            if not self.worker.tick():
                return
        raise AssertionError("the worker never ran out of work")

    def crash_worker_on(self, name: str) -> None:
        doomed = self.make_worker(f"crashed-{uuid.uuid4().hex[:6]}", FakeRecognizer(crash=True))
        with pytest.raises(WorkerCrash):
            doomed.tick()
        assert self.job(name).status == "processing"

    def job(self, name: str) -> Job:
        matches = [j for j in self.jobs.list() if j.filename == Path(name).name]
        assert matches, f"no job for {name}"
        return matches[0]  # newest

    def folder(self, which: str) -> list[str]:
        root = (
            self.data_dir
            / {
                "inbox": "inbox",
                "output": "output",
                "archive": "archive",
                "failed": "failed",
                "staging": ".work",
            }[which]
        )
        return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())

    def attempt(self, action) -> None:
        """Run a user action, remembering a refusal instead of failing the step."""
        self.refusal = None
        try:
            self.response = action()
        except Exception as exc:
            self.refusal = exc


@pytest.fixture
def world(tmp_path) -> World:
    return World(tmp_path)
