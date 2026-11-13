# Run on a Mac GPU (Metal)

Docker containers on macOS run inside a Linux virtual machine and cannot use
the Mac's GPU. To use it, the **worker runs directly on the Mac**; the
database, web page and folder watcher stay in Docker.

On the Mac, Whisper runs in
[whisper.cpp](https://github.com/ggml-org/whisper.cpp) with Metal, and the
speaker model runs on PyTorch's Metal backend (`mps`).

## Prerequisites

- An Apple Silicon Mac, Docker Desktop
- `brew install ffmpeg whisper-cpp python@3.12`
- `whisper-cli --help` works. If Homebrew's package does not provide
  `whisper-cli`, build whisper.cpp from source (Metal is on by default on
  Apple Silicon) and point `WHISPER_CPP_BIN` at the binary.

## Start

```sh
cp .env.example .env                 # set HF_TOKEN as usual
docker compose -f compose.yaml -f compose.host-worker.yaml up -d --build
PYTHON=python3.12 ./scripts/host-worker.sh
```

`compose.host-worker.yaml` leaves the Docker worker out and publishes the
database on `127.0.0.1:5432` so the host worker can reach the queue.

`scripts/host-worker.sh` creates a virtual environment in `.venv-worker`
(once), reads `.env`, and starts the worker with `DEVICE=metal`. Models are
cached in `./models`. Stop it with Ctrl-C; a running job goes back to the
queue.

## Settings

Put these in `.env` if needed:

| Variable | Default | Description |
| --- | --- | --- |
| `DIARIZATION_DEVICE` | `auto` (`mps` on a Mac) | Set to `cpu` if the speaker model fails on Metal. |
| `WHISPER_CPP_BIN` | `whisper-cli` | Path of the whisper.cpp program. |
| `DB_PORT` | `5432` | Host port of the database, if 5432 is taken. |
| `HOST_DATABASE_URL` | built from `DB_PORT` | Full database address for the host worker. |

## Troubleshooting

**"whisper.cpp found no GPU it can use"** — the whisper.cpp build has no
Metal support (for example on an Intel Mac). Use a Metal build, or run with
`DEVICE=cpu ./scripts/host-worker.sh`.

**The worker cannot connect to the database** — start the stack with
`compose.host-worker.yaml`, which is what publishes the port.

**Start at login** — wrap `scripts/host-worker.sh` in a launchd agent; the
script itself stays in the foreground and logs to the terminal.

> **Not verified by the author on a Mac.** The whisper.cpp engine, the host
> worker's settings and the compose override are tested on Linux; the Metal
> path itself, the Homebrew package and pyannote on `mps` are not. Expect to
> adjust details.
