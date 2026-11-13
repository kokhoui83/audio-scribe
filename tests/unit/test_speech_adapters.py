"""How the Whisper and pyannote adapters translate between the models' own
types and ours. The models themselves are stubbed; the real ones are exercised
by the end-to-end run described in docs/how-to/development.md."""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from scribe.adapters.pyannote import PyannoteDiarizer
from scribe.adapters.whisper import WhisperRecognizer
from scribe.adapters.whispercpp import words_from_output
from scribe.application.ports import Recognition
from scribe.domain.job import JobOptions
from scribe.domain.transcript import SpeakerTurn, Word


@dataclass
class Audio:
    samples: object = "pcm"
    sample_rate: int = 16000
    duration: float = 10.0


def w(start, end, word, probability=0.9):
    return SimpleNamespace(start=start, end=end, word=word, probability=probability)


class TestWhisperRecognizer:
    def stub(self, segments, language="en"):
        self.calls = []

        def transcribe(samples, **kwargs):
            self.calls.append((samples, kwargs))
            return iter(segments), SimpleNamespace(language=language)

        return WhisperRecognizer(transcribe)

    def test_words_keep_their_timing_text_and_segment(self):
        recognizer = self.stub(
            [
                SimpleNamespace(
                    start=0,
                    end=2,
                    text=" Hello there.",
                    words=[w(0.1, 0.5, " Hello"), w(0.5, 1.0, " there.")],
                ),
                SimpleNamespace(start=3, end=4, text=" Hi.", words=[w(3.0, 3.4, " Hi.", 0.5)]),
            ]
        )
        result = recognizer.recognize(Audio(), None, lambda fraction: None)
        assert result.language == "en"
        assert list(result.words) == [
            Word(0.1, 0.5, " Hello", probability=0.9),
            Word(0.5, 1.0, " there.", probability=0.9),
            Word(3.0, 3.4, " Hi.", probability=0.5),
        ]
        assert [word.segment for word in result.words] == [0, 0, 1]

    def test_the_model_is_asked_for_word_timestamps_and_the_given_language(self):
        recognizer = self.stub([], language="de")
        result = recognizer.recognize(Audio(), "de", lambda fraction: None)
        samples, kwargs = self.calls[0]
        assert samples == "pcm" and kwargs["language"] == "de" and kwargs["word_timestamps"] is True
        assert result.language == "de" and list(result.words) == []

    def test_a_segment_without_word_timings_becomes_one_word(self):
        recognizer = self.stub([SimpleNamespace(start=1, end=2, text=" No timings here. ", words=None)])
        assert list(recognizer.recognize(Audio(), None, lambda f: None).words) == [
            Word(1, 2, " No timings here.")
        ]

    def test_progress_follows_the_position_in_the_audio(self):
        recognizer = self.stub(
            [
                SimpleNamespace(start=0, end=2.5, text="a", words=[w(0, 1, " a")]),
                SimpleNamespace(start=5, end=20, text="b", words=[w(5, 6, " b")]),
            ]
        )
        seen = []
        recognizer.recognize(Audio(duration=10.0), None, seen.append)
        assert seen == [0.25, 1.0]

    def test_an_abort_raised_by_the_progress_callback_stops_recognition(self):
        consumed = []

        def segments():
            for n in range(3):
                consumed.append(n)
                yield SimpleNamespace(start=n, end=n + 1, text="x", words=[w(n, n + 1, " x")])

        recognizer = WhisperRecognizer(lambda samples, **kw: (segments(), SimpleNamespace(language="en")))

        def abort(fraction):
            raise KeyError("stop")

        with pytest.raises(KeyError):
            recognizer.recognize(Audio(), None, abort)
        assert consumed == [0]


class Annotation:
    def __init__(self, *tracks):
        self.tracks = tracks

    def __bool__(self):  # like pyannote's Annotation: empty means falsy
        return bool(self.tracks)

    def itertracks(self, yield_label=False):
        assert yield_label
        for start, end, label in self.tracks:
            yield SimpleNamespace(start=start, end=end), "track", label


