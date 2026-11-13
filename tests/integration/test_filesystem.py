"""LocalFileStore details that the feature scenarios do not reach."""

import io
from datetime import UTC, datetime

import pytest

from scribe.adapters.filesystem import LocalFileStore
from scribe.application.ports import OutOfSequence
from scribe.domain.job import Job

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    return LocalFileStore(tmp_path)


def job(store, name="call.mp3", job_id="job-1", rel_dir="") -> Job:
    stored, size = store.stage_upload(job_id, name, io.BytesIO(b"audio"))
    return Job.submit(
        job_id=job_id,
        filename=name,
        source="upload",
        stored_path=stored,
        size_bytes=size,
        now=NOW,
        rel_dir=rel_dir,
    )


@pytest.mark.parametrize(
    "hostile", ["../../etc/passwd", "..\\..\\boot.ini", "/abs/olute.mp3", "a/b/../../c.mp3"]
)
def test_an_upload_can_never_be_written_outside_its_staging_folder(store, tmp_path, hostile):
    stored, _ = store.stage_upload("job-1", hostile, io.BytesIO(b"x"))
    assert store.local_path(stored).parent == tmp_path / ".work" / "job-1"


def test_an_unusable_upload_name_gets_a_placeholder(store):
    stored, _ = store.stage_upload("job-1", "..", io.BytesIO(b"x"))
    assert stored == ".work/job-1/audio"


def test_outputs_cannot_escape_the_output_folder(store, tmp_path):
    written = store.write_outputs(job(store, rel_dir="../../outside"), {"md": "text"})
    assert written == ["output/outside/call.md"]


def test_rerunning_a_job_overwrites_its_own_transcript(store):
    j = job(store)
    j.outputs = store.write_outputs(j, {"md": "first"})
    assert store.write_outputs(j, {"md": "second"}) == ["output/call.md"]
    assert store.local_path("output/call.md").read_text() == "second"


def test_archived_originals_with_the_same_name_are_numbered(store):
    first = store.archive_original(job(store, job_id="job-1"))
    second = store.archive_original(job(store, job_id="job-2"))
    assert (first, second) == ("archive/call.mp3", "archive/call (2).mp3")


def test_a_file_returned_to_the_inbox_does_not_replace_a_newer_one(store, tmp_path):
    (tmp_path / "inbox" / "call.mp3").write_bytes(b"old")
    stored = store.stage_from_inbox("call.mp3", "job-1")
    (tmp_path / "inbox" / "call.mp3").write_bytes(b"new")
    store.return_to_inbox(stored, "call.mp3")
    assert sorted(p.name for p in (tmp_path / "inbox").iterdir()) == ["call (2).mp3", "call.mp3"]
    assert not (tmp_path / ".work" / "job-1").exists()


def test_writing_is_atomic_and_leaves_no_temporary_files(store, tmp_path):
    store.write_outputs(job(store), {"md": "text", "json": "{}"})
    assert sorted(p.name for p in (tmp_path / "output").iterdir()) == ["call.json", "call.md"]


class TestAppendingAudio:
    @pytest.fixture
    def stored(self, store):
        return store.stage_upload("job-1", "standup.webm", io.BytesIO(b""))[0]

    def test_pieces_are_appended_in_order(self, store, stored):
        assert store.append_audio(stored, 0, io.BytesIO(b"abc")) == 3
        assert store.append_audio(stored, 3, io.BytesIO(b"def")) == 6
        assert store.local_path(stored).read_bytes() == b"abcdef"

    def test_a_piece_that_is_sent_again_changes_nothing(self, store, stored):
        store.append_audio(stored, 0, io.BytesIO(b"abc"))
        store.append_audio(stored, 3, io.BytesIO(b"def"))
        assert store.append_audio(stored, 0, io.BytesIO(b"abc")) == 6
        assert store.local_path(stored).read_bytes() == b"abcdef"

    def test_a_piece_that_was_only_partly_stored_is_completed(self, store, stored):
        store.append_audio(stored, 0, io.BytesIO(b"abcd"))
        assert store.append_audio(stored, 3, io.BytesIO(b"def")) == 6
        assert store.local_path(stored).read_bytes() == b"abcdef"

    def test_a_piece_that_would_leave_a_gap_is_refused(self, store, stored):
        store.append_audio(stored, 0, io.BytesIO(b"abc"))
        with pytest.raises(OutOfSequence) as refusal:
            store.append_audio(stored, 5, io.BytesIO(b"x"))
        assert refusal.value.expected == 3 and "byte 3" in str(refusal.value)
        assert store.local_path(stored).read_bytes() == b"abc"

    def test_audio_cannot_be_added_to_a_file_that_is_gone(self, store):
        with pytest.raises(OutOfSequence):
            store.append_audio(".work/job-9/gone.webm", 0, io.BytesIO(b"abc"))
