# Design

How the mechanisms described in the [architecture](architecture.md) work.

## Domain model

- **`Job`** (`domain/job.py`) — one audio file on its way to a transcript.
  Holds status, attempts, the lease (`locked_by`, `heartbeat_at`), `run_after`
  (earliest start, used for retry delays) and the result summary. Every state
  change is a method (`start`, `renew`, `complete`, `fail`, `release`,
  `expire_lease`, `cancel`, `retry`) that either applies the change or raises
  `InvalidTransition` / `NotOwner`.
- **`Transcript`** (`domain/transcript.py`) — language, duration, speakers and
  a list of `Segment`s (a paragraph by one speaker, made of timed `Word`s).
- **`render`** (`domain/rendering.py`) — a transcript as md, txt, json, srt or
  vtt.

## The queue

### Claiming

```sql
SELECT … FROM jobs
WHERE status = 'queued' AND run_after <= :now
ORDER BY created_at, id
FOR UPDATE SKIP LOCKED
LIMIT 1
```

In the same transaction the row is loaded into a `Job`, `job.start(worker)` is
applied, and it is saved. `SKIP LOCKED` makes concurrent workers pick
different rows without waiting. A contract test starts four threads against
real PostgreSQL and asserts twenty jobs are claimed exactly once each.

### Atomic updates

`JobRepository.update(job_id, mutate)` is the only way state changes:

1. `SELECT … FOR UPDATE` the row,
2. apply `mutate(job)` — a domain method,
3. save, commit.

If `mutate` raises, nothing is saved. Because worker actions check ownership
(`locked_by == worker` and `status == processing`), a worker that lost its job
cannot overwrite the work of the worker that now holds it.

### Leases and crash recovery

| Setting | Default | Meaning |
| --- | --- | --- |
| `HEARTBEAT_SECONDS` | 10 | How often a worker renews its lease |
| `LEASE_SECONDS` | 120 | Silence after which the job is taken back |

The worker renews from two places: the progress callbacks of the models, and
a timer thread (so a long model call that reports nothing still renews). The
watcher's housekeeper lists processing jobs with an old heartbeat and, under
the row lock, re-checks and calls `job.expire_lease`: back to `queued`, or
`failed` when the attempts are used up — which is what stops a file that
crashes the worker every time ("poison pill") from looping forever.

### Retries

`Job.fail(retryable=True)` re-queues with `run_after = now + backoff × 2^(attempt−1)`
(30 s, 60 s, … by default) until `MAX_ATTEMPTS`. Unreadable audio
(`UnreadableAudio` from the decoder) is not retryable and fails at once.

### Stopping and cancelling

- `docker compose stop` sends SIGTERM; the worker sets a flag, the next
  progress callback raises, and the job is **released** (back to `queued`,
  attempt not counted).
- Cancelling or deleting a running job makes the worker's next renewal raise
  `NotOwner`; it abandons the job and writes nothing.

### A worker that cannot start

If the models cannot be loaded (typically: no `HF_TOKEN`), the worker records
the reason in the `workers` table, claims nothing, and tries again every
minute. Jobs stay queued; the web page shows the reason.

## File handling

```mermaid
sequenceDiagram
    participant I as inbox/
    participant W as .work/<id>/
    participant Q as jobs table
    participant O as output/
    participant A as archive/
    Note over I: file unchanged for STABLE_SECONDS
    I->>W: 1. atomic rename
    W->>Q: 2. insert job (queued)
    Q->>Q: 3. worker claims, transcribes
    Q->>O: 4. write transcripts (temp file + rename)
    O->>Q: 5. mark done, store transcript
    W->>A: 6. move original
```

What a crash at each point leaves behind, and how it heals:

| Crash after | State | Recovery |
| --- | --- | --- |
| 1 | File in `.work`, no job | On start the watcher returns files without a job to the inbox |
| 2–4 | Job `processing`, file in `.work` | Lease expires, job is re-queued; transcripts are overwritten on the re-run |
| 5 | Job `done`, original still in `.work` | Harmless: transcript exists; re-run still possible |

The job is recorded as done *before* the original is moved, so no ordering of
failures can lose the audio.

Other rules:

- A transcript never overwrites another job's file: on a name clash the job
  id is appended (`call-1a2b3c4d.md`). Re-running a job overwrites its own.
- File names from uploads are reduced to their base name; sub-folder names are
  cleaned of `..`, so nothing is written outside the data folder.
- Files created by the containers are given the owner of the data folder, so
  they are not root-owned on the host.

## From audio to transcript

1. **Decode** — ffmpeg converts the first audio track to 16 kHz mono float
   samples. This is why every format ffmpeg knows is supported.
2. **Recognise** — faster-whisper with voice-activity detection and word
   timestamps. The language is detected from the audio unless given. On a GPU
   the batched pipeline is used.
3. **Diarize** — pyannote returns speaker turns (`start`, `end`, `label`). The
   *exclusive* output (no overlapping turns) is used when available. An
   expected number of speakers can be passed as a hint.
4. **Attribute** (`domain/transcript.py`) — each word goes to the speaker whose
   turns overlap it the most; a word in a gap takes the nearest turn. Labels
   are renamed "Speaker 1…N" in order of first appearance.
5. **Paragraphs** — consecutive words of one speaker form a segment; a
   monologue is additionally split at a sentence boundary after a pause of
   1.5 s or about 500 characters.
6. **Render** — one document per configured format; subtitle cues are cut at
   84 characters / 7 seconds and never span two speakers.

## Testing strategy

| Level | Where | What it proves | Needs |
| --- | --- | --- | --- |
| Acceptance (Gherkin) | `tests/features`, steps in `tests/acceptance` | Each requirement, through the real use cases and a real data folder | fake clock, fake speech models, in-memory queue |
| Unit | `tests/unit` | Domain rules, settings, adapter translation logic, the dependency rule | nothing |
| Contract | `tests/contract` | In-memory and PostgreSQL repositories behave identically | PostgreSQL for one of the two runs |
| Integration | `tests/integration` | HTTP API, file-store safety, ffmpeg decoding of real files | ffmpeg |

The speech models are never loaded in tests; they sit behind ports and are
replaced by fakes that turn a small text "recording" into timed words and
speaker turns. The fake queue is trustworthy because it must pass the same
contract tests as the real one.

## Known limitations

- A whole recording is decoded into memory (about 230 MB per hour of audio).
- Speakers are numbered per file; there is no recognition across files.
- Overlapping speech is attributed to one speaker.
- No authentication; the port is bound to localhost by default.
- Schema changes are applied with `CREATE … IF NOT EXISTS`; a schema change to
  an existing column would need a migration tool.
