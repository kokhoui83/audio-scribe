"""Diarizer using a pyannote.audio speaker-diarization pipeline."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from scribe.application.ports import Progress
from scribe.domain.job import JobOptions
from scribe.domain.transcript import SpeakerTurn

# Rough share of the run time spent up to the end of each pipeline step.
_STEP_SPAN = {
    "segmentation": (0.0, 0.3),
    "speaker_counting": (0.3, 0.32),
    "embeddings": (0.32, 0.95),
    "discrete_diarization": (0.95, 1.0),
}


class ModelUnavailable(Exception):
    """The diarization model could not be loaded; the message says what to do."""


class PyannoteDiarizer:
    def __init__(self, pipeline: Callable[..., Any], to_waveform: Callable[[Any], Any]) -> None:
        self._pipeline = pipeline
        self._to_waveform = to_waveform

    def diarize(self, audio: Any, options: JobOptions, progress: Progress) -> list[SpeakerTurn]:
        def hook(step: str, artifact: Any = None, file: Any = None, total: int | None = None,
                 completed: int | None = None) -> None:  # fmt: skip
            low, high = _STEP_SPAN.get(step, (0.0, 0.0))
            if high:
                done = completed / total if total and completed is not None else 1.0
                progress(low + (high - low) * done)

        output = self._pipeline(
            {"waveform": self._to_waveform(audio.samples), "sample_rate": audio.sample_rate},
            hook=hook,
            **_speaker_hints(options),
        )
        # Prefer the variant without overlapping turns: each word then has
        # exactly one candidate speaker.
        annotation = output
        for name in ("exclusive_speaker_diarization", "speaker_diarization"):
            if getattr(output, name, None) is not None:
                annotation = getattr(output, name)
                break
        return [
            SpeakerTurn(segment.start, segment.end, label)
            for segment, _, label in annotation.itertracks(yield_label=True)
        ]


def _speaker_hints(options: JobOptions) -> dict[str, int]:
    if options.num_speakers:
        return {"num_speakers": options.num_speakers}
    hints = {"min_speakers": options.min_speakers, "max_speakers": options.max_speakers}
    return {k: v for k, v in hints.items() if v}


def load(*, model: str, token: str | None, device: str) -> PyannoteDiarizer:
    """Load (downloading on first use) the diarization pipeline. Once cached,
    no token and no network are needed."""
    import torch
    from pyannote.audio import Pipeline

    try:
        pipeline = Pipeline.from_pretrained(model, token=token)
    except Exception as exc:
        raise ModelUnavailable(_explain(model, token, exc)) from exc
    if pipeline is None:
        raise ModelUnavailable(_explain(model, token, None))
    pipeline.to(torch.device(device))

    def to_waveform(samples: Any) -> Any:
        return torch.from_numpy(samples).unsqueeze(0)

    return PyannoteDiarizer(pipeline, to_waveform)


def _explain(model: str, token: str | None, cause: Exception | None) -> str:
    steps = (
        f"To identify speakers, the model {model} must be downloaded once from Hugging Face: "
        f"1) accept its conditions at https://hf.co/{model}, "
        "2) create a read token at https://hf.co/settings/tokens, "
        "3) put it in .env as HF_TOKEN=... and run `docker compose up -d`. "
        "Or set DIARIZE=false to transcribe without speaker labels."
    )
    if not token:
        return f"HF_TOKEN is not set. {steps}"
    detail = f" ({type(cause).__name__}: {cause})" if cause else ""
    return f"The diarization model could not be loaded{detail}. {steps}"
