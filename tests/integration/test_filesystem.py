"""LocalFileStore details that the feature scenarios do not reach."""

import io
from datetime import UTC, datetime

import pytest

from scribe.adapters.filesystem import LocalFileStore
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
