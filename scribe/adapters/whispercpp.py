"""SpeechRecognizer using Whisper through the whisper.cpp command line.

whisper.cpp runs on GPUs that faster-whisper cannot use: anything with a
Vulkan driver (AMD, Intel, ...) and Apple GPUs through Metal. It is run as a
separate program per recording, like ffmpeg, so a misbehaving GPU driver can
take down that program but not the worker.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
import wave
from collections import deque
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np

from scribe.application.ports import Progress, Recognition
from scribe.domain.transcript import Word

log = logging.getLogger(__name__)

MODEL_REPOSITORY = "ggerganov/whisper.cpp"  # on Hugging Face; public, no token needed

_PROGRESS = re.compile(r"progress\s*=\s*(\d+)%")
_BACKEND = re.compile(r"whisper_backend_init_gpu: using (\S+) backend")
_GPU_TALK = re.compile(r"ggml_vulkan|ggml_metal|no GPU found")
_SPECIAL_TOKEN = re.compile(r"^\[_[^\]]*\]$")  # [_BEG_], [_TT_525], ...
_SILENCE_MARKER = "[BLANK_AUDIO]"  # what whisper.cpp writes for a stretch without speech
_KEPT_LOG_LINES = 200
# Scripts written without spaces between words: Thai, Lao, Myanmar, Khmer,
# Japanese kana, Chinese characters.
_UNSPACED = ((0x0E00, 0x0EFF), (0x1000, 0x109F), (0x1780, 0x17FF), (0x3040, 0x30FF), (0x3400, 0x9FFF),
             (0x20000, 0x3FFFF))  # fmt: skip


class EngineUnavailable(Exception):
    """whisper.cpp cannot be used as configured; the message says why."""


class RecognitionFailed(Exception):
    """whisper.cpp did not produce a transcript for this recording."""


class WhisperCppRecognizer:
    def __init__(self, *, binary: str, model: Path, use_gpu: bool, gpu_index: int, threads: int) -> None:
        self._binary = binary
        self._model = model
        self._use_gpu = use_gpu
        self._gpu_index = gpu_index
        self._threads = threads

    def recognize(self, audio: Any, language: str | None, progress: Progress) -> Recognition:
        with tempfile.TemporaryDirectory(prefix="scribe-whispercpp-") as folder:
            result = Path(folder) / "result"
            _write_wav(Path(folder) / "audio.wav", audio.samples, audio.sample_rate)
            try:
                status, lines = self._run(Path(folder) / "audio.wav", result, language, progress)
            except OSError as exc:
                raise RecognitionFailed(f"{self._binary} could not be started: {exc}") from exc
            if status != 0:
                raise RecognitionFailed(f"whisper.cpp exited with status {status}: {_last(lines)}")
            try:
                # Tokens are written as raw bytes, so a character split over
                # two tokens is not valid UTF-8 until they are joined again.
                document = json.loads(result.with_suffix(".json").read_text("utf-8", "surrogateescape"))
            except (OSError, ValueError) as exc:
                raise RecognitionFailed(f"whisper.cpp wrote no usable result ({exc})") from exc
        return words_from_output(document)

    def require_gpu(self) -> str:
        """Check that whisper.cpp really computes on a GPU and return the
        device's name. Without this it would quietly fall back to the CPU."""
        silence = np.zeros(16_000, dtype=np.float32)
        with tempfile.TemporaryDirectory(prefix="scribe-whispercpp-") as folder:
            _write_wav(Path(folder) / "audio.wav", silence, 16_000)
            try:
                status, lines = self._run(Path(folder) / "audio.wav", Path(folder) / "result", "en", _ignore)
            except OSError as exc:
                raise EngineUnavailable(f"{self._binary} could not be started: {exc}") from exc
        if status != 0:
            raise EngineUnavailable(f"whisper.cpp exited with status {status}: {_last(lines)}")
        for line in lines:
            if found := _BACKEND.search(line):
                return found.group(1)
        said = "; ".join(line for line in lines if _GPU_TALK.search(line)) or "nothing about a GPU"
        raise EngineUnavailable(f"whisper.cpp found no GPU it can use. It reported: {said}")

    def _run(
        self, wav: Path, result: Path, language: str | None, progress: Progress
    ) -> tuple[int, list[str]]:
        command = [self._binary, "-m", str(self._model), "-f", str(wav), "-l", language or "auto"]
        command += ["-ojf", "-of", str(result), "-pp"]  # full JSON to a file, progress to the log
        command += ["-dev", str(self._gpu_index)] if self._use_gpu else ["-ng"]
        if self._threads:
            command += ["-t", str(self._threads)]
        lines: deque[str] = deque(maxlen=_KEPT_LOG_LINES)
        process = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace"
        )
        try:
            assert process.stderr is not None
            for line in process.stderr:
                if line.strip():
                    lines.append(line.strip())
                # Reporting progress is also what lets the caller abort.
                if step := _PROGRESS.search(line):
                    progress(min(int(step.group(1)) / 100, 1.0))
            return process.wait(), list(lines)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if process.stderr is not None:
                process.stderr.close()


