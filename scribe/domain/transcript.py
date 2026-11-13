"""Transcripts, and how one is assembled from recognised words and speaker turns."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

# A new paragraph starts at a recogniser segment boundary after this much
# silence, or once the paragraph has grown past this many characters.
PARAGRAPH_GAP_SECONDS = 1.5
PARAGRAPH_MAX_CHARS = 500


@dataclass(frozen=True)
class Word:
    """A recognised word. ``text`` keeps its leading space (if the language
    has one), so words concatenate back into the original text."""

    start: float
    end: float
    text: str
    # Index of the recogniser segment (roughly a sentence) the word came from.
    segment: int = field(default=0, compare=False)
    probability: float | None = None


@dataclass(frozen=True)
class SpeakerTurn:
    start: float
    end: float
    speaker: str


@dataclass(frozen=True)
class Segment:
    """A paragraph spoken by one speaker."""

    start: float
    end: float
    speaker: str | None
    words: tuple[Word, ...]

    @property
    def text(self) -> str:
        return "".join(w.text for w in self.words).strip()


@dataclass(frozen=True)
class Transcript:
    file: str
    language: str | None
    duration: float
    speakers: tuple[str, ...]
    segments: tuple[Segment, ...]
    created: str | None = None

    def with_speaker_names(self, names: dict[str, str] | None) -> Transcript:
        names = {k: v.strip() for k, v in (names or {}).items() if v and v.strip()}
        if not names:
            return self
        return replace(
            self,
            speakers=tuple(names.get(s, s) for s in self.speakers),
            segments=tuple(
                replace(s, speaker=names.get(s.speaker, s.speaker)) if s.speaker else s for s in self.segments
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "language": self.language,
            "duration": self.duration,
            "created": self.created,
            "speakers": list(self.speakers),
            "segments": [
                {
                    "start": s.start,
                    "end": s.end,
                    "speaker": s.speaker,
                    "text": s.text,
                    "words": [
                        {"start": w.start, "end": w.end, "word": w.text}
                        | ({} if w.probability is None else {"probability": w.probability})
                        for w in s.words
                    ],
                }
                for s in self.segments
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transcript:
        return cls(
            file=data["file"],
            language=data.get("language"),
            duration=data.get("duration") or 0.0,
            created=data.get("created"),
            speakers=tuple(data.get("speakers") or ()),
            segments=tuple(
                Segment(
                    start=s["start"],
                    end=s["end"],
                    speaker=s.get("speaker"),
                    words=tuple(
                        Word(w["start"], w["end"], w["word"], probability=w.get("probability"))
                        for w in s["words"]
                    ),
                )
                for s in data.get("segments") or ()
            ),
        )


def build_transcript(
    words: Iterable[Word],
    turns: Sequence[SpeakerTurn] | None,
    *,
    file: str,
    language: str | None,
    duration: float,
    created: str | None = None,
) -> Transcript:
    """``turns=None`` means speakers were not identified at all."""
    words = sorted(words, key=lambda w: (w.start, w.end))
    raw_speakers = _attribute(words, sorted(turns or (), key=lambda t: (t.start, t.end)))
    labels: dict[str, str] = {}
    segments: list[Segment] = []
    current: list[Word] = []
    current_speaker: str | None = None

    def close() -> None:
        if current and "".join(w.text for w in current).strip():
            segments.append(
                Segment(current[0].start, max(w.end for w in current), current_speaker, tuple(current))
            )

    for word, raw in zip(words, raw_speakers, strict=True):
        speaker = None if raw is None else labels.setdefault(raw, f"Speaker {len(labels) + 1}")
        if current and (speaker != current_speaker or _paragraph_break(current, word)):
            close()
            current = []
        current_speaker = speaker
        current.append(
            Word(
                round(word.start, 3),
                round(max(word.end, word.start), 3),
                word.text,
                segment=word.segment,
                probability=None if word.probability is None else round(word.probability, 3),
            )
        )
    close()
    used = {s.speaker for s in segments}
    return Transcript(
        file=file,
        language=language,
        duration=round(duration, 3),
        created=created,
        speakers=tuple(label for label in labels.values() if label in used),
        segments=tuple(segments),
    )


def _paragraph_break(paragraph: list[Word], nxt: Word) -> bool:
    last = paragraph[-1]
    if nxt.segment == last.segment:
        return False
    return (
        nxt.start - last.end > PARAGRAPH_GAP_SECONDS
        or sum(len(w.text) for w in paragraph) > PARAGRAPH_MAX_CHARS
    )


def _attribute(words: list[Word], turns: list[SpeakerTurn]) -> list[str | None]:
    """For each word, the speaker whose turns overlap it the most; a word that
    falls in a gap takes the nearest turn."""
    if not turns:
        return [None] * len(words)
    result: list[str | None] = []
    i = 0
    for w in words:
        start, end = w.start, max(w.end, w.start)
        while i < len(turns) - 1 and turns[i].end <= start:
            i += 1
        overlap: dict[str, float] = {}
        j = i
        while j < len(turns) and turns[j].start < end:
            shared = min(end, turns[j].end) - max(start, turns[j].start)
            if shared > 0:
                overlap[turns[j].speaker] = overlap.get(turns[j].speaker, 0.0) + shared
            j += 1
        if overlap:
            result.append(max(overlap, key=lambda k: overlap[k]))
            continue
        middle = (start + end) / 2
        nearby = turns[max(i - 1, 0) : i + 2]
        result.append(min(nearby, key=lambda t: _distance(t, middle)).speaker)
    return result


def _distance(turn: SpeakerTurn, moment: float) -> float:
    if turn.start <= moment <= turn.end:
        return 0.0
    return min(abs(turn.start - moment), abs(turn.end - moment))
