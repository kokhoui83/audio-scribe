# Operate and troubleshoot

## See what is happening

```sh
docker compose ps
docker compose logs -f worker        # or watcher, api
curl -s localhost:8090/api/health | jq
```

The web page shows the same: worker state at the top, a red banner when
something needs attention.

## Common situations

**"Worker cannot start: HF_TOKEN is not set"** — follow
[Getting started, step 1](getting-started.md#1-configure), then
`docker compose up -d`. Queued files wait and start by themselves.

**"The diarization model could not be loaded"** with a token set — the
conditions of the model have not been accepted for that account, or the
machine has no internet for the first download.

**"No worker is running"** — `docker compose logs worker`. If the container
restarts in a loop with exit code 137 it is running out of memory: use a
smaller `WHISPER_MODEL` or give Docker more memory.

**"whisper.cpp found no GPU it can use"** — see the troubleshooting section
of the [Vulkan](vulkan.md) or [Metal](metal.md) guide.

**A file sits in the inbox** — it must have a known audio extension, must not
be hidden or a partial download (`.part`, `.crdownload`), and must be
unchanged for `STABLE_SECONDS`. See `docker compose logs watcher`.

**A file is in `data/failed/`** — read the `.error.txt` next to it. To try
again, press **Retry** in the web page, or simply move the file back to the
inbox.

**A job is "processing" but nothing happens** — if its worker died, the job
returns to the queue after `LEASE_SECONDS` (2 minutes) without any action.

**Poor speaker separation** — pass the number of speakers; use better audio
(one microphone per person is ideal); very short interjections are the
hardest case.

## Scale

```sh
docker compose up -d --scale worker=2
```

Each worker loads its own models (memory!). On one CPU this rarely helps,
because a single worker already uses all cores; it is meant for multi-GPU
hosts or several machines sharing the database and the data folder.

## Back up

- Transcripts and originals: the `data/` folder.
- Job history: `docker compose exec db pg_dump -U scribe scribe > scribe.sql`
- Models can always be downloaded again.

## Upgrade

```sh
git pull
docker compose up -d --build
```

Running jobs are returned to the queue and picked up by the new worker.

## Reset everything

```sh
docker compose down -v     # deletes job history and cached models; data/ is kept
```

## Work offline

After the first successful start all models are in the `models` volume. Add
`HF_HUB_OFFLINE: "1"` to the worker's environment in `compose.yaml` to
guarantee no network access is attempted.
