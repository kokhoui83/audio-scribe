"""Contract every JobRepository / WorkerRegistry implementation must honour.

Runs against the in-memory implementation always, and against PostgreSQL when
TEST_DATABASE_URL is set (it is in compose.test.yaml).
"""

import os
import threading
from datetime import UTC, datetime, timedelta

import pytest

from scribe.domain.draft import Draft
from scribe.domain.job import RECORDING, InvalidTransition, Job, JobOptions, JobStatus, RetryPolicy
from scribe.domain.transcript import SpeakerTurn, Word, build_transcript
from scribe.domain.worker import READY, WorkerState

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
POLICY = RetryPolicy()


def _memory():
    from scribe.adapters.memory import InMemoryJobRepository, InMemoryWorkerRegistry

    return InMemoryJobRepository(), InMemoryWorkerRegistry()


def _postgres():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    from scribe.adapters.postgres import Database, PostgresJobRepository, PostgresWorkerRegistry

    database = Database(url)
    database.migrate()
    database.execute("TRUNCATE jobs, workers")
    return PostgresJobRepository(database), PostgresWorkerRegistry(database), database


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.postgres)])
def stores(request):
    if request.param == "memory":
        yield _memory()
    else:
        jobs, workers, database = _postgres()
        yield jobs, workers
        database.close()


@pytest.fixture
def jobs(stores):
    return stores[0]


@pytest.fixture
def workers(stores):
    return stores[1]


def make_job(n: int = 1, **kw) -> Job:
    args = dict(
        job_id=f"00000000-0000-0000-0000-{n:012d}",
        filename=f"f{n}.mp3",
        source="folder",
        stored_path=f".work/{n}/f{n}.mp3",
        size_bytes=n,
        now=T0 + timedelta(seconds=n),
    )
    args.update(kw)
    return Job.submit(**args)


def transcript():
    return build_transcript(
        [Word(0, 1, " Hi", probability=0.9), Word(1, 2, " yo")],
        [SpeakerTurn(0, 1, "A"), SpeakerTurn(1, 2, "B")],
        file="f1.mp3",
        language="en",
        duration=2.0,
        created="2026-01-01T12:00:00+00:00",
    )


class TestStoring:
    def test_a_job_is_returned_exactly_as_it_was_added(self, jobs):
        job = make_job(
            rel_dir="team/a", max_attempts=5, options=JobOptions(language="de", diarize=False, max_speakers=4)
        )
        jobs.add(job)
        assert jobs.get(job.id) == job

    def test_an_unknown_job_is_none(self, jobs):
        assert jobs.get("00000000-0000-0000-0000-000000000999") is None

    def test_jobs_are_listed_newest_first(self, jobs):
        for n in (1, 2, 3):
            jobs.add(make_job(n))
        assert [j.filename for j in jobs.list()] == ["f3.mp3", "f2.mp3", "f1.mp3"]
        assert [j.filename for j in jobs.list(limit=1, offset=1)] == ["f2.mp3"]

    def test_listing_can_be_filtered_by_status(self, jobs):
        jobs.add(make_job(1))
        jobs.add(make_job(2))
        jobs.update(make_job(1).id, lambda j: j.cancel(T0))
        assert [j.filename for j in jobs.list(status=JobStatus.CANCELLED)] == ["f1.mp3"]

    def test_counts_cover_every_status(self, jobs):
        jobs.add(make_job(1))
        jobs.add(make_job(2))
        jobs.update(make_job(2).id, lambda j: j.cancel(T0))
        assert jobs.counts() == {"queued": 1, "processing": 0, "done": 0, "failed": 0, "cancelled": 1}

    def test_ids_and_delete(self, jobs):
        jobs.add(make_job(1))
        jobs.add(make_job(2))
        assert jobs.delete(make_job(1).id).filename == "f1.mp3"
        assert jobs.ids() == {make_job(2).id}
        assert jobs.delete(make_job(1).id) is None


