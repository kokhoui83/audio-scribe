#!/bin/sh
# Run Audio Scribe on a Mac with one command. Containers cannot use the Mac's
# GPU (Metal), so the worker runs on the Mac itself; this script installs what
# it needs, starts the rest in Docker and keeps the worker in the background.
#
#   ./scripts/mac.sh up       install what is missing, start everything
#   ./scripts/mac.sh down     stop everything; data and models are kept
#   ./scripts/mac.sh status   what is running
#   ./scripts/mac.sh logs     follow the worker's log
#
# Needs Docker Desktop and Homebrew. See docs/how-to/metal.md.
set -eu
cd "$(dirname "$0")/.."

RUN_DIR=.host-worker
PID_FILE="$RUN_DIR/worker.pid"
LOG_FILE="$RUN_DIR/worker.log"
# As long as Docker gives the worker container (stop_grace_period).
STOP_SECONDS=30
# Long enough for a worker with a setting it cannot accept to give up.
START_CHECK_SECONDS=2

say() {
  echo "mac: $1"
}

fail() {
  echo "mac: $1" >&2
  exit 1
}

compose() {
  docker compose -f compose.yaml -f compose.host-worker.yaml "$@"
}

# Prints the worker's process ID; fails if no worker is running.
worker_pid() {
  [ -f "$PID_FILE" ] || return 1
  pid="$(cat "$PID_FILE")"
  kill -0 "$pid" 2>/dev/null || return 1
  echo "$pid"
}

ensure_settings() {
  [ -f .env ] && return
  cp .env.example .env
  fail "created .env from .env.example. Put your Hugging Face token in it (HF_TOKEN=hf_..., see docs/how-to/getting-started.md) or set DIARIZE=false, then run this again."
}

require_docker() {
  command -v docker >/dev/null \
    || fail "Docker not found. Install Docker Desktop (https://www.docker.com/products/docker-desktop/) and run this again."
  docker info >/dev/null 2>&1 || fail "Docker is not running. Start Docker Desktop and run this again."
}

# The whisper.cpp program the worker will call: the one named in .env, if any.
whisper_program() {
  (
    . ./.env
    echo "${WHISPER_CPP_BIN:-whisper-cli}"
  )
}

install_tools() {
  if command -v ffmpeg >/dev/null && command -v uv >/dev/null \
    && command -v "$(whisper_program)" >/dev/null; then
    return
  fi
  command -v brew >/dev/null \
    || fail "Homebrew is needed to install ffmpeg, whisper.cpp and uv. Install it from https://brew.sh and run this again."
  say "installing ffmpeg, whisper.cpp and uv with Homebrew"
  brew bundle install --file=Brewfile
}

start_worker() {
  if pid="$(worker_pid)"; then
    say "the worker is already running (pid $pid)"
    return
  fi
  mkdir -p "$RUN_DIR"
  # One earlier log is kept, so the reason for a crash survives a restart.
  if [ -f "$LOG_FILE" ]; then mv -f "$LOG_FILE" "$LOG_FILE.1"; fi
  # Started from a subshell that ends at once: the worker then belongs to the
  # system, not to this script, and its end can be seen with `kill -0`.
  (
    nohup ./scripts/host-worker.sh run >"$LOG_FILE" 2>&1 </dev/null &
    echo $! >"$PID_FILE"
  )
  sleep "$START_CHECK_SECONDS"
  if ! worker_pid >/dev/null; then
    rm -f "$PID_FILE"
    tail -n 20 "$LOG_FILE" >&2
    fail "the worker stopped right after starting; the end of its log ($LOG_FILE) is shown above."
  fi
}

stop_worker() {
  if ! pid="$(worker_pid)"; then
    rm -f "$PID_FILE"
    return
  fi
  say "stopping the worker; a running job goes back to the queue"
  kill "$pid"
  waited=0
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$waited" -ge "$STOP_SECONDS" ]; then
      say "the worker did not stop within $STOP_SECONDS seconds; ending it now"
      kill -9 "$pid" 2>/dev/null || true
      break
    fi
    sleep 1
    waited=$((waited + 1))
  done
  rm -f "$PID_FILE"
}

up() {
  ensure_settings
  require_docker
  install_tools
  ./scripts/host-worker.sh setup
  say "starting the database, the web page and the folder watcher in Docker"
  compose up -d --build
  start_worker
  say "running. Open http://localhost:8090 (or the PORT set in .env). The first job downloads the models."
  say "worker log: ./scripts/mac.sh logs    stop: ./scripts/mac.sh down"
}

down() {
  stop_worker
  require_docker
  compose down
}

status() {
  if pid="$(worker_pid)"; then
    say "worker: running (pid $pid), log in $LOG_FILE"
  else
    say "worker: not running"
  fi
  compose ps
}

logs() {
  [ -f "$LOG_FILE" ] || fail "no worker log yet; start with ./scripts/mac.sh up"
  say "the other services: docker compose logs -f api watcher db"
  exec tail -n 50 -f "$LOG_FILE"
}

case "${1:-}" in
  up) up ;;
  down) down ;;
  status) status ;;
  logs) logs ;;
  *) fail "usage: $0 up | down | status | logs" ;;
esac
