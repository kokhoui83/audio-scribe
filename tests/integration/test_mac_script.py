"""scripts/mac.sh against stand-ins for Docker, Homebrew, uv and the worker.

The stand-ins record how they were called, so these tests pin down what the
one command does on a Mac (QR-09) without a Mac, Docker or any speech model:
which tools it installs, how it starts the stack, and that the worker runs in
the background until `down`. Homebrew, Metal and the real worker are not
exercised here.
"""

import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOST_TOOLS = ("uv", "whisper-cli")  # ffmpeg is part of the test image, so it is never missing

RECORD = '#!/bin/sh\necho "{name} $*" >> "$CALLS"\n'
DOCKER = RECORD + 'if [ "$1" = info ]; then exit "${{DOCKER_INFO_EXIT:-0}}"; fi\n'
# Homebrew "installs" by putting the tools on the PATH.
BREW = RECORD + 'cp "$SHELF"/* "$(dirname "$0")"/\n'
# `uv venv ... <dir>` creates the environment; its python is the worker stand-in.
UV = RECORD + (
    'if [ "$1" = venv ]; then\n'
    '  for venv in "$@"; do :; done\n'
    '  mkdir -p "$venv/bin" && cp "$SHELF/../worker" "$venv/bin/python"\n'
    "fi\n"
)
# Asked for its version (`python -c ...`), it answers through the exit status.
VERSION_CHECK = 'if [ "$1" = -c ]; then exit "${{PYTHON_IS_OLD:-0}}"; fi\n'
WORKER = RECORD.replace("\n", "\n" + VERSION_CHECK, 1) + (
    'echo "environment device=$DEVICE database=$DATABASE_URL" >> "$CALLS"\n'
    'if [ -n "${{WORKER_FAILS:-}}" ]; then echo "no such model" >&2; exit 1; fi\n'
    "echo worker starting\n"
    "exec sleep 60\n"
)


@dataclass
class Mac:
    """A copy of the repository's scripts with stand-in programs on the PATH."""

    root: Path
    bin: Path
    env: dict[str, str]

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sh", str(self.root / "scripts" / "mac.sh"), *args],
            env={**self.env, **env},
            capture_output=True,
            text=True,
            timeout=60,
        )

    def calls(self, program: str) -> list[str]:
        log = Path(self.env["CALLS"])
        lines = log.read_text().splitlines() if log.exists() else []
        return [line for line in lines if line.startswith(program + " ")]

    def worker_pid(self) -> int | None:
        pid_file = self.root / ".host-worker" / "worker.pid"
        return int(pid_file.read_text()) if pid_file.exists() else None

    def uninstall_host_tools(self) -> None:
        for tool in HOST_TOOLS:
            (self.bin / tool).unlink()


def is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def write_program(path: Path, template: str, name: str = "") -> None:
    path.write_text(template.format(name=name or path.name))
    path.chmod(0o755)


@pytest.fixture
def mac(tmp_path):
    root, bin_dir, shelf = tmp_path / "repo", tmp_path / "bin", tmp_path / "shelf"
    shutil.copytree(REPO / "scripts", root / "scripts")
    shutil.copy(REPO / ".env.example", root / ".env.example")
    (root / ".env").write_text("HF_TOKEN=hf_test\n")
    (root / "requirements").mkdir()
    (root / "requirements" / "host-worker.txt").write_text("")
    bin_dir.mkdir()
    shelf.mkdir()
    write_program(bin_dir / "docker", DOCKER)
    write_program(bin_dir / "brew", BREW)
    write_program(tmp_path / "worker", WORKER, name="python")
    for tool in HOST_TOOLS:
        write_program(shelf / tool, UV if tool == "uv" else RECORD)
        shutil.copy(shelf / tool, bin_dir / tool)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "CALLS": str(tmp_path / "calls.log"),
        "SHELF": str(shelf),
    }
    mac = Mac(root, bin_dir, env)
    yield mac
    pid = mac.worker_pid()
    if pid and is_running(pid):
        os.kill(pid, signal.SIGKILL)