class TestClaiming:
    def test_the_oldest_runnable_job_is_started_for_the_worker(self, jobs):
        jobs.add(make_job(2))
        jobs.add(make_job(1))
        now = T0 + timedelta(minutes=1)
        claimed = jobs.claim_next("w1", now)
        assert claimed.filename == "f1.mp3"
        assert (claimed.status, claimed.locked_by, claimed.attempts) == (JobStatus.PROCESSING, "w1", 1)
        assert jobs.get(claimed.id) == claimed

    def test_nothing_to_claim(self, jobs):
        assert jobs.claim_next("w1", T0) is None

    def test_a_job_is_claimed_only_once(self, jobs):
        jobs.add(make_job(1))
        assert jobs.claim_next("w1", T0 + timedelta(minutes=1)) is not None
        assert jobs.claim_next("w2", T0 + timedelta(minutes=1)) is None

    def test_a_job_waiting_for_its_retry_delay_is_skipped(self, jobs):
        jobs.add(make_job(1))
        now = T0 + timedelta(minutes=1)
        jobs.claim_next("w1", now)
        jobs.update(make_job(1).id, lambda j: j.fail("w1", now, "boom", retryable=True, policy=POLICY))
        assert jobs.claim_next("w1", now + timedelta(seconds=29)) is None
        assert jobs.claim_next("w1", now + timedelta(seconds=30)).attempts == 2

    def test_concurrent_workers_never_get_the_same_job(self, jobs):
        for n in range(1, 21):
            jobs.add(make_job(n))
        claimed, lock = [], threading.Lock()

        def work(worker_id):
            while (job := jobs.claim_next(worker_id, T0 + timedelta(hours=1))) is not None:
                with lock:
                    claimed.append(job.id)

        threads = [threading.Thread(target=work, args=(f"w{i}",)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(claimed) == 20 and len(set(claimed)) == 20


class TestUpdating:
    def test_a_mutation_is_applied_and_saved(self, jobs):
        jobs.add(make_job(1))
        updated = jobs.update(make_job(1).id, lambda j: j.rename_speakers({"Speaker 1": "Alice"}))
        assert updated.speaker_names == {"Speaker 1": "Alice"}
        assert jobs.get(updated.id) == updated

    def test_updating_an_unknown_job_returns_none(self, jobs):
        assert jobs.update("00000000-0000-0000-0000-000000000999", lambda j: j.cancel(T0)) is None

    def test_a_rejected_mutation_changes_nothing(self, jobs):
        jobs.add(make_job(1))
        with pytest.raises(InvalidTransition):
            jobs.update(make_job(1).id, lambda j: j.retry(T0))
        assert jobs.get(make_job(1).id) == make_job(1)

    def test_a_completed_job_keeps_its_transcript(self, jobs):
        jobs.add(make_job(1))
        job = jobs.claim_next("w1", T0 + timedelta(minutes=1))
        done_at = T0 + timedelta(minutes=2)
        jobs.update(
            job.id,
            lambda j: j.complete(
                "w1",
                done_at,
                outputs=["output/f1.md"],
                stored_path="archive/f1.mp3",
                duration_s=2.0,
                language="en",
                num_speakers=2,
                transcript=transcript(),
            ),
        )
        stored = jobs.get(job.id, with_transcript=True)
        assert stored.status is JobStatus.DONE and stored.finished_at == done_at
        assert stored.outputs == ["output/f1.md"] and stored.transcript == transcript()

    def test_transcripts_are_only_loaded_on_request(self, jobs):
        jobs.add(make_job(1))
        job = jobs.claim_next("w1", T0 + timedelta(minutes=1))
        jobs.update(
            job.id,
            lambda j: j.complete(
                "w1",
                T0,
                outputs=[],
                stored_path="x",
                duration_s=2.0,
                language="en",
                num_speakers=2,
                transcript=transcript(),
            ),
        )
        assert jobs.get(job.id).transcript is None
        assert jobs.list()[0].transcript is None

    def test_an_update_that_does_not_touch_the_transcript_keeps_it(self, jobs):
        jobs.add(make_job(1))
        job = jobs.claim_next("w1", T0 + timedelta(minutes=1))
        jobs.update(
            job.id,
            lambda j: j.complete(
                "w1",
                T0,
                outputs=[],
                stored_path="x",
                duration_s=2.0,
                language="en",
                num_speakers=2,
                transcript=transcript(),
            ),
        )
        jobs.update(job.id, lambda j: j.rename_speakers({"Speaker 1": "Al"}))
        assert jobs.get(job.id, with_transcript=True).transcript == transcript()


class TestRecordings:
    DRAFT = Draft(position=4.2, language="en", words=(Word(0.0, 1.0, " Hi", segment=3, probability=0.9),))

    def recording(self, jobs) -> Job:
        job = make_job(1, source=RECORDING, size_bytes=0, audio_complete=False)
        jobs.add(job)
        return job

    def test_a_recording_is_returned_exactly_as_it_was_added(self, jobs):
        job = self.recording(jobs)
        stored = jobs.get(job.id)
        assert stored == job and not stored.audio_complete and stored.audio_at == job.created_at

    def test_arriving_audio_is_saved(self, jobs):
        job = self.recording(jobs)
        later = T0 + timedelta(minutes=1)
        jobs.update(job.id, lambda j: j.receive_audio(later, size_bytes=512))
        stored = jobs.get(job.id)
        assert (stored.size_bytes, stored.audio_at) == (512, later)

    def test_the_text_so_far_is_saved_and_only_loaded_on_request(self, jobs):
        job = self.recording(jobs)
        jobs.claim_next("w1", T0 + timedelta(minutes=1))
        jobs.update(job.id, lambda j: j.checkpoint("w1", self.DRAFT, duration_s=9.0))
        assert jobs.get(job.id).draft is None and jobs.list()[0].draft is None
        stored = jobs.get(job.id, with_transcript=True)
        assert stored.draft == self.DRAFT and stored.draft.words[0].segment == 3
        assert stored.duration_s == 9.0

    def test_an_update_that_does_not_touch_the_text_so_far_keeps_it(self, jobs):
        job = self.recording(jobs)
        now = T0 + timedelta(minutes=1)
        jobs.claim_next("w1", now)
        jobs.update(job.id, lambda j: j.checkpoint("w1", self.DRAFT, duration_s=9.0))
        jobs.update(job.id, lambda j: j.pause("w1", now, resume_at=now + timedelta(seconds=30)))
        assert jobs.get(job.id, with_transcript=True).draft == self.DRAFT
        assert jobs.claim_next("w1", now + timedelta(seconds=29)) is None
        assert jobs.claim_next("w1", now + timedelta(seconds=30)).attempts == 1

    def test_a_job_without_text_so_far_has_none(self, jobs):
        jobs.add(make_job(1))
        assert jobs.get(make_job(1).id, with_transcript=True).draft is None


class TestStaleJobs:
    def test_only_processing_jobs_with_an_old_heartbeat_are_stale(self, jobs):
        for n in (1, 2, 3):
            jobs.add(make_job(n))
        start = T0 + timedelta(minutes=1)
        old = jobs.claim_next("w1", start)
        fresh = jobs.claim_next("w2", start)
        jobs.update(fresh.id, lambda j: j.renew("w2", start + timedelta(seconds=100)))
        assert jobs.stale_ids(start + timedelta(seconds=50)) == [old.id]


class TestWorkerRegistry:
    def test_a_worker_report_replaces_the_previous_one(self, workers):
        workers.report(
            WorkerState("w1", "loading", T0, device="cpu", speech_model="tiny", speaker_model="off")
        )
        latest = WorkerState("w1", READY, T0 + timedelta(seconds=5), None, "cpu", "tiny", "off")
        workers.report(latest)
        workers.report(WorkerState("w2", "error", T0, message="no token"))
        assert workers.list() == [latest, WorkerState("w2", "error", T0, message="no token")]

    def test_a_removed_worker_is_no_longer_listed(self, workers):
        workers.report(WorkerState("w1", READY, T0))
        workers.remove("w1")
        assert workers.list() == []
