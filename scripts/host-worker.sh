#!/bin/sh
# Run the worker on this machine instead of in Docker. On a Mac this is what
# lets Whisper and the speaker model use the GPU (Metal).
#
#   docker compose -f compose.yaml -f compose.host-worker.yaml up -d
#   ./scripts/host-worker.sh
#
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

command -v ffmpeg >/dev/null || fail "ffmpeg not found (macOS: brew install ffmpeg)"
command -v "$WHISPER_CPP_BIN" >/dev/null \
  || fail "$WHISPER_CPP_BIN not found (macOS: brew install whisper-cpp), or set WHISPER_CPP_BIN"
"$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null \
  || fail "Python 3.12 or newer is needed (macOS: brew install python@3.12, then PYTHON=python3.12 $0)"

if [ ! -x "$VENV/bin/python" ]; then
  echo "host-worker: creating $VENV and installing packages (once, takes a few minutes)"
  "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --disable-pip-version-check -r requirements/host-worker.txt

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
