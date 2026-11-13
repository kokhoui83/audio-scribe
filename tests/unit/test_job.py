"""The life of a job: queued -> processing -> done / failed / cancelled."""

from datetime import UTC, datetime, timedelta

import pytest

from scribe.domain.draft import Draft
from scribe.domain.job import RECORDING, InvalidTransition, Job, JobStatus, NotOwner, RetryPolicy
from scribe.domain.transcript import Word

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
POLICY = RetryPolicy(max_attempts=3, backoff_seconds=30)


def new_job(**overrides) -> Job:
    args = dict(
        job_id="j1",
        filename="call.mp3",
        source="folder",
        stored_path=".work/j1/call.mp3",
        size_bytes=10,
        now=T0,
        max_attempts=3,
    )
    args.update(overrides)
    return Job.submit(**args)


def started_job(worker="w1", **overrides) -> Job:
    job = new_job(**overrides)
    job.start(worker, T0)
    return job


class TestSubmitting:
    def test_a_new_job_is_queued_and_runnable_at_once(self):
        job = new_job()
        assert job.status is JobStatus.QUEUED
        assert job.attempts == 0
        assert job.is_runnable(T0)


class TestStarting:
    def test_starting_takes_the_lease_and_counts_an_attempt(self):
        job = started_job("w1")
        assert job.status is JobStatus.PROCESSING
        assert (job.locked_by, job.attempts, job.heartbeat_at, job.started_at) == ("w1", 1, T0, T0)

    def test_a_job_that_is_not_queued_cannot_be_started(self):
        job = started_job()
        with pytest.raises(InvalidTransition):
            job.start("w2", T0)

    def test_a_job_waiting_for_its_retry_delay_is_not_runnable(self):
        job = started_job()
        job.fail("w1", T0, "boom", retryable=True, policy=POLICY)
        assert not job.is_runnable(T0 + timedelta(seconds=29))
        assert job.is_runnable(T0 + timedelta(seconds=30))


class TestProgress:
    def test_renewing_updates_heartbeat_stage_and_progress(self):
        job = started_job()
        later = T0 + timedelta(seconds=10)
        job.renew("w1", later, stage="transcribing", progress=0.4)
        assert (job.heartbeat_at, job.stage, job.progress) == (later, "transcribing", 0.4)

    def test_only_the_owner_may_renew(self):
        job = started_job("w1")
        with pytest.raises(NotOwner):
            job.renew("w2", T0)

    def test_a_cancelled_job_is_no_longer_owned(self):
        job = started_job("w1")
        job.cancel(T0)
        with pytest.raises(NotOwner):
            job.renew("w1", T0)


class TestCompleting:
    def test_completing_stores_the_summary_and_releases_the_lease(self):
        job = started_job()
        done_at = T0 + timedelta(minutes=1)
        job.complete(
            "w1",
            done_at,
            outputs=["output/call.md"],
            stored_path="archive/call.mp3",
            duration_s=61.5,
            language="en",
            num_speakers=2,
        )
        assert job.status is JobStatus.DONE
        assert job.locked_by is None and job.progress == 1 and job.finished_at == done_at
        assert (job.outputs, job.stored_path) == (["output/call.md"], "archive/call.mp3")
        assert (job.duration_s, job.language, job.num_speakers) == (61.5, "en", 2)

    def test_a_worker_that_lost_the_job_cannot_complete_it(self):
        job = started_job("w1")
        with pytest.raises(NotOwner):
            job.complete("w2", T0, outputs=[], stored_path="x", duration_s=1, language="en", num_speakers=0)


class TestFailing:
    def test_a_transient_failure_is_requeued_with_exponential_backoff(self):
        job = started_job()
        job.fail("w1", T0, "out of memory", retryable=True, policy=POLICY)
        assert job.status is JobStatus.QUEUED and job.error == "out of memory"
        assert job.run_after == T0 + timedelta(seconds=30)

        job.start("w1", job.run_after)
        job.fail("w1", job.heartbeat_at, "again", retryable=True, policy=POLICY)
        assert job.run_after == job.heartbeat_at + timedelta(seconds=60)

    def test_the_last_attempt_fails_for_good(self):
        job = new_job(max_attempts=2)
        for _ in range(2):
            job.start("w1", job.run_after)
            job.fail("w1", job.run_after, "boom", retryable=True, policy=POLICY)
        assert job.status is JobStatus.FAILED and job.finished_at is not None

    def test_a_permanent_failure_is_not_retried(self):
        job = started_job()
        job.fail("w1", T0, "not an audio file", retryable=False, policy=POLICY)
        assert job.status is JobStatus.FAILED

    def test_only_the_owner_may_fail_a_job(self):
        job = started_job("w1")
        with pytest.raises(NotOwner):
            job.fail("w2", T0, "boom", retryable=True, policy=POLICY)


