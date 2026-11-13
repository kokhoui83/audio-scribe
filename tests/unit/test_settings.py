"""Configuration from environment variables."""

from pathlib import Path

import pytest

from scribe.settings import ConfigError, Settings


def test_defaults_work_without_any_configuration():
    s = Settings.from_env({})
    assert s.data_dir == Path("/data")
    assert s.output_formats == ("md",)
    assert s.archive_originals is True and s.diarize is True
    assert (s.device, s.whisper_model, s.default_language, s.hf_token) == (
        "cpu",
        "large-v3-turbo",
        None,
        None,
    )
    assert (s.max_attempts, s.lease_seconds, s.stable_seconds) == (3, 120, 5.0)
    assert {"mp3", "wav", "m4a", "flac", "ogg", "opus", "mp4"} <= s.audio_extensions


def test_blank_values_mean_default():
    # docker compose passes unset variables through as empty strings
    s = Settings.from_env({"OUTPUT_FORMATS": "", "MAX_ATTEMPTS": " ", "DIARIZE": "", "DEVICE": ""})
    assert (s.output_formats, s.max_attempts, s.diarize, s.device) == (("md",), 3, True, "cpu")


def test_values_are_parsed():
    s = Settings.from_env(
        {
            "DATA_DIR": "/srv/audio",
            "OUTPUT_FORMATS": "md, JSON ,srt",
            "ARCHIVE_ORIGINALS": "false",
            "DIARIZE": "0",
            "DEVICE": "CUDA",
            "DEFAULT_LANGUAGE": "DE",
            "HF_TOKEN": " hf_x ",
            "MAX_ATTEMPTS": "5",
            "AUDIO_EXTENSIONS": ".mp3, WAV",
            "WHISPER_BATCH_SIZE": "4",
        }
    )
    assert s.data_dir == Path("/srv/audio")
    assert s.output_formats == ("md", "json", "srt")
    assert (s.archive_originals, s.diarize, s.device, s.default_language) == (False, False, "cuda", "de")
    assert (s.hf_token, s.max_attempts, s.whisper_batch_size) == ("hf_x", 5, 4)
    assert s.audio_extensions == frozenset({"mp3", "wav"})


@pytest.mark.parametrize(
    "env",
    [
        {"OUTPUT_FORMATS": "md,docx"},
        {"DEVICE": "tpu"},
        {"MAX_ATTEMPTS": "many"},
        {"MAX_ATTEMPTS": "0"},
        {"DIARIZE": "perhaps"},
        {"LEASE_SECONDS": "5", "HEARTBEAT_SECONDS": "10"},
    ],
)
def test_mistakes_are_reported_with_the_variable_name(env):
    with pytest.raises(ConfigError) as error:
        Settings.from_env(env)
    assert any(name in str(error.value) for name in env)


def test_compute_type_and_batch_size_follow_the_device():
    cpu, gpu = Settings.from_env({}), Settings.from_env({"DEVICE": "cuda"})
    assert (cpu.compute_type, cpu.batch_size) == ("int8", 1)
    assert (gpu.compute_type, gpu.batch_size) == ("float16", 8)
    custom = Settings.from_env({"WHISPER_COMPUTE_TYPE": "float32", "WHISPER_BATCH_SIZE": "2"})
    assert (custom.compute_type, custom.batch_size) == ("float32", 2)
