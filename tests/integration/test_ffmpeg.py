"""FfmpegDecoder against the real ffmpeg binary."""

import shutil
import subprocess

import numpy as np
import pytest

from scribe.adapters.ffmpeg import SAMPLE_RATE, FfmpegDecoder
from scribe.application.ports import UnreadableAudio

pytestmark = [
    pytest.mark.ffmpeg,
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed"),
]


def tone(path, seconds=2, extra=()):
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}:sample_rate=44100",
            "-ac",
            "2",
            *extra,
            str(path),
        ],
        check=True,
    )
    return path


@pytest.mark.parametrize(
    "name, extra",
    [
        ("a.wav", ()),
        ("a.mp3", ()),
        ("a.flac", ()),
        ("a.ogg", ()),
        ("a.opus", ()),
        ("a.m4a", ()),
        ("a.aac", ()),
        ("a.wma", ()),
        ("a.aiff", ()),
        ("a.webm", ()),
        ("a.mka", ()),
        ("phone.wav", ("-ar", "8000", "-ac", "1")),
    ],
)  # no .amr sample: this ffmpeg build can decode AMR but has no encoder to make one
def test_popular_formats_decode_to_16k_mono_float(tmp_path, name, extra):
    audio = FfmpegDecoder().decode(tone(tmp_path / name, extra=extra))
    assert audio.sample_rate == SAMPLE_RATE
    assert audio.samples.ndim == 1 and str(audio.samples.dtype) == "float32"
    assert audio.duration == pytest.approx(2.0, abs=0.15)
    assert abs(audio.samples).max() > 0.01


def test_the_audio_track_of_a_video_is_used(tmp_path):
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=64x64:rate=5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-shortest",
            str(video),
        ],
        check=True,
    )
    assert FfmpegDecoder().decode(video).duration == pytest.approx(1.0, abs=0.15)


def test_a_file_that_is_not_audio_is_unreadable(tmp_path):
    fake = tmp_path / "notes.mp3"
    fake.write_text("these are just words")
    with pytest.raises(UnreadableAudio) as error:
        FfmpegDecoder().decode(fake)
    assert "notes.mp3" in str(error.value)


def test_a_video_without_sound_is_unreadable(tmp_path):
    silent = tmp_path / "silent.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=5", str(silent)],
        check=True,
    )
    with pytest.raises(UnreadableAudio):
        FfmpegDecoder().decode(silent)


def test_a_missing_file_is_unreadable(tmp_path):
    with pytest.raises(UnreadableAudio):
        FfmpegDecoder().decode(tmp_path / "gone.mp3")


@pytest.fixture(scope="module")
def stream(tmp_path_factory):
    """20 seconds of noise as a WebM stream without an index, which is what a
    browser produces while recording."""
    path = tmp_path_factory.mktemp("stream") / "standup.webm"
    command = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anoisesrc=duration=20:color=pink:seed=7"]
    command += ["-c:a", "libopus", "-b:a", "48k", "-f", "webm", "-live", "1", "pipe:1"]
    path.write_bytes(subprocess.run(command, check=True, capture_output=True).stdout)
    return path


def shift(reference: np.ndarray, other: np.ndarray, reach: int = 400) -> int:
    """By how many samples ``other`` is displaced against ``reference``."""
    window = reference[reach : reach + SAMPLE_RATE]
    errors = [
        np.abs(window - other[reach + lag : reach + lag + SAMPLE_RATE]).mean() for lag in range(-reach, reach)
    ]
    return int(np.argmin(errors)) - reach


class TestRecordingInProgress:
    """A recording that is still being written, cut off at an arbitrary byte."""

    def test_decoding_can_start_part_of_the_way_in(self, stream):
        whole = FfmpegDecoder().decode(stream)
        rest = FfmpegDecoder().decode(stream, start=12.5)
        assert rest.duration == pytest.approx(whole.duration - 12.5, abs=0.05)
        # Word times are counted from the start offset. ffmpeg starts a few
        # milliseconds early (7 ms for Opus); what matters is that this stays
        # far below the length of a word and does not add up over passes.
        assert abs(shift(whole.samples[int(12.5 * SAMPLE_RATE) :], rest.samples)) <= 0.02 * SAMPLE_RATE

    @pytest.mark.parametrize("fraction", [0.3, 0.55, 0.9])
    def test_a_file_that_is_still_growing_is_decoded_as_far_as_it_goes(self, stream, tmp_path, fraction):
        partial = tmp_path / "standup.webm"
        content = stream.read_bytes()
        partial.write_bytes(content[: int(len(content) * fraction) + 7])
        audio = FfmpegDecoder().decode(partial)
        assert audio.duration == pytest.approx(20 * fraction, abs=1.5)

    def test_the_part_already_decoded_does_not_change_when_more_arrives(self, stream, tmp_path):
        partial = tmp_path / "standup.webm"
        content = stream.read_bytes()
        partial.write_bytes(content[: len(content) // 2])
        early = FfmpegDecoder().decode(partial)
        whole = FfmpegDecoder().decode(stream)
        assert shift(whole.samples[5 * SAMPLE_RATE :], early.samples[5 * SAMPLE_RATE :]) == 0

    def test_starting_beyond_the_end_gives_no_audio_rather_than_an_error(self, stream):
        audio = FfmpegDecoder().decode(stream, start=60.0)
        assert audio.duration == 0

    def test_a_file_with_nothing_in_it_yet_is_unreadable(self, tmp_path):
        empty = tmp_path / "standup.webm"
        empty.write_bytes(b"")
        with pytest.raises(UnreadableAudio):
            FfmpegDecoder().decode(empty)
