"""Test doubles for the things that are slow or need hardware: the clock and
the speech models. A fake "recording" is a text file with one line per
utterance, ``voice: what is said``; the fakes turn it into timed words and
speaker turns the way real models would."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scribe.application.ports import Recognition, UnreadableAudio
from scribe.domain.transcript import SpeakerTurn, Word

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
WORD_SECONDS = 0.5
PAUSE_SECONDS = 0.5
NOT_AUDIO = "this is not audio"


class FakeClock:
    def __init__(self, start: datetime = T0) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def recording(*lines: tuple[str, str]) -> str:
    return "".join(f"{voice}: {text}\n" for voice, text in lines)


@dataclass
class FakeAudio:
    utterances: list[tuple[float, float, str, list[Word]]]  # start, end, voice, words
    duration: float


class FakeDecoder:
    def decode(self, path: Path, start: float = 0.0) -> FakeAudio:
        whole = self._whole(path)
        if start <= 0:
            return whole
        # As a real decoder does: times count from ``start``.
        utterances = [
            (
                max(begin - start, 0.0),
                end - start,
                voice,
                [replace(w, start=w.start - start, end=w.end - start) for w in words if w.start >= start],
            )
            for begin, end, voice, words in whole.utterances
            if end > start
        ]
        return FakeAudio(utterances, duration=max(whole.duration - start, 0.0))

    def _whole(self, path: Path) -> FakeAudio:
        content = path.read_text(encoding="utf-8")
        if content.startswith(NOT_AUDIO):
            raise UnreadableAudio(f"{path.name} does not contain audio")
        utterances, t = [], 0.0
        for index, line in enumerate(l for l in content.splitlines() if ":" in l):  # noqa: E741
            voice, text = line.split(":", 1)
            words = []
            start = t
            for token in text.split():
                words.append(Word(t, t + WORD_SECONDS, f" {token}", segment=index, probability=0.9))
                t += WORD_SECONDS
            utterances.append((start, t, voice.strip(), words))
            t += PAUSE_SECONDS
        return FakeAudio(utterances, duration=max(t, 1.0))


class WorkerCrash(BaseException):
    """Simulates the process dying: nothing gets a chance to clean up."""


@dataclass
class FakeRecognizer:
    failures: list[str] = field(default_factory=list)  # error messages still to raise
    crash: bool = False
    during: list = field(default_factory=list)  # callables run mid-recognition
    languages_requested: list[str | None] = field(default_factory=list)

    def recognize(self, audio: FakeAudio, language, progress) -> Recognition:
        self.languages_requested.append(language)
        if self.crash:
            raise WorkerCrash()
        if self.failures:
            raise RuntimeError(self.failures.pop(0))
        for hook in self.during:
            hook(progress)
        progress(0.5)
        progress(1.0)
        return Recognition(language or "en", [w for u in audio.utterances for w in u[3]])


@dataclass
class FakeDiarizer:
    options_seen: list = field(default_factory=list)

    def diarize(self, audio: FakeAudio, options, progress) -> list[SpeakerTurn]:
        self.options_seen.append(options)
        progress(1.0)
        return [SpeakerTurn(start, end, f"voice-{voice}") for start, end, voice, _ in audio.utterances]
