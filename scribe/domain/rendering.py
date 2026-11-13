"""Turn a Transcript into text in one of the supported output formats."""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape

from .transcript import Transcript

# format -> media type
FORMATS: dict[str, str] = {
    "md": "text/markdown",
    "txt": "text/plain",
    "json": "application/json",
    "srt": "application/x-subrip",
    "vtt": "text/vtt",
}

CUE_MAX_CHARS = 84
CUE_MAX_SECONDS = 7.0
CUE_GAP_SECONDS = 1.0
CUE_MIN_SECONDS = 0.5


def render(transcript: Transcript, fmt: str, speaker_names: dict[str, str] | None = None) -> str:
    try:
        renderer = _RENDERERS[fmt]
    except KeyError:
        raise ValueError(f"unknown format {fmt!r}; choose from {', '.join(FORMATS)}") from None
    return renderer(transcript.with_speaker_names(speaker_names))


def clock(seconds: float) -> str:
    s = int(max(seconds, 0))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _timestamp(seconds: float, separator: str) -> str:
    ms = int(round(max(seconds, 0) * 1000))
    hours, minutes, secs = ms // 3_600_000, ms % 3_600_000 // 60_000, ms % 60_000 // 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{ms % 1000:03d}"


def _markdown(t: Transcript) -> str:
    lines = [f"# {t.file or 'Transcript'}", "", f"- **Duration:** {clock(t.duration)}"]
    if t.language:
        lines.append(f"- **Language:** {t.language}")
    if t.speakers:
        lines.append(f"- **Speakers:** {len(t.speakers)} ({', '.join(t.speakers)})")
    if t.created:
        lines.append(f"- **Transcribed:** {t.created}")
    lines += ["", "---", ""]
    if not t.segments:
        lines += ["_No speech detected._", ""]
    for s in t.segments:
        who = f"**{s.speaker}** " if s.speaker else ""
        lines += [f"{who}`[{clock(s.start)}]`", "", s.text, ""]
    return "\n".join(lines)


def _plain_text(t: Transcript) -> str:
    return (
        "\n\n".join(f"[{clock(s.start)}]{f' {s.speaker}:' if s.speaker else ''} {s.text}" for s in t.segments)
        + "\n"
    )


def _json(t: Transcript) -> str:
    return json.dumps(t.to_dict(), ensure_ascii=False, indent=2) + "\n"


@dataclass
class _Cue:
    start: float
    end: float
    speaker: str | None
    text: str


def _cues(t: Transcript) -> list[_Cue]:
    """Subtitle-sized pieces: short enough to read, never spanning two speakers."""
    cues: list[_Cue] = []
    for segment in t.segments:
        cue: _Cue | None = None
        for w in segment.words:
            if cue is not None and (
                len((cue.text + w.text).strip()) > CUE_MAX_CHARS
                or w.end - cue.start > CUE_MAX_SECONDS
                or w.start - cue.end > CUE_GAP_SECONDS
            ):
                cue = None
            if cue is None:
                cue = _Cue(w.start, w.end, segment.speaker, "")
                cues.append(cue)
            cue.text += w.text
            cue.end = max(cue.end, w.end)
    for cue in cues:
        cue.text = cue.text.strip()
        if cue.end <= cue.start:
            cue.end = cue.start + CUE_MIN_SECONDS
    return [c for c in cues if c.text]


def _srt(t: Transcript) -> str:
    return "\n".join(
        f"{n}\n{_timestamp(c.start, ',')} --> {_timestamp(c.end, ',')}\n"
        f"{f'[{c.speaker}] ' if c.speaker else ''}{c.text}\n"
        for n, c in enumerate(_cues(t), 1)
    )


def _vtt(t: Transcript) -> str:
    lines = ["WEBVTT", ""]
    for c in _cues(t):
        voice = f"<v {escape(c.speaker, quote=False)}>" if c.speaker else ""
        lines += [
            f"{_timestamp(c.start, '.')} --> {_timestamp(c.end, '.')}",
            voice + escape(c.text, quote=False),
            "",
        ]
    return "\n".join(lines)


_RENDERERS = {"md": _markdown, "txt": _plain_text, "json": _json, "srt": _srt, "vtt": _vtt}
