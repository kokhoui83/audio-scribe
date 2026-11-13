"""FfmpegDecoder against the real ffmpeg binary."""

import shutil
import subprocess

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
