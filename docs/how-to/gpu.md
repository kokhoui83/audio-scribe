# Run on an NVIDIA GPU

## Prerequisites

- An NVIDIA GPU with a current driver on the host
- The [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
- Check: `docker run --rm --gpus all ubuntu nvidia-smi` prints your GPU

## Start

```sh
docker compose -f compose.yaml -f compose.gpu.yaml up -d --build
```

The override builds the worker image with the CUDA 12.6 build of PyTorch
(`audio-scribe-worker-gpu`), sets `DEVICE=cuda` and reserves one GPU.
Whisper then runs in `float16` with batches of 8.

To avoid typing both files every time, add to `.env`:

```
COMPOSE_FILE=compose.yaml:compose.gpu.yaml
```

## Switch back to CPU

```sh
docker compose up -d      # without the override (and without COMPOSE_FILE)
```

Both worker images can exist side by side; the model cache is shared.

## Tuning

- Out of GPU memory: lower `WHISPER_BATCH_SIZE` (for example `4`) or use
  `WHISPER_MODEL=medium`.
- Several GPUs: run one worker per GPU by adding more worker services with
  different `device_ids` in the override file.

> The GPU override was written against the documented requirements of
> PyTorch, CTranslate2 and pyannote but has not been run on GPU hardware by
> the author. If the worker reports a missing CUDA library, check
> `docker compose logs worker` and the `LD_LIBRARY_PATH` line in the
> `Dockerfile`.
