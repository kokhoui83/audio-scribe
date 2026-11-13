"""WhisperCppRecognizer against a stand-in for the whisper.cpp command line.

The stand-in is a small script that records how it was called and answers in
whisper.cpp's formats, so these tests pin down the contract with the program
(options, input file, progress lines, JSON output) without needing it or a GPU.
"""

import json
import os
import sys
import time
from dataclasses import dataclass, field

import numpy as np
import pytest

from scribe.adapters.whispercpp import EngineUnavailable, RecognitionFailed, WhisperCppRecognizer
from scribe.domain.transcript import Word

OUTPUT = {
    "result": {"language": "de"},
    "transcription": [
        {
            "offsets": {"from": 0, "to": 900},
            "text": " Guten Tag.",
            "tokens": [
                {"text": "[_BEG_]", "offsets": {"from": 0, "to": 0}, "p": 0.9},
                {"text": " Guten", "offsets": {"from": 100, "to": 400}, "p": 0.8},
                {"text": " Tag", "offsets": {"from": 400, "to": 800}, "p": 0.6},
                {"text": ".", "offsets": {"from": 800, "to": 900}, "p": 1.0},
            ],
        }
    ],
}
GPU_LOG = [
    "ggml_vulkan: 0 = Radeon RX 6600 (radv) | uma: 0",
    "whisper_backend_init_gpu: using Vulkan0 backend",
]
CPU_LOG = ["ggml_vulkan: No devices found.", "whisper_backend_init_gpu: no GPU found"]

SCRIPT = """#!{python}
import json, os, sys, time, wave
here = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
with wave.open(args[args.index("-f") + 1]) as wav:
    audio = [wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getnframes()]
with open(os.path.join(here, "calls.jsonl"), "a") as log:
    log.write(json.dumps({{"args": args, "audio": audio, "pid": os.getpid()}}) + "\\n")
for line in {stderr!r}:
    print(line, file=sys.stderr, flush=True)
if {hang!r}:
    time.sleep(60)
if {output!r} is not None:
    with open(args[args.index("-of") + 1] + ".json", "wb") as out:
        out.write({output!r})
sys.exit({exit_code!r})
"""


@dataclass
class Audio:
    samples: np.ndarray = field(default_factory=lambda: np.linspace(-2.0, 2.0, 8000, dtype=np.float32))
    sample_rate: int = 16000

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate


@pytest.fixture
def cli(tmp_path):
    """Install a stand-in program; returns (path, function reading its calls)."""

    def install(*, output=OUTPUT, stderr=(), exit_code=0, hang=False):
        raw = output if isinstance(output, bytes | None) else json.dumps(output).encode()
        program = tmp_path / "whisper-cli"
        program.write_text(
            SCRIPT.format(
                python=sys.executable, stderr=list(stderr), hang=hang, output=raw, exit_code=exit_code
            )
        )
        program.chmod(0o755)
        return str(program)

    def calls():
        log = tmp_path / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    install.calls = calls
    return install


def recognizer(binary, tmp_path, **overrides):
    options = {"model": tmp_path / "ggml-tiny.bin", "use_gpu": False, "gpu_index": 0, "threads": 0}
    return WhisperCppRecognizer(binary=binary, **(options | overrides))


def option(args, name):
    return args[args.index(name) + 1]


def test_the_words_and_the_detected_language_come_back(cli, tmp_path):
    result = recognizer(cli(), tmp_path).recognize(Audio(), None, lambda fraction: None)
    assert result.language == "de"
    assert list(result.words) == [
        Word(0.1, 0.4, " Guten", probability=0.8),
        Word(0.4, 0.9, " Tag.", probability=pytest.approx(0.8)),
    ]


def test_the_audio_is_handed_over_as_a_16_bit_mono_wav_file(cli, tmp_path):
    recognizer(cli(), tmp_path).recognize(Audio(), None, lambda fraction: None)
    assert cli.calls()[0]["audio"] == [16000, 1, 2, 8000]


def test_the_language_is_detected_unless_given(cli, tmp_path):
    engine = recognizer(cli(), tmp_path)
    engine.recognize(Audio(), None, lambda fraction: None)
    engine.recognize(Audio(), "de", lambda fraction: None)
    first, second = (call["args"] for call in cli.calls())
    assert option(first, "-l") == "auto" and option(second, "-l") == "de"
    assert option(first, "-m") == str(tmp_path / "ggml-tiny.bin")
    assert "-ojf" in first  # the JSON variant that has per-token timing