class TestLeases:
    LEASE = timedelta(seconds=120)

    def test_a_lease_expires_when_the_heartbeat_is_too_old(self):
        job = started_job()
        assert not job.lease_expired(T0 + timedelta(seconds=120), self.LEASE)
        assert job.lease_expired(T0 + timedelta(seconds=121), self.LEASE)

    def test_only_processing_jobs_have_a_lease(self):
        assert not new_job().lease_expired(T0 + timedelta(days=1), self.LEASE)

    def test_an_expired_lease_requeues_the_job_immediately(self):
        job = started_job()
        job.expire_lease(T0 + timedelta(minutes=5))
        assert job.status is JobStatus.QUEUED and job.locked_by is None
        assert job.is_runnable(T0 + timedelta(minutes=5))
        assert "stopped responding" in job.error

    def test_an_expired_lease_on_the_last_attempt_fails_the_job(self):
        job = started_job(max_attempts=1)
        job.expire_lease(T0 + timedelta(minutes=5))
        assert job.status is JobStatus.FAILED

    def test_releasing_requeues_without_spending_an_attempt(self):
        job = started_job()
        job.release("w1", T0)
        assert (job.status, job.attempts, job.locked_by) == (JobStatus.QUEUED, 0, None)


class TestOperatorActions:
    @pytest.mark.parametrize("make", [new_job, started_job])
    def test_queued_and_processing_jobs_can_be_cancelled(self, make):
        job = make()
        job.cancel(T0)
        assert job.status is JobStatus.CANCELLED and job.locked_by is None

    def test_a_finished_job_cannot_be_cancelled(self):
        job = started_job()
        job.fail("w1", T0, "x", retryable=False, policy=POLICY)
        with pytest.raises(InvalidTransition):
            job.cancel(T0)

    def test_retrying_resets_attempts_and_requeues(self):
        job = started_job()
        job.fail("w1", T0, "x", retryable=False, policy=POLICY)
        job.retry(T0)
        assert (job.status, job.attempts, job.error) == (JobStatus.QUEUED, 0, None)
        assert job.is_runnable(T0)

    def test_a_job_in_flight_cannot_be_retried(self):
        with pytest.raises(InvalidTransition):
            started_job().retry(T0)

    def test_relocating_records_where_the_original_now_lives(self):
        job = new_job()
        job.relocate("archive/call.mp3")
        assert job.stored_path == "archive/call.mp3"

    def test_speaker_names_are_trimmed_and_blank_ones_dropped(self):
        job = new_job()
        job.rename_speakers({"Speaker 1": "  Alice ", "Speaker 2": "  "})
        assert job.speaker_names == {"Speaker 1": "Alice"}


def new_recording(**overrides) -> Job:
    return new_job(filename="standup.webm", source=RECORDING, size_bytes=0, audio_complete=False, **overrides)


SOME_TEXT = Draft(position=4.0, language="en", words=(Word(0.0, 1.0, " Hello."),))


