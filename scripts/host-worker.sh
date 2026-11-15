#!/bin/sh
# Run the worker on this machine instead of in Docker. On a Mac this is what
# lets Whisper and the speaker model use the GPU (Metal).
#
#   docker compose -f compose.yaml -f compose.host-worker.yaml up -d
#   ./scripts/host-worker.sh          prepare, then run in the foreground
#   ./scripts/host-worker.sh setup    only check the tools and install the packages
#   ./scripts/host-worker.sh run      only run; fails if nothing was prepared
#
# On a Mac, scripts/mac.sh does all of this with one command.
# Settings come from .env, as for Docker. See docs/how-to/metal.md.
set -eu
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

PYTHON="${PYTHON:-python3}"
VENV="${VENV:-.venv-worker}"
WHISPER_CPP_BIN="${WHISPER_CPP_BIN:-whisper-cli}"

fail() {
  echo "host-worker: $1" >&2
  exit 1
}

# Whether the given Python is recent enough for this code.
is_current() {
  "$1" -c 'import sys; sys.exit(sys.version_info < (3, 14))' 2>/dev/null
}

setup() {
  command -v ffmpeg >/dev/null || fail "ffmpeg not found (macOS: brew install ffmpeg)"
  command -v "$WHISPER_CPP_BIN" >/dev/null \
    || fail "$WHISPER_CPP_BIN not found (macOS: brew install whisper-cpp), or set WHISPER_CPP_BIN"
  if [ -x "$VENV/bin/python" ] && ! is_current "$VENV/bin/python"; then
    echo "host-worker: $VENV was made with a Python older than 3.14; building it again"
    rm -rf "$VENV"
  fi
  if [ ! -x "$VENV/bin/python" ]; then
    echo "host-worker: creating $VENV and installing packages (once, takes a few minutes)"
  fi
  # With uv there is nothing else to install: it fetches Python as well.
  if command -v uv >/dev/null; then
    [ -x "$VENV/bin/python" ] || uv venv --quiet --python 3.14 "$VENV"
    uv pip install --quiet --python "$VENV/bin/python" -r requirements/host-worker.txt
  else
    is_current "$PYTHON" \
      || fail "Python 3.14 or newer is needed. Install uv (macOS: brew install uv), which fetches it, or run with PYTHON=python3.14 $0"
    [ -x "$VENV/bin/python" ] || "$PYTHON" -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --disable-pip-version-check -r requirements/host-worker.txt
  fi
}

run() {
  [ -x "$VENV/bin/python" ] || fail "$VENV is missing; run $0 setup first"
  if [ "$(uname -s)" = Darwin ]; then
    default_device=metal
  else
    default_device=cpu
  fi
  mkdir -p "${DATA_DIR:-./data}" "${MODELS_DIR:-./models}"
  DATA_DIR="$(cd "${DATA_DIR:-./data}" && pwd)"
  MODELS_DIR="$(cd "${MODELS_DIR:-./models}" && pwd)"
  export DATA_DIR MODELS_DIR WHISPER_CPP_BIN
  export DEVICE="${DEVICE:-$default_device}"
  export SPEECH_ENGINE="${SPEECH_ENGINE:-whisper-cpp}"
  export DATABASE_URL="${HOST_DATABASE_URL:-postgresql://scribe:scribe@127.0.0.1:${DB_PORT:-5432}/scribe}"
  export HF_HOME="$MODELS_DIR/hf" HF_HUB_DISABLE_TELEMETRY=1 PYANNOTE_METRICS_ENABLED=0
  # Operations the Metal backend lacks run on the CPU instead of failing.
  export PYTORCH_ENABLE_MPS_FALLBACK=1
  exec "$VENV/bin/python" -m scribe.entrypoints.worker
}

case "${1:-}" in
  "") setup && run ;;
  setup) setup ;;
  run) run ;;
  *) fail "usage: $0 [setup | run]" ;;
esac
