# Configuration

Settings are environment variables, read from `.env` next to `compose.yaml`.
After a change run `docker compose up -d`. An empty value means "default". A
mistyped value stops the service with a message naming the variable.

## Speech to text

| Variable | Default | Description |
| --- | --- | --- |
| `WHISPER_MODEL` | `large-v3-turbo` | `tiny`, `base`, `small`, `medium`, `large-v3`, `large-v3-turbo`, or any faster-whisper model name. Larger is more accurate and slower. |
| `DEFAULT_LANGUAGE` | *(detect)* | Language code such as `en`, `de`, `zh`. |
| `WHISPER_COMPUTE_TYPE` | `auto` | `auto` = `int8` on CPU, `float16` on GPU. |
| `WHISPER_BATCH_SIZE` | `0` | `0` = 1 on CPU, 8 on GPU. Higher is faster and uses more memory. |
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

Advanced, rarely needed (add them to the `x-env` block in `compose.yaml`):
`AUDIO_EXTENSIONS`, `SCAN_SECONDS`, `POLL_SECONDS`, `HEARTBEAT_SECONDS`,
`RETRY_BACKOFF_SECONDS`.

## Web page and API

| Variable | Default | Description |
| --- | --- | --- |
| `BIND_ADDR` | `127.0.0.1` | `0.0.0.0` exposes the page on the network. There is no login, so only do this on a trusted network or behind a reverse proxy with authentication. |
| `PORT` | `8090` | Host port. |
