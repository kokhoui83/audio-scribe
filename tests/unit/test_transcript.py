"""Building a speaker-attributed transcript from words and diarization turns."""

from scribe.domain.transcript import SpeakerTurn, Transcript, Word, build_transcript


def words(*specs) -> list[Word]:
    """spec: (start, end, text) or (start, end, text, whisper_segment)."""
    return [Word(s[0], s[1], s[2], segment=s[3] if len(s) > 3 else 0) for s in specs]


def build(ws, turns=None, **kw) -> Transcript:
    return build_transcript(ws, turns, file="a.mp3", language="en", duration=60.0, **kw)


class TestSpeakerAttribution:
    def test_each_word_goes_to_the_speaker_whose_turn_overlaps_it_most(self):
        t = build(
            words((0.0, 0.5, " Hello"), (0.5, 1.0, " there."), (1.2, 1.6, " Hi"), (1.6, 2.0, " Bob.")),
            [SpeakerTurn(0.0, 1.1, "SPEAKER_01"), SpeakerTurn(1.1, 2.5, "SPEAKER_00")],
        )
        assert [(s.speaker, s.text) for s in t.segments] == [
            ("Speaker 1", "Hello there."),
            ("Speaker 2", "Hi Bob."),
        ]

    def test_speakers_are_numbered_in_order_of_first_appearance(self):
        t = build(
            words((0, 1, " a"), (1, 2, " b"), (2, 3, " c")),
            [SpeakerTurn(0, 1, "Z"), SpeakerTurn(1, 2, "A"), SpeakerTurn(2, 3, "Z")],
        )
        assert t.speakers == ("Speaker 1", "Speaker 2")
        assert [s.speaker for s in t.segments] == ["Speaker 1", "Speaker 2", "Speaker 1"]

    def test_a_word_straddling_two_turns_goes_to_the_larger_overlap(self):
        ws = words((0.0, 0.5, " first"), (0.8, 1.6, " straddle"))
        mostly_b = build(ws, [SpeakerTurn(0, 1.0, "A"), SpeakerTurn(1.0, 3, "B")])
        assert [(s.speaker, s.text) for s in mostly_b.segments] == [
            ("Speaker 1", "first"),
            ("Speaker 2", "straddle"),
        ]
        mostly_a = build(ws, [SpeakerTurn(0, 1.3, "A"), SpeakerTurn(1.3, 3, "B")])
        assert [(s.speaker, s.text) for s in mostly_a.segments] == [("Speaker 1", "first straddle")]

    def test_a_word_in_a_silent_gap_takes_the_nearest_turn(self):
        t = build(
            words((0, 1, " one"), (4.6, 4.8, " late"), (5, 6, " two")),
            [SpeakerTurn(0, 1, "A"), SpeakerTurn(5, 6, "B")],
        )
        assert [(s.speaker, s.text) for s in t.segments] == [("Speaker 1", "one"), ("Speaker 2", "late two")]

    def test_words_before_the_first_and_after_the_last_turn_are_still_attributed(self):
        t = build(words((0, 0.2, " early"), (9, 9.5, " late")), [SpeakerTurn(1, 2, "A")])
        assert [s.speaker for s in t.segments] == ["Speaker 1"]

    def test_without_diarization_there_are_no_speakers(self):
        t = build(words((0, 1, " just"), (1, 2, " text")), None)
        assert t.speakers == ()
        assert [(s.speaker, s.text) for s in t.segments] == [(None, "just text")]

    def test_diarization_that_found_no_turns_leaves_words_unattributed(self):
        assert build(words((0, 1, " hm")), []).segments[0].speaker is None


class TestParagraphs:
    def test_one_speaker_stays_in_one_paragraph_across_short_pauses(self):
        t = build(words((0, 1, " One.", 0), (1.5, 2.5, " Two.", 1)))
        assert [s.text for s in t.segments] == ["One. Two."]

    def test_a_long_pause_between_whisper_segments_starts_a_new_paragraph(self):
        t = build(words((0, 1, " One.", 0), (5, 6, " Two.", 1)))
        assert [(s.start, s.end, s.text) for s in t.segments] == [(0, 1, "One."), (5, 6, "Two.")]

    def test_a_long_monologue_is_split_at_a_whisper_segment_boundary(self):
        long_sentence = [(i * 0.1, i * 0.1 + 0.1, " word", 0) for i in range(120)]
        t = build(words(*long_sentence, (12.0, 12.1, " Next.", 1), (12.1, 12.2, " More.", 1)))
        assert len(t.segments) == 2 and t.segments[1].text == "Next. More."

    def test_languages_without_spaces_are_joined_as_given(self):
        assert build(words((0, 1, "你"), (1, 2, "好"))).segments[0].text == "你好"

    def test_no_words_means_no_segments(self):
        t = build([], [SpeakerTurn(0, 1, "A")])
        assert t.segments == () and t.speakers == ()


class TestSerialisation:
    def test_a_transcript_survives_a_round_trip_through_a_dict(self):
        t = build(
            words((0, 1, " Hi"), (1, 2, " yo")),
            [SpeakerTurn(0, 1, "A"), SpeakerTurn(1, 2, "B")],
            created="2026-01-01T00:00:00+00:00",
        )
        assert Transcript.from_dict(t.to_dict()) == t

    def test_the_dict_form_is_plain_json_data(self):
        d = build(words((0, 1, " Hi")), [SpeakerTurn(0, 1, "A")]).to_dict()
        assert d["speakers"] == ["Speaker 1"]
        assert d["segments"][0] == {
            "start": 0,
            "end": 1,
            "speaker": "Speaker 1",
            "text": "Hi",
            "words": [{"start": 0, "end": 1, "word": " Hi"}],
        }

    def test_custom_names_replace_labels_and_blank_names_are_ignored(self):
        t = build(words((0, 1, " Hi"), (1, 2, " yo")), [SpeakerTurn(0, 1, "A"), SpeakerTurn(1, 2, "B")])
        named = t.with_speaker_names({"Speaker 1": "Alice", "Speaker 2": " "})
        assert named.speakers == ("Alice", "Speaker 2")
        assert [s.speaker for s in named.segments] == ["Alice", "Speaker 2"]
