# Run on a GPU through Vulkan (AMD, Intel)

For GPUs that are not NVIDIA. Whisper then runs on the GPU in
[whisper.cpp](https://github.com/ggml-org/whisper.cpp) instead of
faster-whisper. Speaker identification stays on the CPU, because PyTorch has
no Vulkan backend.

For an NVIDIA GPU use [the CUDA setup](gpu.md) instead: it also accelerates
speaker identification.

## Prerequisites

- A Linux Docker host whose GPU has a working Vulkan driver.
- The GPU is visible as `/dev/dri/renderD*` on the host.

Not supported:

- **Docker Desktop on Windows (WSL2).** Containers there can only reach the
  GPU through Direct3D, and no Linux distribution ships the Vulkan-on-Direct3D
  driver. The worker will report "found no GPU".
- **Docker on macOS.** See [Run on a Mac GPU](metal.md).

## Start

```sh
docker compose -f compose.yaml -f compose.vulkan.yaml up -d --build
```

The override builds whisper.cpp with Vulkan into the image
`audio-scribe-worker-vulkan`, sets `DEVICE=vulkan` and passes `/dev/dri` to
the worker. The first build compiles whisper.cpp and takes a few minutes.

On start the worker checks that whisper.cpp really computes on a GPU and logs
its name:

```
whisper.cpp computes on Vulkan0
```

To avoid typing both files every time, add to `.env`:

```
COMPOSE_FILE=compose.yaml:compose.vulkan.yaml
```

## Troubleshooting

**"whisper.cpp found no GPU it can use"** — the worker refuses to fall back
to the CPU silently; queued files wait. The message quotes what whisper.cpp
saw. Check that `/dev/dri` exists on the host and that
`docker compose exec worker ls /dev/dri` shows a `renderD*` entry. Software
renderers (llvmpipe) are deliberately not counted as a GPU.

**Several GPUs** — set `GPU_INDEX` in `.env` (`0` is the first GPU whisper.cpp
lists in `docker compose logs worker`).

**Out of GPU memory** — use a smaller `WHISPER_MODEL`.

## Differences from the default engine

- `WHISPER_COMPUTE_TYPE` and `WHISPER_BATCH_SIZE` do not apply.
- Models are whisper.cpp's own files, downloaded on first use from
  <https://hf.co/ggerganov/whisper.cpp> into the `models` volume. The same
  names work (`tiny` … `large-v3-turbo`).
- Word timings are estimated differently and are somewhat less precise, which
  can move a speaker change by a word.
- No voice-activity detection before recognition.

> Verified by the author: the image builds, and a recording dropped in the
> inbox is transcribed through whisper.cpp's Vulkan code path using a software
> Vulkan device. **Not verified on a physical AMD or Intel GPU.**
