# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements/base.txt requirements/base.txt
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements/base.txt

# ---- api + watcher: small image -------------------------------------------
FROM base AS api
COPY scribe scribe
EXPOSE 8000
CMD ["uvicorn", "--factory", "scribe.entrypoints.api:build", "--host", "0.0.0.0", "--port", "8000"]

# ---- worker: speech models -------------------------------------------------
FROM base AS worker
# cpu, or cu126 for NVIDIA GPUs (CUDA 12 + cuDNN 9, which is also what
# faster-whisper's CTranslate2 backend needs).
ARG TORCH_VARIANT=cpu
ARG TORCH_VERSION=2.15.0
COPY requirements/worker.txt requirements/worker.txt
# PyTorch first, from the index for the chosen hardware; the remaining
# packages then come from PyPI and keep the torch that is already installed.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url https://download.pytorch.org/whl/${TORCH_VARIANT} \
        torch==${TORCH_VERSION} torchaudio torchcodec \
    && pip install -r requirements/worker.txt
# Let CTranslate2 find the CUDA libraries that ship inside the torch wheels
# (the directories simply do not exist in the CPU build).
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib \
    HF_HOME=/models/hf \
    HF_HUB_DISABLE_TELEMETRY=1 \
    PYANNOTE_METRICS_ENABLED=0
COPY scribe scribe
CMD ["python", "-m", "scribe.entrypoints.worker"]

# ---- tests (no speech models: they sit behind ports and are faked) ---------
FROM base AS test
COPY requirements/dev.txt requirements/dev.txt
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements/dev.txt
COPY pyproject.toml .
COPY scribe scribe
COPY tests tests
CMD ["sh", "-c", "ruff format --check -q . && ruff check -q . && pytest"]
