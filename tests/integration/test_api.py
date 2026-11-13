"""The HTTP API, driven through FastAPI's test client against real use cases."""

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from scribe.adapters.filesystem import LocalFileStore
from scribe.adapters.memory import InMemoryJobRepository, InMemoryWorkerRegistry
from scribe.application.management import JobService
from scribe.application.processing import Engines
from scribe.application.worker import Worker
from scribe.domain.job import RetryPolicy
from scribe.entrypoints.api import create_app
from tests.fakes import NOT_AUDIO, FakeClock, FakeDecoder, FakeDiarizer, FakeRecognizer, recording

AUDIO = recording(("anna", "Hello Ben."), ("ben", "Hello Anna.")).encode()


class Api:
    def __init__(self, tmp_path):
        self.clock = FakeClock()
        self.database_ok = True
        jobs, files, registry = InMemoryJobRepository(), LocalFileStore(tmp_path), InMemoryWorkerRegistry()
        self.files = files
        service = JobService(
            jobs=jobs,
            files=files,
            workers=registry,
            clock=self.clock,
            new_id=lambda: str(uuid.uuid4()),
            max_attempts=1,
            worker_timeout=timedelta(seconds=45),
            database_ok=lambda: self.database_ok,
        )
        self.worker = Worker(
            worker_id="w1",
            jobs=jobs,
            files=files,
            registry=registry,
            clock=self.clock,
            load_engines=lambda: Engines(
                FakeDecoder(), FakeRecognizer(), FakeDiarizer(), "cpu", "tiny", "fake"
            ),
            policy=RetryPolicy(max_attempts=1),
            output_formats=("md",),
            default_language=None,
            heartbeat=timedelta(seconds=10),
        )
        self.http = TestClient(create_app(service))

    def upload(self, name="call.mp3", content=AUDIO, **form) -> dict:
        response = self.http.post("/api/jobs", files={"file": (name, content)}, data=form)
        assert response.status_code == 201, response.text
        return response.json()

    def finished(self, **kw) -> dict:
        job = self.upload(**kw)
        self.worker.tick()
        return self.http.get(f"/api/jobs/{job['id']}").json()


@pytest.fixture
def api(tmp_path):
    return Api(tmp_path)


MISSING = "/api/jobs/00000000-0000-0000-0000-000000000000"


class TestUploading:
    def test_an_upload_becomes_a_queued_job(self, api):
        job = api.upload("interview.m4a")
        assert (job["filename"], job["status"], job["source"], job["attempts"]) == (
            "interview.m4a",
            "queued",
            "upload",
            0,
        )
        assert job["size_bytes"] == len(AUDIO) and job["created_at"].startswith("2026-01-01T12:00:00")

    def test_options_are_recorded(self, api):
        job = api.upload(language="FR", diarize="false", num_speakers="2", min_speakers="", max_speakers="")
        assert job["options"] == {"language": "fr", "diarize": False, "num_speakers": 2}

    def test_an_empty_upload_is_rejected(self, api):
        response = api.http.post("/api/jobs", files={"file": ("a.mp3", b"")})
        assert response.status_code == 400 and "empty" in response.json()["detail"]
        assert api.http.get("/api/jobs").json()["jobs"] == []

    @pytest.mark.parametrize(
        "form", [{"num_speakers": "0"}, {"num_speakers": "x"}, {"min_speakers": "3", "max_speakers": "2"}]
    )
    def test_nonsensical_speaker_counts_are_rejected(self, api, form):
        assert api.http.post("/api/jobs", files={"file": ("a.mp3", AUDIO)}, data=form).status_code in (
            400,
            422,
        )

    def test_a_hostile_file_name_is_reduced_to_its_base_name(self, api):
        assert api.upload("../../etc/passwd.mp3")["filename"] == "passwd.mp3"


class TestListing:
    def test_jobs_are_listed_newest_first_and_can_be_filtered(self, api):
        api.finished(name="a.mp3")
        api.clock.advance(1)
        api.upload("b.mp3")
        assert [j["filename"] for j in api.http.get("/api/jobs").json()["jobs"]] == ["b.mp3", "a.mp3"]
        done = api.http.get("/api/jobs", params={"status": "done"}).json()["jobs"]
        assert [j["filename"] for j in done] == ["a.mp3"]

    def test_an_unknown_status_filter_is_rejected(self, api):
        assert api.http.get("/api/jobs", params={"status": "weird"}).status_code == 422

    def test_a_finished_job_reports_its_summary(self, api):
        job = api.finished()
        assert (job["status"], job["language"], job["num_speakers"], job["progress"]) == (
            "done",
            "en",
            2,
            1.0,
        )
        assert job["outputs"] == ["output/call.md"] and job["duration_s"] > 0

    def test_an_unknown_job_is_404(self, api):
        assert api.http.get(MISSING).status_code == 404
        assert api.http.delete(MISSING).status_code == 404
        assert api.http.post(MISSING + "/retry").status_code == 404
        assert api.http.post(MISSING + "/cancel").status_code == 404
        assert api.http.get(MISSING + "/transcript").status_code == 404