def test_up_starts_the_stack_without_the_docker_worker_and_a_worker_in_the_background(mac):
    result = mac.run("up")

    assert result.returncode == 0, result.stderr
    assert "docker compose -f compose.yaml -f compose.host-worker.yaml up -d --build" in mac.calls("docker")
    assert is_running(mac.worker_pid())
    assert mac.calls("python") == ["python -m scribe.entrypoints.worker"]
    assert "worker starting" in (mac.root / ".host-worker" / "worker.log").read_text()
    assert "http://localhost:8090" in result.stdout


def test_the_worker_reaches_the_database_through_the_port_published_on_the_host(mac):
    mac.run("up")

    assert "database=postgresql://scribe:scribe@127.0.0.1:5432/scribe" in mac.calls("environment")[0]


def test_up_installs_missing_tools_with_homebrew(mac):
    mac.uninstall_host_tools()

    result = mac.run("up")

    assert result.returncode == 0, result.stderr
    assert mac.calls("brew") == ["brew bundle install --file=Brewfile"]
    assert is_running(mac.worker_pid())


def test_up_leaves_homebrew_alone_when_the_tools_are_there(mac):
    mac.run("up")

    assert mac.calls("brew") == []


def test_up_accepts_a_whisper_cpp_program_named_in_the_settings(mac):
    (mac.bin / "whisper-cli").rename(mac.bin / "my-whisper")
    (mac.root / ".env").write_text("HF_TOKEN=hf_test\nWHISPER_CPP_BIN=my-whisper\n")

    result = mac.run("up")

    assert result.returncode == 0, result.stderr
    assert mac.calls("brew") == []


def test_up_without_homebrew_says_how_to_get_it(mac):
    mac.uninstall_host_tools()
    (mac.bin / "brew").unlink()

    result = mac.run("up")

    assert result.returncode != 0
    assert "https://brew.sh" in result.stderr
    assert mac.calls("docker compose") == []


def test_up_creates_the_python_environment_with_uv_only_once(mac):
    mac.run("up")
    mac.run("down")
    mac.run("up")

    assert len([call for call in mac.calls("uv") if call.startswith("uv venv")]) == 1


def test_up_rebuilds_a_python_environment_that_is_too_old(mac):
    mac.run("up")
    mac.run("down")

    result = mac.run("up", PYTHON_IS_OLD="1")

    assert result.returncode == 0, result.stderr
    assert "older than 3.14" in result.stdout
    assert len([call for call in mac.calls("uv") if call.startswith("uv venv")]) == 2


def test_up_twice_keeps_the_worker_that_is_running(mac):
    mac.run("up")
    first = mac.worker_pid()

    result = mac.run("up")

    assert result.returncode == 0, result.stderr
    assert mac.worker_pid() == first
    assert len(mac.calls("python")) == 1


def test_up_stops_when_docker_is_not_running(mac):
    result = mac.run("up", DOCKER_INFO_EXIT="1")

    assert result.returncode != 0
    assert "Start Docker Desktop" in result.stderr
    assert mac.worker_pid() is None


def test_first_up_creates_the_settings_file_and_asks_for_the_token(mac):
    (mac.root / ".env").unlink()

    result = mac.run("up")

    assert result.returncode != 0
    assert (mac.root / ".env").read_text() == (mac.root / ".env.example").read_text()
    assert "HF_TOKEN" in result.stderr
    assert mac.calls("docker") == []


def test_up_shows_the_log_of_a_worker_that_stops_at_once(mac):
    result = mac.run("up", WORKER_FAILS="1")

    assert result.returncode != 0
    assert "no such model" in result.stderr
    assert mac.worker_pid() is None


def test_down_stops_the_worker_and_the_stack(mac):
    mac.run("up")
    pid = mac.worker_pid()

    result = mac.run("down")

    assert result.returncode == 0, result.stderr
    deadline = time.monotonic() + 5
    while is_running(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not is_running(pid)
    assert mac.worker_pid() is None
    assert mac.calls("docker")[-1] == "docker compose -f compose.yaml -f compose.host-worker.yaml down"


def test_status_says_whether_the_worker_runs(mac):
    assert "worker: not running" in mac.run("status").stdout

    mac.run("up")

    assert f"worker: running (pid {mac.worker_pid()})" in mac.run("status").stdout


def test_an_unknown_command_shows_the_usage(mac):
    result = mac.run("launch")

    assert result.returncode != 0
    assert "up" in result.stderr and "down" in result.stderr