class TestPyannoteDiarizer:
    def stub(self, output, steps=()):
        self.calls = []

        def pipeline(file, hook=None, **kwargs):
            self.calls.append((file, kwargs))
            for step in steps:
                hook(*step[:2], **step[2])
            return output

        return PyannoteDiarizer(pipeline, to_waveform=lambda samples: ("tensor", samples))

    def test_turns_come_from_the_non_overlapping_diarization_when_available(self):
        output = SimpleNamespace(
            speaker_diarization=Annotation((0, 5, "SPEAKER_00"), (4, 9, "SPEAKER_01")),
            exclusive_speaker_diarization=Annotation((0, 4.5, "SPEAKER_00"), (4.5, 9, "SPEAKER_01")),
        )
        turns = self.stub(output).diarize(Audio(), JobOptions(), lambda f: None)
        assert turns == [SpeakerTurn(0, 4.5, "SPEAKER_00"), SpeakerTurn(4.5, 9, "SPEAKER_01")]

    def test_audio_in_which_nobody_speaks_gives_no_turns(self):
        output = SimpleNamespace(speaker_diarization=Annotation(), exclusive_speaker_diarization=Annotation())
        assert self.stub(output).diarize(Audio(), JobOptions(), lambda f: None) == []

    def test_older_pipelines_that_return_a_bare_annotation_are_supported(self):
        turns = self.stub(Annotation((0, 1, "A"))).diarize(Audio(), JobOptions(), lambda f: None)
        assert turns == [SpeakerTurn(0, 1, "A")]

    def test_the_audio_is_handed_over_in_memory(self):
        self.stub(Annotation()).diarize(Audio(), JobOptions(), lambda f: None)
        file, kwargs = self.calls[0]
        assert file == {"waveform": ("tensor", "pcm"), "sample_rate": 16000} and kwargs == {}

    @pytest.mark.parametrize(
        "options, expected",
        [
            (JobOptions(num_speakers=2), {"num_speakers": 2}),
            (JobOptions(min_speakers=2, max_speakers=4), {"min_speakers": 2, "max_speakers": 4}),
            (JobOptions(num_speakers=3, min_speakers=1, max_speakers=9), {"num_speakers": 3}),
            (JobOptions(language="en", diarize=True), {}),
        ],
    )
    def test_speaker_count_hints_are_passed_on(self, options, expected):
        self.stub(Annotation()).diarize(Audio(), options, lambda f: None)
        assert self.calls[0][1] == expected

    def test_progress_advances_through_the_pipeline_steps(self):
        steps = [
            ("segmentation", None, {"total": 10, "completed": 5}),
            ("segmentation", None, {"total": 10, "completed": 10}),
            ("speaker_counting", None, {}),
            ("embeddings", None, {"total": 4, "completed": 2}),
            ("embeddings", None, {"total": 4, "completed": 4}),
            ("discrete_diarization", None, {}),
        ]
        seen = []
        self.stub(Annotation(), steps).diarize(Audio(), JobOptions(), seen.append)
        assert seen == sorted(seen) and seen[0] > 0 and seen[-1] <= 1.0
        assert len(set(seen)) >= 4


def token(text, start_ms, end_ms, p=0.9):
    return {"text": text, "offsets": {"from": start_ms, "to": end_ms}, "p": p}


def segment(*tokens):
    return {"offsets": {"from": 0, "to": 0}, "text": "", "tokens": list(tokens)}


class TestWhisperCppOutput:
    """whisper.cpp reports sub-word tokens; we need words."""

    def parse(self, *segments, language="en"):
        return words_from_output({"result": {"language": language}, "transcription": list(segments)})

    def test_tokens_are_joined_into_words_with_their_timing(self):
        result = self.parse(
            segment(
                token("[_BEG_]", 0, 0),
                token(" And", 320, 330),
                token(" so", 330, 530),
                token(",", 680, 740),
                token(" Amer", 950, 1200, p=0.5),
                token("icans", 1200, 1590, p=0.7),
                token(".", 1600, 1650, p=0.9),
                token("[_TT_525]", 1650, 1650),
            )
        )
        assert result.language == "en"
        assert list(result.words) == [
            Word(0.32, 0.33, " And", probability=0.9),
            Word(0.33, 0.74, " so,", probability=0.9),
            Word(0.95, 1.65, " Americans.", probability=pytest.approx(0.7)),
        ]

    def test_each_word_remembers_the_segment_it_came_from(self):
        result = self.parse(
            segment(token(" One", 0, 100), token(" two.", 100, 200)),
            segment(token("[_BEG_]", 0, 0)),
            segment(token(" Three.", 900, 1000)),
        )
        assert [(w.text, w.segment) for w in result.words] == [(" One", 0), (" two.", 0), (" Three.", 2)]

    def test_a_segment_never_continues_the_last_word_of_the_one_before(self):
        result = self.parse(segment(token(" One", 0, 100)), segment(token("Two", 500, 600)))
        assert [w.text for w in result.words] == [" One", "Two"]

    def test_languages_written_without_spaces_get_one_word_per_character_group(self):
        result = self.parse(segment(token("你好", 0, 400), token("世界", 400, 900)), language="zh")
        assert [(w.start, w.end, w.text) for w in result.words] == [(0.0, 0.4, "你好"), (0.4, 0.9, "世界")]

    def test_a_character_split_across_tokens_is_put_back_together(self):
        # whisper.cpp writes the raw bytes of each token, so a multi-byte
        # character can arrive in two halves.
        first, second = (
            part.decode("utf-8", "surrogateescape") for part in ("好".encode()[:2], "好".encode()[2:])
        )
        result = self.parse(
            segment(token("你", 0, 100), token(first, 100, 200), token(second, 200, 300)), language="zh"
        )
        assert [(w.start, w.end, w.text) for w in result.words] == [(0.0, 0.1, "你"), (0.1, 0.3, "好")]

    def test_no_speech_gives_no_words(self):
        result = self.parse(segment(token("[_BEG_]", 0, 0), token("[_TT_50]", 0, 0)), language="en")
        assert list(result.words) == []
        assert words_from_output({"result": {}, "transcription": []}) == Recognition(None, [])

    def test_the_marker_for_silence_is_not_speech(self):
        blank = [
            token(" [", 0, 500),
            token("BLANK", 500, 900),
            token("_", 900, 950),
            token("AUDIO", 950, 1400),
        ]
        result = self.parse(
            segment(token("[_BEG_]", 0, 0), *blank, token("]", 1400, 1500)),
            segment(token(" Hello.", 2000, 2400)),
        )
        assert [(w.text, w.segment) for w in result.words] == [(" Hello.", 1)]
