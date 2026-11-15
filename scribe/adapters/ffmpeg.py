"""AudioDecoder using the ffmpeg command line: anything ffmpeg can read
becomes 16 kHz mono float samples, the input both speech models expect."""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from scribe.application.ports import UnreadableAudio

SAMPLE_RATE = 16_000


@dataclass(frozen=True)
class PcmAudio:
    samples: np.ndarray  # float32, mono
    sample_rate: int = SAMPLE_RATE

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate


class FfmpegDecoder:
    def __init__(self, binary: str = "ffmpeg") -> None:
        self._binary = binary

    def decode(self, path: Path, start: float = 0.0) -> PcmAudio:
        if not path.is_file():
            raise UnreadableAudio(f"{path.name}: the file is missing")
        # Decoded to a temporary file rather than a pipe, so a long recording
        # is never held in memory twice.
        with tempfile.NamedTemporaryFile(suffix=".f32") as raw:
            command = [self._binary, "-nostdin", "-v", "error", "-y", "-i", str(path)]
            command += ["-vn", "-sn", "-dn", "-map", "0:a:0"]  # first audio track only
            if start > 0:
                # After -i: decode from the beginning and drop the samples
                # before ``start``. Slower than seeking, but exact, and it
                # works for a recording in progress, which has no index.
                command += ["-ss", f"{start:.3f}"]
            command += ["-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", raw.name]
            done = subprocess.run(command, capture_output=True)
            if done.returncode != 0:
                reason = done.stderr.decode("utf-8", "replace").strip().splitlines()
                detail = reason[-1] if reason else f"ffmpeg exited with status {done.returncode}"
                raise UnreadableAudio(f"{path.name}: cannot be decoded as audio ({detail})")
            samples = np.fromfile(raw.name, dtype=np.float32)
        if samples.size == 0 and start <= 0:
            raise UnreadableAudio(f"{path.name}: contains no audio")
        return PcmAudio(samples)