class TestTranscripts:
    def test_markdown_is_the_default_format(self, api):
        job = api.finished()
        response = api.http.get(f"/api/jobs/{job['id']}/transcript")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        assert "**Speaker 1**" in response.text

    @pytest.mark.parametrize(
        "fmt, media",
        [
            ("json", "application/json"),
            ("srt", "application/x-subrip"),
            ("vtt", "text/vtt"),
            ("txt", "text/plain"),
        ],
    )
    def test_other_formats_come_with_their_media_type(self, api, fmt, media):
        job = api.finished()
        response = api.http.get(f"/api/jobs/{job['id']}/transcript", params={"format": fmt})
        assert response.status_code == 200 and response.headers["content-type"].startswith(media)

    def test_a_download_carries_a_file_name(self, api):
        job = api.finished(name="Team call.mp3")
        response = api.http.get(
            f"/api/jobs/{job['id']}/transcript", params={"format": "srt", "download": "1"}
        )
        assert "attachment" in response.headers["content-disposition"]
        assert "Team%20call.srt" in response.headers["content-disposition"]

    def test_an_unknown_format_is_400(self, api):
        job = api.finished()
        assert api.http.get(f"/api/jobs/{job['id']}/transcript", params={"format": "docx"}).status_code == 400

    def test_a_transcript_that_is_not_ready_is_409(self, api):
        job = api.upload()
        assert api.http.get(f"/api/jobs/{job['id']}/transcript").status_code == 409

    def test_speakers_can_be_renamed(self, api):
        job = api.finished()
        response = api.http.put(f"/api/jobs/{job['id']}/speakers", json={"names": {"Speaker 1": "Anna"}})
        assert response.status_code == 200 and response.json()["speaker_names"] == {"Speaker 1": "Anna"}
        assert "**Anna**" in api.http.get(f"/api/jobs/{job['id']}/transcript").text
        assert "**Anna**" in api.files.local_path("output/call.md").read_text()


class TestActions:
    def test_cancel_then_retry_then_delete(self, api):
        job = api.upload()
        url = f"/api/jobs/{job['id']}"
        assert api.http.post(url + "/cancel").json()["status"] == "cancelled"
        assert api.http.post(url + "/cancel").status_code == 409
        assert api.http.post(url + "/retry").json()["status"] == "queued"
        assert api.http.post(url + "/retry").status_code == 409
        assert api.http.delete(url).status_code == 204
        assert api.http.get(url).status_code == 404

    def test_a_failed_job_shows_its_error(self, api):
        job = api.finished(content=NOT_AUDIO.encode())
        assert job["status"] == "failed" and "does not contain audio" in job["error"]

    def test_retrying_without_the_original_is_409(self, api):
        job = api.finished()
        api.files.local_path(job["stored_path"]).unlink()
        response = api.http.post(f"/api/jobs/{job['id']}/retry")
        assert response.status_code == 409 and "no longer available" in response.json()["detail"]


