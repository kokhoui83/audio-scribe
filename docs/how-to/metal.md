# Run on a Mac GPU (Metal)

Docker containers on macOS run inside a Linux virtual machine and cannot use
the Mac's GPU. To use it, the **worker runs directly on the Mac**; the
database, web page and folder watcher stay in Docker. One script takes care
of both.

On the Mac, Whisper runs in
[whisper.cpp](https://github.com/ggml-org/whisper.cpp) with Metal, and the
speaker model runs on PyTorch's Metal backend (`mps`).

## Prerequisites

- An Apple Silicon Mac
- [Docker Desktop](https://www.docker.com/products/docker-desktop/), running
- [Homebrew](https://brew.sh)

Everything else is installed by the script.

## Start

```sh
./scripts/mac.sh up
```

The first time, this creates `.env` and stops: put your Hugging Face token
in it (`HF_TOKEN=hf_...`, see [Getting started](getting-started.md)) or set
`DIARIZE=false`, then run the command again. It then:

1. installs `ffmpeg`, `whisper-cpp` and `uv` with Homebrew (the
   [`Brewfile`](../../Brewfile)), if any of them is missing;
2. creates the worker's Python environment in `.venv-worker` (`uv` fetches
   Python 3.12 and the packages; once, a few minutes);
3. starts the database, the web page and the folder watcher in Docker;
4. starts the worker in the background with `DEVICE=metal`.

Then open <http://localhost:8090>. Models are downloaded on first use and
cached in `./models`. You can close the terminal; the worker keeps running.

## Day to day

| Command | What it does |
| --- | --- |
| `./scripts/mac.sh up` | Starts whatever is not running. Safe to repeat. |
| `./scripts/mac.sh down` | Stops the worker and the containers. A running job goes back to the queue; data and models are kept. |
| `./scripts/mac.sh status` | Says whether the worker runs and lists the containers. |
| `./scripts/mac.sh logs` | Follows the worker's log, `.host-worker/worker.log`. The log of the previous run is kept as `worker.log.1`. |

After changing `.env`, run `down` and then `up`.

The worker is not started again by itself after a restart of the Mac or if
it crashes: run `./scripts/mac.sh up`. The web page shows a banner while no
worker is running.

## Settings

Put these in `.env` if needed:

| Variable | Default | Description |
| --- | --- | --- |
| `DIARIZATION_DEVICE` | `auto` (`mps` on a Mac) | Set to `cpu` if the speaker model fails on Metal. |
| `WHISPER_CPP_BIN` | `whisper-cli` | Path of the whisper.cpp program. If you set it, Homebrew's `whisper-cpp` is not needed. |
| `DB_PORT` | `5432` | Host port of the database, if 5432 is taken. |
| `HOST_DATABASE_URL` | built from `DB_PORT` | Full database address for the host worker. |

## By hand

`mac.sh` is a wrapper around two steps, which also work on their own, for
example to watch the worker in a terminal or to run it on Linux:

```sh
docker compose -f compose.yaml -f compose.host-worker.yaml up -d --build
./scripts/host-worker.sh
```

`compose.host-worker.yaml` leaves the Docker worker out and publishes the
database on `127.0.0.1:5432` so the host worker can reach the queue.
`scripts/host-worker.sh` needs `ffmpeg`, whisper.cpp and either `uv` or
Python 3.12 (`PYTHON=python3.12 ./scripts/host-worker.sh`). It stays in the
foreground; stop it with Ctrl-C.

## Troubleshooting

**"the worker stopped right after starting"** — the last lines of its log
are printed with the message. Usually a setting in `.env` that the worker
does not accept.

**"whisper.cpp found no GPU it can use"** — the whisper.cpp build has no
Metal support (for example on an Intel Mac). Use a Metal build, or put
`DEVICE=cpu` in `.env`.

**`whisper-cli` not found after the Homebrew step** — Homebrew's package
did not provide the program under that name. Build whisper.cpp from source
(Metal is on by default on Apple Silicon) and point `WHISPER_CPP_BIN` at
the binary.

**The worker cannot connect to the database** — port 5432 is used by
another PostgreSQL on the Mac. Set `DB_PORT` in `.env`, then `down` and `up`.

> **Not verified by the author on a Mac.** `mac.sh` is tested on Linux
> against stand-ins for Docker, Homebrew, uv and the worker; the whisper.cpp
> engine, the host worker's settings and the compose override are tested on
> Linux as well. Homebrew's packages, the Metal path itself and pyannote on
> `mps` are not. Expect to adjust details.