def test_the_cpu_is_used_unless_a_gpu_is_asked_for(cli, tmp_path):
    binary = cli()
    recognizer(binary, tmp_path).recognize(Audio(), None, lambda fraction: None)
    recognizer(binary, tmp_path, use_gpu=True, gpu_index=1, threads=6).recognize(
        Audio(), None, lambda f: None
    )
    on_cpu, on_gpu = (call["args"] for call in cli.calls())
    assert "-ng" in on_cpu and "-t" not in on_cpu
    assert "-ng" not in on_gpu and option(on_gpu, "-dev") == "1" and option(on_gpu, "-t") == "6"


def test_progress_is_read_from_the_programs_log(cli, tmp_path):
    lines = [
        "whisper_model_load: loading model",
        "whisper_print_progress_callback: progress =   5%",
        "whisper_print_progress_callback: progress =  50%",
        "whisper_print_progress_callback: progress = 100%",
    ]
    seen = []
    recognizer(cli(stderr=lines), tmp_path).recognize(Audio(), None, seen.append)
    assert seen == [0.05, 0.5, 1.0]


def test_an_abort_raised_by_the_progress_callback_stops_the_program(cli, tmp_path):
    binary = cli(stderr=["whisper_print_progress_callback: progress =  10%"], hang=True)

    def abort(fraction):
        raise KeyError("stop")

    started = time.monotonic()
    with pytest.raises(KeyError):
        recognizer(binary, tmp_path).recognize(Audio(), None, abort)
    assert time.monotonic() - started < 20
    with pytest.raises(ProcessLookupError):
        os.kill(cli.calls()[0]["pid"], 0)


def test_a_failing_program_is_reported_with_its_last_words(cli, tmp_path):
    binary = cli(stderr=["loading", "error: failed to initialize whisper context"], exit_code=3, output=None)
    with pytest.raises(RecognitionFailed) as error:
        recognizer(binary, tmp_path).recognize(Audio(), None, lambda fraction: None)
    assert "failed to initialize whisper context" in str(error.value) and "3" in str(error.value)


def test_a_program_that_writes_no_result_is_a_failure(cli, tmp_path):
    with pytest.raises(RecognitionFailed):
        recognizer(cli(output=None), tmp_path).recognize(Audio(), None, lambda fraction: None)


def test_characters_split_across_tokens_survive_the_json_file(cli, tmp_path):
    def raw_token(data: bytes) -> bytes:
        return b'{"text": "' + data + b'", "offsets": {"from": 0, "to": 100}, "p": 0.9}'

    good = "好".encode()
    document = (
        b'{"result": {"language": "zh"}, "transcription": [{"tokens": ['
        + raw_token(good[:2])
        + b", "
        + raw_token(good[2:])
        + b"]}]}"
    )
    result = recognizer(cli(output=document), tmp_path).recognize(Audio(), "zh", lambda fraction: None)
    assert [w.text for w in result.words] == ["好"]


def test_nothing_is_left_behind_in_the_temporary_folder(cli, tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(scratch))
    recognizer(cli(), tmp_path).recognize(Audio(), None, lambda fraction: None)
    assert list(scratch.iterdir()) == []


class TestGpuCheck:
    """whisper.cpp quietly falls back to the CPU when it finds no GPU. A worker
    that was told to use one must notice at start-up instead."""

    def test_a_usable_gpu_is_named(self, cli, tmp_path):
        engine = recognizer(cli(stderr=GPU_LOG), tmp_path, use_gpu=True)
        assert engine.require_gpu() == "Vulkan0"
        call = cli.calls()[0]
        assert "-ng" not in call["args"] and call["audio"][:3] == [16000, 1, 2]

    def test_no_gpu_is_an_error_that_says_what_was_looked_for(self, cli, tmp_path):
        engine = recognizer(cli(stderr=CPU_LOG), tmp_path, use_gpu=True)
        with pytest.raises(EngineUnavailable) as error:
            engine.require_gpu()
        assert "GPU" in str(error.value) and "No devices found" in str(error.value)

    def test_a_program_that_cannot_start_is_an_error_too(self, cli, tmp_path):
        engine = recognizer(cli(stderr=["error: failed to load model"], exit_code=1, output=None), tmp_path)
        with pytest.raises(EngineUnavailable) as error:
            engine.require_gpu()
        assert "failed to load model" in str(error.value)

    def test_a_missing_program_is_an_error(self, tmp_path):
        with pytest.raises(EngineUnavailable) as error:
            recognizer(str(tmp_path / "nowhere" / "whisper-cli"), tmp_path).require_gpu()
        assert "whisper-cli" in str(error.value)
