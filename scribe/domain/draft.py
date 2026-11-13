"""The text of a recording so far.

A recording is transcribed in passes while it is still going on. Each pass
recognises the audio after ``position`` and adds the words that are settled.
The newest words are not: the recogniser may have heard half a sentence, so
they are recognised again in the next pass, when more audio has arrived.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from .transcript import Word

# Words that end within this much of the newest audio are not kept yet.
SETTLE_MARGIN_SECONDS = 5.0
# Speech that goes on this long without the recogniser ending a sentence is
# cut between two words instead, so a pass never grows without bound.
FORCED_CUT_SECONDS = 60.0


@dataclass(frozen=True)
class Draft:
    position: float = 0.0  # seconds of the recording whose words are settled
    language: str | None = None
    words: tuple[Word, ...] = ()

    @property
    def text(self) -> str:
        return "".join(w.text for w in self.words).strip()

    def extended(
        self,
        heard: Sequence[Word],
        *,
        seconds: float,
        language: str | None,
        final: bool,
        margin: float = SETTLE_MARGIN_SECONDS,
    ) -> Draft:
        """The draft after a pass that recognised ``heard`` in the ``seconds``
        of audio following ``position`` (word times count from there).
        ``final`` means the recording has ended, so nothing is held back."""
        heard = sorted(heard, key=lambda w: (w.start, w.end))
        kept, cut = (len(heard), seconds) if final else _settled(heard, seconds, margin)
        first_segment = self.words[-1].segment + 1 if self.words else 0
        renumbered = {s: first_segment + n for n, s in enumerate(dict.fromkeys(w.segment for w in heard))}
        new = tuple(
            replace(
                w, start=self.position + w.start, end=self.position + w.end, segment=renumbered[w.segment]
            )
            for w in heard[:kept]
        )
        return Draft(self.position + cut, self.language or language, self.words + new)

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "language": self.language,
            "words": [
                {"start": w.start, "end": w.end, "word": w.text, "segment": w.segment}
                | ({} if w.probability is None else {"probability": w.probability})
                for w in self.words
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Draft:
        data = data or {}
        return cls(
            position=data.get("position") or 0.0,
            language=data.get("language"),
            words=tuple(
                Word(
                    w["start"],
                    w["end"],
                    w["word"],
                    segment=w.get("segment", 0),
                    probability=w.get("probability"),
                )
                for w in data.get("words") or ()
            ),
        )


def _settled(heard: Sequence[Word], seconds: float, margin: float) -> tuple[int, float]:
    """How many of the words to keep, and how many seconds of the audio are
    thereby dealt with."""
    limit = seconds - margin
    if limit <= 0:
        return 0, 0.0
    if not heard or heard[-1].end <= limit:
        return len(heard), limit
    last = _last_end(heard, limit, sentences_only=True)
    if last is None and seconds > FORCED_CUT_SECONDS:
        last = _last_end(heard, limit, sentences_only=False)
    if last is None:
        return 0, 0.0
    # Cut in the pause between the two words, but not inside the margin.
    pause = (heard[last].end + heard[last + 1].start) / 2
    return last + 1, max(heard[last].end, min(pause, limit))


def _last_end(heard: Sequence[Word], limit: float, *, sentences_only: bool) -> int | None:
    """Index of the last word that ends before ``limit`` and is followed by
    another word (of another recogniser segment, if ``sentences_only``)."""
    for index in range(len(heard) - 2, -1, -1):
        if heard[index].end <= limit and (
            not sentences_only or heard[index + 1].segment != heard[index].segment
        ):
            return index
    return None
