"""Use case: take the next job from the queue and turn it into a transcript."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from scribe.domain.job import Job, JobStatus, NotOwner, RetryPolicy
from scribe.domain.rendering import render
from scribe.domain.transcript import Transcript, build_transcript

from .ports import (
    AudioDecoder,
    Clock,
    Diarizer,
    FileStore,
    JobRepository,
    Progress,
    SpeechRecognizer,
    UnreadableAudio,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Engines:
    """The loaded speech models. ``diarizer`` is None when speaker
    identification is turned off."""

    decoder: AudioDecoder
    recognizer: SpeechRecognizer
    diarizer: Diarizer | None
    device: str = ""
    speech_model: str = ""
    speaker_model: str = ""


class _Abandon(Exception):
    """Stop working on the current job: we were asked to stop, or lost it."""


class JobProcessor:
    def __init__(
        self,
        *,
        worker_id: str,
        jobs: JobRepository,
        files: FileStore,
        engines: Engines,
        clock: Clock,
        policy: RetryPolicy,
        output_formats: tuple[str, ...],
        default_language: str | None,
        heartbeat: timedelta,
    ) -> None:
        self._worker_id = worker_id
        self._jobs = jobs
        self._files = files
        self._engines = engines
        self._clock = clock
        self._policy = policy
        self._output_formats = output_formats
        self._default_language = default_language
        self._heartbeat = heartbeat
        self._stop_requested = False
        self._current: str | None = None
        self._lost = False
        self._renewed_at: datetime = clock.now()

    def request_stop(self) -> None:
        """Give the current job back to the queue at the next opportunity."""
        self._stop_requested = True

    def keep_alive(self) -> None:
        """Renew the lease on the current job. Meant to be called from a timer
        thread, so the lease survives long model calls that report no progress."""
        job_id = self._current
        if job_id is None:
            return
        try:
            self._renew(job_id)
        except NotOwner:
            self._lost = True

    def process_next(self) -> Job | None:
        """Process one job. Returns it in its new state, or None if the queue
        had nothing to do."""
        job = self._jobs.claim_next(self._worker_id, self._clock.now())
        if job is None:
            return None
        log.info(
            "job %s: started %s (attempt %d of %d)", job.id, job.filename, job.attempts, job.max_attempts
        )
        self._current, self._lost, self._renewed_at = job.id, False, self._clock.now()
        try:
            transcript = self._transcribe(job)
            self._enter(job, "writing", 0.97)
            self._finish(job, transcript)
        except _Abandon:
            self._abandon(job)
        except NotOwner:
            log.info("job %s: no longer ours; result discarded", job.id)
        except UnreadableAudio as exc:
            self._fail(job, str(exc), retryable=False)
        except Exception as exc:
            log.exception("job %s: attempt failed", job.id)
            self._fail(job, str(exc) or type(exc).__name__, retryable=True)
        finally:
            self._current = None
        return self._jobs.get(job.id)

    # --------------------------------------------------------------- steps

    def _transcribe(self, job: Job) -> Transcript:
        diarizer = self._engines.diarizer if job.options.diarize is not False else None
        recognition_share = 0.6 if diarizer else 0.9

        self._enter(job, "decoding", 0.0)
        audio = self._engines.decoder.decode(self._files.local_path(job.stored_path))

        self._enter(job, "transcribing", 0.05)
        recognition = self._engines.recognizer.recognize(
            audio,
            job.options.language or self._default_language,
            self._progress(job, 0.05, 0.05 + recognition_share),
        )
        words = list(recognition.words)

        turns = None
        if diarizer and words:
            self._enter(job, "identifying speakers", 0.05 + recognition_share)
            turns = diarizer.diarize(audio, job.options, self._progress(job, 0.05 + recognition_share, 0.95))

        return build_transcript(
            words,
            turns,
            file=job.filename,
            language=recognition.language,
            duration=audio.duration,
            created=self._clock.now().isoformat(timespec="seconds"),
        )

    def _finish(self, job: Job, transcript: Transcript) -> None:
        documents = {fmt: render(transcript, fmt, job.speaker_names) for fmt in self._output_formats}
        outputs = self._files.write_outputs(job, documents)
        self._update(
            job.id,
            lambda j: j.complete(
                self._worker_id,
                self._clock.now(),
                outputs=outputs,
                stored_path=j.stored_path,
                duration_s=transcript.duration,
                language=transcript.language,
                num_speakers=len(transcript.speakers),
                transcript=transcript,
            ),
        )
        log.info("job %s: done, %d speaker(s), %s", job.id, len(transcript.speakers), ", ".join(outputs))
        # The job is safely recorded as done before the original is moved, so
        # a crash in between can never lose the file.
        stored_path = self._files.archive_original(job)
        self._jobs.update(job.id, lambda j: j.relocate(stored_path))

    def _abandon(self, job: Job) -> None:
        if self._lost:
            log.info("job %s: cancelled or taken over; stopping", job.id)
            return
        log.info("job %s: returned to the queue (worker stopping)", job.id)
        with contextlib.suppress(NotOwner):
            self._update(job.id, lambda j: j.release(self._worker_id, self._clock.now()))

    def _fail(self, job: Job, error: str, *, retryable: bool) -> None:
        try:
            failed = self._update(
                job.id,
                lambda j: j.fail(
                    self._worker_id, self._clock.now(), error, retryable=retryable, policy=self._policy
                ),
            )
        except NotOwner:
            return
        if failed.status is JobStatus.FAILED:
            log.error("job %s: failed for good: %s", job.id, error)
            stored_path = self._files.fail_original(failed, error)
            self._jobs.update(job.id, lambda j: j.relocate(stored_path))
        else:
            log.warning("job %s: will be retried after %s: %s", job.id, failed.run_after.isoformat(), error)

    # -------------------------------------------------------------- lease

    def _enter(self, job: Job, stage: str, progress: float) -> None:
        """Start a new stage; always confirms we still hold the job."""
        self._check()
        try:
            self._renew(job.id, stage, progress)
        except NotOwner:
            self._lost = True
            raise _Abandon() from None

    def _progress(self, job: Job, low: float, high: float) -> Progress:
        def report(fraction: float) -> None:
            self._check()
            if self._clock.now() - self._renewed_at >= self._heartbeat:
                try:
                    self._renew(job.id, None, low + (high - low) * min(max(fraction, 0.0), 1.0))
                except NotOwner:
                    self._lost = True
                    raise _Abandon() from None

        return report

    def _check(self) -> None:
        if self._stop_requested or self._lost:
            raise _Abandon()

    def _renew(self, job_id: str, stage: str | None = None, progress: float | None = None) -> None:
        self._update(job_id, lambda j: j.renew(self._worker_id, self._clock.now(), stage, progress))
        self._renewed_at = self._clock.now()

    def _update(self, job_id: str, mutate: Callable[[Job], None]) -> Job:
        job = self._jobs.update(job_id, mutate)
        if job is None:  # deleted while we were working on it
            raise NotOwner(f"job {job_id} no longer exists")
        return job
