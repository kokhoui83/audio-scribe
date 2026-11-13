# Audio Scribe

Drop an audio file in a folder, get back a transcript that says who spoke
when. Runs entirely on your own machine with Docker Compose.

- **Speech to text** with Whisper (via faster-whisper), **speaker
  identification** with pyannote. Both are dedicated local speech models; no
  large language model and no cloud service is involved.
- **Any common format**: mp3, wav, m4a, flac, ogg, opus, aac, wma, … and the
  audio track of mp4, mkv, mov, webm.
- **Folder watching**, plus a web page and an HTTP API for uploads.
- **Durable job queue** (PostgreSQL): automatic retries, recovery from worker
  crashes, nothing lost on restart.
- **Output** as Markdown (default), plain text, JSON with word timings, SRT
  and WebVTT.
- **CPU by default, NVIDIA GPU** with one extra compose file.

## Quick start

```sh
cp .env.example .env        # then set HF_TOKEN (see below)
docker compose up -d --build
```

1. Speaker identification needs a free Hugging Face token **once**, to
   download the model: accept the conditions at
   <https://hf.co/pyannote/speaker-diarization-community-1>, create a read
   token at <https://hf.co/settings/tokens>, and put it in `.env` as
   `HF_TOKEN=...`. (Or set `DIARIZE=false` to skip speaker labels.)
2. Copy audio files into `data/inbox/`.
3. Transcripts appear in `data/output/`; originals move to `data/archive/`.
4. Watch progress, upload files and read transcripts at
   <http://localhost:8090>.

With an NVIDIA GPU:

```sh
docker compose -f compose.yaml -f compose.gpu.yaml up -d --build
```

## Documentation

| | |
| --- | --- |
| [Requirements](docs/requirements.md) | What the system must do, with IDs the tests trace back to |
| [Architecture](docs/architecture.md) | Containers, layers, the dependency rule, key decisions |
| [Design](docs/design.md) | Queue mechanics, file handling, speaker attribution, test strategy |
| [Getting started](docs/how-to/getting-started.md) | First run, step by step |
| [Configuration](docs/how-to/configuration.md) | Every setting |
| [GPU](docs/how-to/gpu.md) | Running on an NVIDIA GPU |
| [HTTP API](docs/how-to/api.md) | Endpoints with examples |
| [Operations](docs/how-to/operations.md) | Monitoring, scaling, backup, troubleshooting |
| [Development](docs/how-to/development.md) | Running tests, the TDD workflow, extending the system |

## Tests

```sh
./t.sh          # lint + all tests in Docker, including the PostgreSQL contract tests
```

## License

[MIT](LICENSE). The models it downloads have their own licenses: the Whisper models
are MIT, and the pyannote speaker model is CC-BY-4.0.
