# Configuration

Settings are environment variables, read from `.env` next to `compose.yaml`.
After a change run `docker compose up -d`. An empty value means "default". A
mistyped value stops the service with a message naming the variable.

## Speech to text

| Variable | Default | Description |
| --- | --- | --- |
| `DEVICE` | `cpu` | `cpu`, `cuda`, `vulkan` or `metal`. Set by the compose override files and the host worker script; see the GPU guides. |
| `SPEECH_ENGINE` | `auto` | `auto` = `faster-whisper` on `cpu`/`cuda`, `whisper-cpp` on `vulkan`/`metal`. `whisper-cpp` can also be forced on `cpu` where the program is installed (Vulkan image, host worker). |
| `GPU_INDEX` | `0` | Which GPU whisper.cpp uses, if there are several. |
| `DIARIZATION_DEVICE` | `auto` | PyTorch device for speaker identification: `cpu`, `cuda` or `mps`. `auto` follows `DEVICE` (`cpu` under Vulkan). |
| `WHISPER_MODEL` | `large-v3-turbo` | `tiny`, `base`, `small`, `medium`, `large-v3`, `large-v3-turbo`, or any faster-whisper model name. Larger is more accurate and slower. |
| `DEFAULT_LANGUAGE` | *(detect)* | Language code such as `en`, `de`, `zh`. |
| `WHISPER_COMPUTE_TYPE` | `auto` | faster-whisper only. `auto` = `int8` on CPU, `float16` on GPU. |
| `WHISPER_BATCH_SIZE` | `0` | faster-whisper only. `0` = 1 on CPU, 8 on GPU. Higher is faster and uses more memory. |
| `CPU_THREADS` | `0` | Threads for inference; `0` = all cores. |

## Speaker identification

| Variable | Default | Description |
| --- | --- | --- |
| `DIARIZE` | `true` | `false` turns speaker labels off everywhere. |
| `HF_TOKEN` | | Hugging Face token; only needed until the model is cached. |
| `DIARIZATION_MODEL` | `pyannote/speaker-diarization-community-1` | Any pyannote diarization pipeline. |

## Output

| Variable | Default | Description |
| --- | --- | --- |
| `OUTPUT_FORMATS` | `md` | Comma-separated: `md`, `txt`, `json`, `srt`, `vtt`. |
| `ARCHIVE_ORIGINALS` | `true` | `false` deletes originals after success. |
| `DATA_DIR` | `./data` | Host folder holding `inbox/`, `output/`, … |

## Intake and queue

| Variable | Default | Description |
| --- | --- | --- |
| `STABLE_SECONDS` | `5` | How long a file must be unchanged before it is queued. Raise it for slow network copies. |
| `MAX_ATTEMPTS` | `3` | Attempts per job before it is failed. |
| `LEASE_SECONDS` | `120` | A job whose worker is silent this long is taken back. |

## Live recording

| Variable | Default | Description |
| --- | --- | --- |
| `RECORDING_PASS_SECONDS` | `30` | How long a recording in progress waits between two transcription passes. Lower shows text sooner and repeats more work. |
| `RECORDING_IDLE_SECONDS` | `120` | A recording that received no audio for this long is ended and transcribed. |

Advanced, rarely needed (add them to the `x-env` block in `compose.yaml`):
`AUDIO_EXTENSIONS`, `SCAN_SECONDS`, `POLL_SECONDS`, `HEARTBEAT_SECONDS`,
`RETRY_BACKOFF_SECONDS`.

## Web page and API

| Variable | Default | Description |
| --- | --- | --- |
| `BIND_ADDR` | `127.0.0.1` | `0.0.0.0` exposes the page on the network. There is no login, so only do this on a trusted network or behind a reverse proxy with authentication. |
| `PORT` | `8090` | Host port. |
