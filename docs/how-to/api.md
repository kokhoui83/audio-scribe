# Use the HTTP API

Base URL: `http://localhost:8090`. Interactive reference: `/docs` (OpenAPI).

## Submit a file

```sh
curl -F file=@meeting.mp3 \
     -F language=en \
     -F num_speakers=2 \
     http://localhost:8090/api/jobs
```

Optional form fields: `language`, `diarize` (`true`/`false`), `num_speakers`,
`min_speakers`, `max_speakers`. Returns `201` with the job.

## Follow a job

```sh
curl http://localhost:8090/api/jobs/<id>
```

```json
{
  "id": "82d08385-…", "filename": "meeting.mp3", "status": "processing",
  "stage": "transcribing", "progress": 0.42, "attempts": 1, "max_attempts": 3,
  "language": null, "num_speakers": null, "error": null, "outputs": []
}
```

`status` is one of `queued`, `processing`, `done`, `failed`, `cancelled`.

## Fetch the transcript

```sh
curl "http://localhost:8090/api/jobs/<id>/transcript"                  # Markdown
curl "http://localhost:8090/api/jobs/<id>/transcript?format=json"
curl -OJ "http://localhost:8090/api/jobs/<id>/transcript?format=srt&download=1"
```

Formats: `md`, `txt`, `json`, `srt`, `vtt` — all available for every finished
job, whatever `OUTPUT_FORMATS` says.

JSON shape:

```json
{
  "file": "meeting.mp3", "language": "en", "duration": 20.0,
  "speakers": ["Speaker 1", "Speaker 2"],
  "segments": [
    {"start": 0.0, "end": 5.8, "speaker": "Speaker 1", "text": "Good morning. …",
     "words": [{"start": 0.0, "end": 0.4, "word": " Good", "probability": 0.98}]}
  ]
}
```

## Send a recording while it is being made

For audio that is still being produced. The server transcribes what has
arrived while the rest is on its way; see [Record a meeting](recording.md).

```sh
id=$(curl -s -F filename=standup.webm localhost:8090/api/recordings | jq -r .id)

# For each piece, in order. "offset" is the number of bytes sent before it.
curl -F piece=@piece-000.bin -F offset=0     localhost:8090/api/recordings/$id/audio
curl -F piece=@piece-001.bin -F offset=40960 localhost:8090/api/recordings/$id/audio

curl localhost:8090/api/jobs/$id/draft            # {"text": "…", "seconds": 61.3}
curl -X POST localhost:8090/api/recordings/$id/finish
```

- The pieces, put together, must be one media file that ffmpeg can read from
  its beginning, such as the output of a browser's `MediaRecorder` or of
  `ffmpeg -f webm -live 1`. They can be cut anywhere.
- The answer to each piece is the job; its `size_bytes` is the offset of the
  next piece. Sending a piece again with the same offset is harmless. A piece
  whose offset is beyond what the server has is refused with `409`, and the
  answer names the `expected_offset`.
- `POST /api/recordings` takes the same optional fields as an upload, plus
  `filename` (its extension is only used for naming).
- While the recording runs, the job has `"recording": true` and its
  `duration_s` is the length heard so far. Without `finish`, the recording
  is ended after `RECORDING_IDLE_SECONDS` without audio.

## All endpoints

| Method | Path | Purpose | Errors |
| --- | --- | --- | --- |
| `GET` | `/api/health` | Database, job counts, workers | `503` database down |
| `GET` | `/api/jobs?status=&limit=&offset=` | List, newest first | |
| `POST` | `/api/jobs` | Upload | `400` empty file / bad option |
| `GET` | `/api/jobs/{id}` | One job | `404` |
| `GET` | `/api/jobs/{id}/transcript?format=&download=` | Transcript | `409` not done, `400` bad format |
| `GET` | `/api/jobs/{id}/draft` | Text of a recording so far, and the seconds it covers | `404` |
| `POST` | `/api/recordings` | Start a recording | `400` bad option |
| `POST` | `/api/recordings/{id}/audio` | Add a piece (`piece`, `offset`) | `409` gap / recording closed, `404` |
| `POST` | `/api/recordings/{id}/finish` | End the recording | `400` nothing recorded, `409` already ended, `404` |
| `PUT` | `/api/jobs/{id}/speakers` | Name speakers: `{"names": {"Speaker 1": "Anna"}}` | `404` |
| `POST` | `/api/jobs/{id}/retry` | Run a failed, cancelled or finished job again | `409` in flight / original gone |
| `POST` | `/api/jobs/{id}/cancel` | Cancel a queued or running job | `409` already finished |
| `DELETE` | `/api/jobs/{id}` | Forget the job (files in `output/` and `archive/` stay) | `404` |

## Example: wait for a result in a script

```sh
id=$(curl -s -F file=@call.wav localhost:8090/api/jobs | jq -r .id)
until [ "$(curl -s localhost:8090/api/jobs/$id | jq -r .status)" != "queued" ] &&
      [ "$(curl -s localhost:8090/api/jobs/$id | jq -r .status)" != "processing" ]; do sleep 5; done
curl -s "localhost:8090/api/jobs/$id/transcript?format=txt"
```
