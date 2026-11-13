"""Transcript output formats."""

import json

import pytest

from scribe.domain.rendering import FORMATS, render
from scribe.domain.transcript import SpeakerTurn, Transcript, Word, build_transcript


def conversation() -> Transcript:
    return build_transcript(
        [
            Word(1.0, 1.5, " Hello"),
            Word(1.5, 2.25, " there."),
            Word(3725.0, 3725.5, " Hi"),
            Word(3725.5, 3726.0, " <Bob>."),
        ],
        [SpeakerTurn(0, 3, "A"), SpeakerTurn(3700, 3800, "B")],
        file="meeting.mp3",
        language="en",
        duration=3800.0,
        created="2026-01-01T10:00:00+00:00",
    )


def monologue() -> Transcript:
    return build_transcript(
        [Word(0, 1, " Just"), Word(1, 2, " me.")], None, file="memo.wav", language="de", duration=2
    )


def empty() -> Transcript:
    return build_transcript([], None, file="silence.wav", language="en", duration=5)


def test_the_supported_formats_are_markdown_text_json_srt_and_vtt():
    assert set(FORMATS) == {"md", "txt", "json", "srt", "vtt"}


def test_an_unknown_format_is_rejected():
    with pytest.raises(ValueError):
        render(conversation(), "docx")


class TestMarkdown:
    def test_it_has_a_header_and_one_block_per_speaker_turn(self):
        md = render(conversation(), "md")
        assert md.startswith("# meeting.mp3\n")
        assert "- **Duration:** 01:03:20" in md
        assert "- **Language:** en" in md
        assert "- **Speakers:** 2 (Speaker 1, Speaker 2)" in md
        assert "**Speaker 1** `[00:00:01]`\n\nHello there.\n" in md
        assert "**Speaker 2** `[01:02:05]`\n\nHi <Bob>.\n" in md

    def test_without_speakers_blocks_only_carry_a_timestamp(self):
        md = render(monologue(), "md")
        assert "Speakers" not in md and "`[00:00:00]`\n\nJust me.\n" in md and "**" not in md.split("---")[1]

    def test_an_empty_transcript_says_so(self):
        assert "_No speech detected._" in render(empty(), "md")


class TestPlainText:
    def test_one_line_per_turn_with_time_and_speaker(self):
        assert render(conversation(), "txt") == (
            "[00:00:01] Speaker 1: Hello there.\n\n[01:02:05] Speaker 2: Hi <Bob>.\n"
        )

    def test_without_speakers(self):
        assert render(monologue(), "txt") == "[00:00:00] Just me.\n"


class TestJson:
    def test_it_is_the_transcript_with_word_timings(self):
        data = json.loads(render(conversation(), "json"))
        assert data["file"] == "meeting.mp3" and data["speakers"] == ["Speaker 1", "Speaker 2"]
        assert data["segments"][0]["words"][0] == {"start": 1.0, "end": 1.5, "word": " Hello"}

    def test_non_ascii_text_is_kept_readable(self):
        t = build_transcript([Word(0, 1, "你好")], None, file="a", language="zh", duration=1)
        assert "你好" in render(t, "json")


class TestSubtitles:
    def test_srt_numbers_cues_and_prefixes_the_speaker(self):
        assert render(conversation(), "srt") == (
            "1\n00:00:01,000 --> 00:00:02,250\n[Speaker 1] Hello there.\n\n"
            "2\n01:02:05,000 --> 01:02:06,000\n[Speaker 2] Hi <Bob>.\n"
        )

    def test_vtt_uses_voice_tags_and_escapes_markup(self):
        assert render(conversation(), "vtt") == (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:02.250\n<v Speaker 1>Hello there.\n\n"
            "01:02:05.000 --> 01:02:06.000\n<v Speaker 2>Hi &lt;Bob&gt;.\n"
        )

    def test_long_speech_is_cut_into_readable_cues(self):
        ws = [Word(i * 0.5, i * 0.5 + 0.5, f" word{i}") for i in range(60)]
        t = build_transcript(ws, None, file="a", language="en", duration=30)
        cues = [c for c in render(t, "srt").strip().split("\n\n")]
        assert len(cues) > 3
        for cue in cues:
            assert len(cue.split("\n")[2]) <= 84

    def test_a_cue_never_has_zero_length(self):
        t = build_transcript([Word(2.0, 2.0, " Hm")], None, file="a", language="en", duration=3)
        assert "00:00:02,000 --> 00:00:02,500" in render(t, "srt")

    def test_empty_transcripts_give_empty_subtitles(self):
        assert render(empty(), "srt") == "" and render(empty(), "vtt") == "WEBVTT\n"


class TestSpeakerNames:
    @pytest.mark.parametrize("fmt", FORMATS)
    def test_custom_names_appear_in_every_format(self, fmt):
        out = render(conversation(), fmt, {"Speaker 1": "Alice"})
        assert "Alice" in out and "Speaker 1" not in out and "Speaker 2" in out