class TestRecording:
    # The newest five seconds are held back, so the first voice must be followed by more than that.
    FIRST = recording(
        ("anna", "Hello Ben. How are you today my friend?"),
        ("ben", "Fine thanks. I was away for a week and only got back today."),
    )
    SECOND = recording(("anna", "Very well."))

    def start(self, api, **form) -> dict:
        response = api.http.post("/api/recordings", data={"filename": "standup.webm", **form})
        assert response.status_code == 201, response.text
        return response.json()

    def send(self, api, job, piece: str, offset: int):
        return api.http.post(
            f"/api/recordings/{job['id']}/audio",
            files={"piece": ("piece", piece.encode())},
            data={"offset": str(offset)},
        )

    def test_a_started_recording_is_a_queued_job_that_expects_audio(self, api):
        job = self.start(api, language="EN", num_speakers="2")
        assert (job["filename"], job["source"], job["status"], job["recording"], job["size_bytes"]) == (
            "standup.webm",
            "recording",
            "queued",
            True,
            0,
        )
        assert job["options"] == {"language": "en", "num_speakers": 2}

    def test_a_recording_gets_a_name_when_none_is_given(self, api):
        assert api.http.post("/api/recordings").json()["filename"] == "recording.webm"

    def test_an_uploaded_file_is_not_a_recording(self, api):
        assert api.upload()["recording"] is False

    def test_pieces_are_stored_and_the_text_so_far_can_be_read(self, api):
        job = self.start(api)
        url = f"/api/jobs/{job['id']}"
        assert api.http.get(url + "/draft").json() == {"text": "", "seconds": 0.0}
        sent = self.send(api, job, self.FIRST, 0)
        assert sent.status_code == 200 and sent.json()["size_bytes"] == len(self.FIRST)
        api.worker.tick()
        draft = api.http.get(url + "/draft").json()
        assert draft["text"] == "Hello Ben. How are you today my friend?" and draft["seconds"] > 4
        listed = api.http.get(url).json()
        assert (listed["status"], listed["recording"], listed["attempts"]) == ("queued", True, 0)
        assert listed["duration_s"] > 0

    def test_finishing_leads_to_a_transcript_with_speakers(self, api):
        job = self.start(api)
        self.send(api, job, self.FIRST, 0)
        api.worker.tick()
        self.send(api, job, self.SECOND, len(self.FIRST))
        finished = api.http.post(f"/api/recordings/{job['id']}/finish")
        assert finished.status_code == 200 and finished.json()["recording"] is False
        api.worker.tick()
        done = api.http.get(f"/api/jobs/{job['id']}").json()
        assert (done["status"], done["num_speakers"]) == ("done", 2)
        text = api.http.get(f"/api/jobs/{job['id']}/transcript", params={"format": "txt"}).text
        assert "only got back today." in text and "Very well." in text

    def test_a_repeated_piece_is_accepted_and_a_gap_is_409_naming_the_expected_offset(self, api):
        job = self.start(api)
        self.send(api, job, self.FIRST, 0)
        assert self.send(api, job, self.FIRST, 0).json()["size_bytes"] == len(self.FIRST)
        gap = self.send(api, job, self.SECOND, len(self.FIRST) + 1)
        assert gap.status_code == 409 and gap.json()["expected_offset"] == len(self.FIRST)

    def test_audio_for_a_closed_recording_is_409(self, api):
        job = self.start(api)
        self.send(api, job, self.FIRST, 0)
        api.http.post(f"/api/recordings/{job['id']}/finish")
        assert self.send(api, job, self.SECOND, len(self.FIRST)).status_code == 409
        assert api.http.post(f"/api/recordings/{job['id']}/finish").status_code == 409

    def test_audio_for_an_uploaded_file_is_409(self, api):
        assert self.send(api, api.upload(), self.SECOND, len(AUDIO)).status_code == 409

    def test_finishing_without_audio_is_400_and_leaves_no_job(self, api):
        job = self.start(api)
        response = api.http.post(f"/api/recordings/{job['id']}/finish")
        assert response.status_code == 400 and "nothing was recorded" in response.json()["detail"]
        assert api.http.get("/api/jobs").json()["jobs"] == []

    def test_a_negative_offset_is_rejected(self, api):
        assert self.send(api, self.start(api), self.FIRST, -1).status_code == 422

    def test_an_unknown_recording_is_404(self, api):
        missing = {"id": MISSING.rsplit("/", 1)[1]}
        assert self.send(api, missing, self.FIRST, 0).status_code == 404
        assert api.http.post(f"/api/recordings/{missing['id']}/finish").status_code == 404
        assert api.http.get(MISSING + "/draft").status_code == 404


class TestHealth:
    def test_health_reports_queue_and_workers(self, api):
        api.finished()
        body = api.http.get("/api/health").json()
        assert body["status"] == "ok" and body["jobs"]["done"] == 1
        assert body["formats"] == ["md", "txt", "json", "srt", "vtt"]
        (worker,) = body["workers"]
        assert (
            worker["id"],
            worker["status"],
            worker["alive"],
            worker["device"],
            worker["speech_model"],
        ) == ("w1", "ready", True, "cpu", "tiny")

    def test_health_is_503_when_the_database_is_down(self, api):
        api.database_ok = False
        response = api.http.get("/api/health")
        assert response.status_code == 503 and response.json()["status"] == "unavailable"


def test_the_web_page_is_served(api):
    response = api.http.get("/")
    assert response.status_code == 200 and "text/html" in response.headers["content-type"]
    assert "Audio Scribe" in response.text


def test_the_web_page_can_record(api):
    page = api.http.get("/").text
    assert 'id="record"' in page and "/api/recordings" in page
