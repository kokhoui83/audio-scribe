"""SpeechRecognizer using Whisper through faster-whisper (CTranslate2)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from functools import partial
from pathlib import Path
from typing import Any

from scribe.application.ports import Progress, Recognition
from scribe.domain.transcript import Word

# (samples, **options) -> (segments, info), as faster-whisper's transcribe().
Transcribe = Callable[..., tuple[Iterable[Any], Any]]


class WhisperRecognizer:
    def __init__(self, transcribe: Transcribe) -> None:
        self._transcribe = transcribe

    def recognize(self, audio: Any, language: str | None, progress: Progress) -> Recognition:
        segments, info = self._transcribe(audio.samples, language=language, word_timestamps=True)
        words: list[Word] = []
        # faster-whisper decodes lazily: each step of this loop is model work,
        # so reporting progress here is also what lets a job be aborted.
        for index, segment in enumerate(segments):
            if segment.words:
                words.extend(
                    Word(w.start, w.end, w.word, segment=index, probability=w.probability)
                    for w in segment.words
                )
            elif segment.text.strip():
                words.append(Word(segment.start, segment.end, " " + segment.text.strip(), segment=index))
            progress(min(segment.end / audio.duration, 1.0) if audio.duration else 1.0)
        return Recognition(info.language, words)


def load(
    *,
    model: str,
    device: str,
    compute_type: str,
    batch_size: int,
    cpu_threads: int,
    cache_dir: Path,
) -> WhisperRecognizer:
    """Load (downloading on first use) a Whisper model. Speech is located with
    a voice-activity detector first, which avoids invented text in silences."""
    from faster_whisper import BatchedInferencePipeline, WhisperModel

    whisper = WhisperModel(
        model,
        device=device,
        compute_type=compute_type,
        cpu_threads=cpu_threads,
        download_root=str(cache_dir),
    )
    if batch_size > 1:
        return WhisperRecognizer(partial(BatchedInferencePipeline(whisper).transcribe, batch_size=batch_size))
    return WhisperRecognizer(partial(whisper.transcribe, vad_filter=True, condition_on_previous_text=False))