class TestRecording:
    IDLE = timedelta(seconds=120)

    def test_an_ordinary_job_has_all_its_audio_from_the_start(self):
        job = new_job()
        assert job.audio_complete and not job.is_recording

    def test_a_recording_is_queued_at_once_although_its_audio_is_still_arriving(self):
        job = new_recording()
        assert job.is_recording and not job.audio_complete
        assert job.is_runnable(T0) and job.audio_at == T0

    def test_arriving_audio_is_noted(self):
        job = new_recording()
        later = T0 + timedelta(seconds=5)
        job.receive_audio(later, size_bytes=4096)
        assert (job.size_bytes, job.audio_at) == (4096, later)

    def test_audio_is_also_accepted_while_a_worker_holds_the_job(self):
        job = new_recording()
        job.start("w1", T0)
        job.receive_audio(T0, size_bytes=1)
        assert job.size_bytes == 1

    @pytest.mark.parametrize("close", [lambda j: j.cancel(T0), lambda j: j.finish_recording(T0)])
    def test_a_closed_recording_accepts_no_more_audio(self, close):
        job = new_recording()
        close(job)
        with pytest.raises(InvalidTransition):
            job.receive_audio(T0, size_bytes=1)

    def test_an_ordinary_job_accepts_no_audio(self):
        with pytest.raises(InvalidTransition):
            new_job().receive_audio(T0, size_bytes=1)

    def test_finishing_makes_a_waiting_recording_runnable_at_once(self):
        job = new_recording()
        job.start("w1", T0)
        job.pause("w1", T0, resume_at=T0 + timedelta(seconds=30))
        job.finish_recording(T0 + timedelta(seconds=1))
        assert job.audio_complete and job.is_runnable(T0 + timedelta(seconds=1))

    def test_a_recording_can_only_be_finished_once(self):
        job = new_recording()
        job.finish_recording(T0)
        with pytest.raises(InvalidTransition):
            job.finish_recording(T0)

    def test_a_recording_is_stalled_when_no_audio_arrived_for_too_long(self):
        job = new_recording()
        job.receive_audio(T0 + timedelta(seconds=10), size_bytes=1)
        assert not job.audio_stalled(T0 + timedelta(seconds=130), self.IDLE)
        assert job.audio_stalled(T0 + timedelta(seconds=131), self.IDLE)

    def test_a_finished_recording_is_never_stalled(self):
        job = new_recording()
        job.finish_recording(T0)
        assert not job.audio_stalled(T0 + timedelta(days=1), self.IDLE)

    def test_a_checkpoint_stores_the_text_so_far_and_the_length_heard(self):
        job = new_recording()
        job.start("w1", T0)
        job.checkpoint("w1", SOME_TEXT, duration_s=9.0)
        assert (job.draft, job.duration_s) == (SOME_TEXT, 9.0)

    def test_only_the_owner_may_checkpoint_or_pause(self):
        job = new_recording()
        job.start("w1", T0)
        with pytest.raises(NotOwner):
            job.checkpoint("w2", SOME_TEXT, duration_s=9.0)
        with pytest.raises(NotOwner):
            job.pause("w2", T0, resume_at=T0)

    def test_pausing_requeues_for_later_without_spending_an_attempt(self):
        job = new_recording()
        job.start("w1", T0)
        resume_at = T0 + timedelta(seconds=30)
        job.pause("w1", T0, resume_at=resume_at)
        assert (job.status, job.attempts, job.locked_by) == (JobStatus.QUEUED, 0, None)
        assert not job.is_runnable(T0) and job.is_runnable(resume_at)

    def test_pausing_a_recording_that_ended_meanwhile_does_not_delay_it(self):
        job = new_recording()
        job.start("w1", T0)
        job.finish_recording(T0)
        job.pause("w1", T0, resume_at=T0 + timedelta(seconds=30))
        assert job.is_runnable(T0)

    def test_a_crash_between_passes_still_counts_as_an_attempt(self):
        job = new_recording()
        job.start("w1", T0)
        job.pause("w1", T0, resume_at=T0)
        job.start("w1", T0)
        job.expire_lease(T0 + timedelta(minutes=5))
        assert job.attempts == 1 and job.status is JobStatus.QUEUED

    def test_completing_a_recording_clears_the_text_so_far(self):
        job = new_recording()
        job.start("w1", T0)
        job.finish_recording(T0)
        job.complete("w1", T0, outputs=[], stored_path="x", duration_s=1, language="en", num_speakers=0)
        assert job.draft == Draft()

    def test_running_a_recording_again_starts_from_the_beginning_with_what_was_recorded(self):
        job = new_recording()
        job.start("w1", T0)
        job.checkpoint("w1", SOME_TEXT, duration_s=9.0)
        job.cancel(T0)
        job.retry(T0)
        assert job.draft == Draft() and job.audio_complete

    def test_running_an_ordinary_job_again_leaves_its_draft_alone(self):
        job = started_job()
        job.cancel(T0)
        job.retry(T0)
        assert job.draft is None
