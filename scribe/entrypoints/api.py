"""HTTP API and web page. Translates HTTP to JobService calls and back; no
business rules live here."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from scribe.application.management import (
    EmptyUpload,
    JobNotFound,
    JobService,
    OriginalMissing,
    TranscriptNotReady,
)
from scribe.application.ports import OutOfSequence
from scribe.domain.job import InvalidTransition, Job, JobOptions, JobStatus
from scribe.domain.rendering import FORMATS

STATIC = Path(__file__).parent / "static"


class SpeakerNames(BaseModel):
    names: dict[str, str]


def job_view(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "filename": job.filename,
        "source": job.source,
        "folder": job.rel_dir,
        "stored_path": job.stored_path,
        "size_bytes": job.size_bytes,
        "options": job.options.to_dict(),
        "status": job.status.value,
        "stage": job.stage,
        "progress": job.progress,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "run_after": job.run_after,
        "error": job.error,
        "speaker_names": job.speaker_names,
        "outputs": job.outputs,
        "duration_s": job.duration_s,
        "language": job.language,
        "num_speakers": job.num_speakers,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "recording": not job.audio_complete,
    }


def _options(
    language: str, diarize: str, num_speakers: str, min_speakers: str, max_speakers: str
) -> JobOptions:
    options = JobOptions(
        language=language.strip().lower() or None,
        diarize=_optional_flag("diarize", diarize),
        num_speakers=_optional_count("num_speakers", num_speakers),
        min_speakers=_optional_count("min_speakers", min_speakers),
        max_speakers=_optional_count("max_speakers", max_speakers),
    )
    if options.min_speakers and options.max_speakers and options.min_speakers > options.max_speakers:
        raise HTTPException(400, "min_speakers cannot be greater than max_speakers")
    return options


def _optional_count(name: str, raw: str) -> int | None:
    raw = raw.strip()
    if not raw:
        return None
    if not raw.isdigit() or int(raw) < 1:
        raise HTTPException(400, f"{name} must be a whole number of at least 1")
    return int(raw)


def _optional_flag(name: str, raw: str) -> bool | None:
    value = raw.strip().lower()
    if not value:
        return None
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise HTTPException(400, f"{name} must be true or false")


def create_app(service: JobService) -> FastAPI:
    app = FastAPI(title="Audio Scribe", version="0.1.0")

    @app.exception_handler(JobNotFound)
    def _not_found(_, __):
        return JSONResponse({"detail": "job not found"}, status_code=404)

    @app.exception_handler(InvalidTransition)
    @app.exception_handler(OriginalMissing)
    @app.exception_handler(TranscriptNotReady)
    def _conflict(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(OutOfSequence)
    def _out_of_sequence(_, exc):
        return JSONResponse({"detail": str(exc), "expected_offset": exc.expected}, status_code=409)

    @app.exception_handler(EmptyUpload)
    def _bad_upload(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/", include_in_schema=False)
    def page():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/api/health")
    def health():
        report = service.health()
        body = {
            "status": "ok" if report.database_ok else "unavailable",
            "database": report.database_ok,
            "jobs": report.jobs,
            "formats": list(FORMATS),
            "workers": [
                {
                    "id": w.state.id,
                    "status": w.state.status,
                    "message": w.state.message,
                    "device": w.state.device,
                    "speech_model": w.state.speech_model,
                    "speaker_model": w.state.speaker_model,
                    "heartbeat_at": w.state.heartbeat_at.isoformat(),
                    "alive": w.alive,
                }
                for w in report.workers
            ],
        }
        return JSONResponse(body, status_code=200 if report.database_ok else 503)

    @app.get("/api/jobs")
    def list_jobs(
        status: JobStatus | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        return {"jobs": [job_view(j) for j in service.list(status, limit, offset)]}

    @app.post("/api/jobs", status_code=201)
    def upload(
        file: Annotated[UploadFile, File()],
        language: Annotated[str, Form()] = "",
        diarize: Annotated[str, Form()] = "",
        num_speakers: Annotated[str, Form()] = "",
        min_speakers: Annotated[str, Form()] = "",
        max_speakers: Annotated[str, Form()] = "",
    ):
        options = _options(language, diarize, num_speakers, min_speakers, max_speakers)
        return job_view(service.submit_upload(file.filename or "audio", file.file, options))

    @app.post("/api/recordings", status_code=201)
    def start_recording(
        filename: Annotated[str, Form()] = "",
        language: Annotated[str, Form()] = "",
        diarize: Annotated[str, Form()] = "",
        num_speakers: Annotated[str, Form()] = "",
        min_speakers: Annotated[str, Form()] = "",
        max_speakers: Annotated[str, Form()] = "",
    ):
        options = _options(language, diarize, num_speakers, min_speakers, max_speakers)
        return job_view(service.start_recording(filename.strip() or "recording.webm", options))

    @app.post("/api/recordings/{job_id}/audio")
    def add_audio(job_id: str, piece: Annotated[UploadFile, File()], offset: Annotated[int, Form(ge=0)]):
        return job_view(service.add_audio(job_id, offset, piece.file))

    @app.post("/api/recordings/{job_id}/finish")
    def finish_recording(job_id: str):
        return job_view(service.finish_recording(job_id))

    @app.get("/api/jobs/{job_id}/draft")
    def draft(job_id: str):
        so_far = service.text_so_far(job_id)
        return {"text": so_far.text, "seconds": so_far.seconds}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        return job_view(service.get(job_id))

    @app.get("/api/jobs/{job_id}/transcript")
    def transcript(job_id: str, format: str = "md", download: bool = False):
        if format not in FORMATS:
            raise HTTPException(400, f"format must be one of {', '.join(FORMATS)}")
        text = service.transcript_text(job_id, format)
        headers = {}
        if download:
            name = f"{PurePosixPath(service.get(job_id).filename).stem}.{format}"
            headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(name)}"
        return Response(text, media_type=f"{FORMATS[format]}; charset=utf-8", headers=headers)

    @app.put("/api/jobs/{job_id}/speakers")
    def rename_speakers(job_id: str, body: SpeakerNames):
        return job_view(service.rename_speakers(job_id, body.names))

    @app.post("/api/jobs/{job_id}/retry")
    def retry(job_id: str):
        return job_view(service.retry(job_id))

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        return job_view(service.cancel(job_id))

    @app.delete("/api/jobs/{job_id}", status_code=204)
    def delete(job_id: str):
        service.delete(job_id)
        return Response(status_code=204)

    return app


def build() -> FastAPI:
    """Factory for uvicorn: ``uvicorn --factory scribe.entrypoints.api:build``."""
    from scribe import bootstrap

    return create_app(bootstrap.job_service())
