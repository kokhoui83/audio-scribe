"""Configuration, read from environment variables (see .env.example)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from scribe.domain.rendering import FORMATS

DEFAULT_EXTENSIONS = (
    "mp3,wav,m4a,m4b,aac,flac,ogg,oga,opus,wma,aiff,aif,amr,3gp,ac3,mka,weba,webm,mp4,mov,mkv,avi,m4v,wmv"
)
DEVICES = ("cpu", "cuda", "vulkan", "metal")
# Which Whisper implementation runs on which device. faster-whisper
# (CTranslate2) knows CPU and CUDA; whisper.cpp adds Vulkan and Metal.
ENGINES = {"faster-whisper": ("cpu", "cuda"), "whisper-cpp": ("cpu", "vulkan", "metal")}
DEFAULT_ENGINE = {
    "cpu": "faster-whisper",
    "cuda": "faster-whisper",
    "vulkan": "whisper-cpp",
    "metal": "whisper-cpp",
}
# The PyTorch device that identifies speakers. PyTorch has no Vulkan backend.
TORCH_DEVICES = ("cpu", "cuda", "mps")
DEFAULT_TORCH_DEVICE = {"cpu": "cpu", "cuda": "cuda", "vulkan": "cpu", "metal": "mps"}
GPU_BATCH_SIZE = 8


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    database_url: str
    data_dir: Path
    models_dir: Path
    output_formats: tuple[str, ...]
    archive_originals: bool
    audio_extensions: frozenset[str]
    # queue
    max_attempts: int
    retry_backoff_seconds: float
    lease_seconds: int
    heartbeat_seconds: float
    poll_seconds: float
    # watcher
    scan_seconds: float
    stable_seconds: float
    # live recording
    recording_pass_seconds: float
    recording_idle_seconds: float
    # speech models
    device: str
    speech_engine: str
    whisper_cpp_binary: str
    gpu_index: int
    whisper_model: str
    whisper_compute_type: str
    whisper_batch_size: int
    cpu_threads: int
    default_language: str | None
    diarize: bool
    diarization_model: str
    diarization_device: str
    hf_token: str | None

    @property
    def compute_type(self) -> str:
        if self.whisper_compute_type != "auto":
            return self.whisper_compute_type
        return "float16" if self.device == "cuda" else "int8"

    @property
    def batch_size(self) -> int:
        if self.whisper_batch_size > 0:
            return self.whisper_batch_size
        return GPU_BATCH_SIZE if self.device == "cuda" else 1

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        read = _Reader(env)
        device = read.choice("DEVICE", "cpu", DEVICES)
        engine = read.choice("SPEECH_ENGINE", "auto", ("auto", *ENGINES))
        if engine == "auto":
            engine = DEFAULT_ENGINE[device]
        if device not in ENGINES[engine]:
            raise ConfigError(
                f"SPEECH_ENGINE: {engine} does not run on DEVICE={device}; "
                f"it supports {', '.join(ENGINES[engine])}"
            )
        speaker_device = read.choice("DIARIZATION_DEVICE", "auto", ("auto", *TORCH_DEVICES))
        if speaker_device == "auto":
            speaker_device = DEFAULT_TORCH_DEVICE[device]
        settings = cls(
            database_url=read.text("DATABASE_URL", "postgresql://scribe:scribe@db:5432/scribe"),
            data_dir=Path(read.text("DATA_DIR", "/data")),
            models_dir=Path(read.text("MODELS_DIR", "/models")),
            output_formats=read.choices("OUTPUT_FORMATS", "md", tuple(FORMATS)),
            archive_originals=read.boolean("ARCHIVE_ORIGINALS", True),
            audio_extensions=frozenset(
                e.lstrip(".") for e in read.words("AUDIO_EXTENSIONS", DEFAULT_EXTENSIONS)
            ),
            max_attempts=read.integer("MAX_ATTEMPTS", 3, minimum=1),
            retry_backoff_seconds=read.number("RETRY_BACKOFF_SECONDS", 30, minimum=0),
            lease_seconds=read.integer("LEASE_SECONDS", 120, minimum=1),
            heartbeat_seconds=read.number("HEARTBEAT_SECONDS", 10, minimum=0.1),
            poll_seconds=read.number("POLL_SECONDS", 2, minimum=0.1),
            scan_seconds=read.number("SCAN_SECONDS", 2, minimum=0.1),
            stable_seconds=read.number("STABLE_SECONDS", 5, minimum=0),
            recording_pass_seconds=read.number("RECORDING_PASS_SECONDS", 30, minimum=1),
            recording_idle_seconds=read.number("RECORDING_IDLE_SECONDS", 120, minimum=10),
            device=device,
            speech_engine=engine,
            whisper_cpp_binary=read.text("WHISPER_CPP_BIN", "whisper-cli"),
            gpu_index=read.integer("GPU_INDEX", 0, minimum=0),
            whisper_model=read.text("WHISPER_MODEL", "large-v3-turbo"),
            whisper_compute_type=read.text("WHISPER_COMPUTE_TYPE", "auto").lower(),
            whisper_batch_size=read.integer("WHISPER_BATCH_SIZE", 0, minimum=0),
            cpu_threads=read.integer("CPU_THREADS", 0, minimum=0),
            default_language=read.text("DEFAULT_LANGUAGE", "").lower() or None,
            diarize=read.boolean("DIARIZE", True),
            diarization_model=read.text("DIARIZATION_MODEL", "pyannote/speaker-diarization-community-1"),
            diarization_device=speaker_device,
            hf_token=read.text("HF_TOKEN", "") or None,
        )
        if settings.lease_seconds <= 2 * settings.heartbeat_seconds:
            raise ConfigError(
                "LEASE_SECONDS must be more than twice HEARTBEAT_SECONDS, "
                "or healthy workers would lose their jobs"
            )
        return settings


class _Reader:
    def __init__(self, env: Mapping[str, str]) -> None:
        self._env = env

    def text(self, name: str, default: str) -> str:
        return self._env.get(name, "").strip() or default

    def words(self, name: str, default: str) -> tuple[str, ...]:
        return tuple(w.strip().lower() for w in self.text(name, default).split(",") if w.strip())

    def choice(self, name: str, default: str, allowed: tuple[str, ...]) -> str:
        value = self.text(name, default).lower()
        if value not in allowed:
            raise ConfigError(f"{name}: {value!r} is not one of {', '.join(allowed)}")
        return value

    def choices(self, name: str, default: str, allowed: tuple[str, ...]) -> tuple[str, ...]:
        values = self.words(name, default)
        for value in values:
            if value not in allowed:
                raise ConfigError(f"{name}: {value!r} is not one of {', '.join(allowed)}")
        return values

    def boolean(self, name: str, default: bool) -> bool:
        value = self.text(name, "").lower()
        if not value:
            return default
        if value in ("1", "true", "yes", "on"):
            return True
        if value in ("0", "false", "no", "off"):
            return False
        raise ConfigError(f"{name}: {value!r} is not true or false")

    def number(self, name: str, default: float, minimum: float) -> float:
        raw = self.text(name, "")
        try:
            value = float(raw) if raw else float(default)
        except ValueError:
            raise ConfigError(f"{name}: {raw!r} is not a number") from None
        if value < minimum:
            raise ConfigError(f"{name}: must be at least {minimum:g}")
        return value

    def integer(self, name: str, default: int, minimum: int) -> int:
        raw = self.text(name, "")
        try:
            value = int(raw) if raw else default
        except ValueError:
            raise ConfigError(f"{name}: {raw!r} is not a whole number") from None
        if value < minimum:
            raise ConfigError(f"{name}: must be at least {minimum}")
        return value