def words_from_output(document: dict[str, Any]) -> Recognition:
    """Turn whisper.cpp's "full JSON" output into words."""
    words: list[Word] = []
    for index, segment in enumerate(document.get("transcription") or ()):
        group: list[_Piece] = []
        for piece in _pieces(segment.get("tokens") or ()):
            if group and _starts_word(piece.text):
                words.append(_word(group, index))
                group = []
            group.append(piece)
        if group:
            words.append(_word(group, index))
    words = [word for word in words if word.text.strip() != _SILENCE_MARKER]
    return Recognition((document.get("result") or {}).get("language"), words)


class _Piece:
    """One or more tokens that together are complete text."""

    def __init__(self, text: str, start: float, end: float, probabilities: list[float]) -> None:
        self.text = text
        self.start = start
        self.end = end
        self.probabilities = probabilities


def _pieces(tokens: Iterable[dict[str, Any]]) -> Iterable[_Piece]:
    pending: _Piece | None = None
    for token in tokens:
        text = token.get("text") or ""
        if not text or _SPECIAL_TOKEN.match(text.strip()):
            continue
        start, end = token["offsets"]["from"] / 1000, token["offsets"]["to"] / 1000
        probability = [token["p"]] if "p" in token else []
        if pending is None:
            pending = _Piece(text, start, end, probability)
        else:
            pending = _Piece(pending.text + text, pending.start, end, pending.probabilities + probability)
        repaired = _repair(pending.text)
        if repaired is not None:
            pending.text = repaired
            yield pending
            pending = None
    if pending is not None:  # half a character with nothing to complete it
        pending.text = pending.text.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
        yield pending


def _repair(text: str) -> str | None:
    """The text with split characters rejoined, or None while a part is missing."""
    try:
        return text.encode("utf-8", "surrogateescape").decode("utf-8")
    except UnicodeDecodeError:
        return None


def _starts_word(text: str) -> bool:
    first = text[0]
    return first.isspace() or any(low <= ord(first) <= high for low, high in _UNSPACED)


def _word(group: list[_Piece], segment: int) -> Word:
    probabilities = [p for piece in group for p in piece.probabilities]
    return Word(
        group[0].start,
        max(piece.end for piece in group),
        "".join(piece.text for piece in group),
        segment=segment,
        probability=sum(probabilities) / len(probabilities) if probabilities else None,
    )


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())


def _last(lines: list[str]) -> str:
    return lines[-1] if lines else "it said nothing"


def _ignore(fraction: float) -> None:
    pass


def load(
    *, binary: str, model: str, device: str, gpu_index: int, cpu_threads: int, cache_dir: Path
) -> WhisperCppRecognizer:
    """Find (downloading on first use) the model file and check that
    whisper.cpp works on the requested device."""
    recognizer = WhisperCppRecognizer(
        binary=binary,
        model=_model_file(model, cache_dir),
        use_gpu=device != "cpu",
        gpu_index=gpu_index,
        threads=cpu_threads,
    )
    if device != "cpu":
        log.info("whisper.cpp computes on %s", recognizer.require_gpu())
    return recognizer


def _model_file(model: str, cache_dir: Path) -> Path:
    """``model`` is a name such as large-v3-turbo, or the path of a ggml file."""
    if Path(model).is_file():
        return Path(model)
    from huggingface_hub import hf_hub_download

    try:
        return Path(hf_hub_download(MODEL_REPOSITORY, f"ggml-{model}.bin", cache_dir=str(cache_dir)))
    except Exception as exc:
        raise EngineUnavailable(
            f"The Whisper model ggml-{model}.bin could not be downloaded from "
            f"https://hf.co/{MODEL_REPOSITORY} ({type(exc).__name__}: {exc})"
        ) from exc
