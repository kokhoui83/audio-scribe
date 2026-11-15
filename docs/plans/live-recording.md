# Plan: live recording

Status: **done** (branch `feature/live-recording`). The steps at the end are
ticked off as they were completed; the last section records what was verified.

## Why

Measured on the reference machine (CPU, 16 threads, `large-v3-turbo`) with a
75-minute meeting:

| Stage | Time | Share |
| --- | --- | --- |
| Decoding + speech-to-text | 12.9 min | 28% |
| Speaker identification | about 33.5 min | 72% |
| Total | 46.4 min | |

Speech-to-text runs at about six times real-time, so it can keep up with a
recording that is still going on. If it does, only speaker identification is
left when the meeting ends: the wait drops by roughly the speech-to-text share
(here from 46 to about 34 minutes).

## Goal

Record in the web page. While the recording runs, the audio is stored on the
server and transcribed in the background. When the recording is stopped, the
remainder is transcribed, speakers are identified over the whole recording,
and the result is a normal job with a normal transcript.

Reading the text while recording is a by-product and is included in a simple
form.

## Out of scope

- Identifying speakers while the recording runs (the larger saving, but it
  means working below pyannote's standard interface).
- Capturing the sound of other applications (a video call's far end); the
  page records the microphone.
- Pausing and resuming a recording.
- Making speaker identification itself faster.

## Decisions

**1. A recording is a job from its first second.** It gets `source =
"recording"` and a flag `audio_complete = false`. The queue status
(`queued`, `processing`, …) keeps its meaning; "still recording" is a
separate fact. Leases, retries, cancelling and crash recovery therefore work
unchanged.

**2. The worker works on a recording in passes and gives it back in
between.** A pass transcribes the audio that arrived since the previous one,
saves the result, and returns the job to the queue with a short delay
(`RECORDING_PASS_SECONDS`, 30 s) without using up an attempt. Considered and
rejected: one worker holding the job for the whole meeting. It would block
the queue for hours while being idle five sixths of the time, and would need
a sleep inside a use case. With passes, other files are processed in between
and a restart loses at most one pass.

**3. The text so far is a `Draft` stored with the job** (new `draft` column):
the words, the position up to which the audio is settled, and the detected
language. It is the checkpoint a pass resumes from, and what the page shows
as live text.

**4. Pieces are cut where the recogniser itself ends a sentence.** Each pass
transcribes everything after the settled position, then keeps only the words
up to the last segment boundary that lies at least five seconds before the
end of the audio. The rest is transcribed again in the next pass, with more
context. This needs no separate silence detector and no new port, and is a
pure function that can be unit-tested. Cost: a few seconds of audio are
transcribed twice per pass.

**5. The browser sends the recording as it is produced** (`MediaRecorder`,
WebM/Opus in Chrome and Firefox), one piece every five seconds, appended to a
single file on the server. Each piece states the byte offset it belongs at:
the same piece sent twice is harmless, a gap is refused. Considered and
rejected: sending raw PCM from an audio worklet (ten times the size, more
browser code, an uncompressed original in the archive).

**6. The decoder learns to start at a time offset** (`decode(path, start)`),
so a pass only produces the samples it needs. A file that is still growing
is decoded up to its last complete packet.

**7. A recording that stops receiving audio is finished automatically** after
`RECORDING_IDLE_SECONDS` (120 s) and transcribed with what arrived, so a
closed browser tab does not leave a job open forever. The page also keeps the
recording in memory and offers it as a download if the server refuses it.

**8. Speaker identification is unchanged.** It runs once, at the end, over
the whole recording, and its turns are merged with the words from the draft
by the existing `build_transcript`.

## Requirements added

FR-50 to FR-58 in [requirements](../requirements.md#live-recording).

## Steps

Each step follows the workflow in [AGENTS.md](../../AGENTS.md): requirement,
scenario, failing test, code, refactor.

- [x] 1. Requirements FR-50 to FR-58 and `tests/features/recording.feature`.
- [x] 2. Domain: `Draft` and the settling rule (`domain/draft.py`), with unit
      tests.
- [x] 3. Domain: `Job` learns `receive audio`, `finish recording`,
      `checkpoint`, `pause` and the idle rule, with unit tests.
- [x] 4. Ports and adapters: `AudioDecoder.decode(start=)`,
      `FileStore.append_audio`, the `draft` / `audio_complete` / `audio_at`
      columns in both repositories; contract and integration tests (real
      ffmpeg on a growing WebM file).
- [x] 5. Use cases: passes in `JobProcessor`; `start_recording`, `add_audio`,
      `finish_recording`, `text_so_far` in `JobService`; step definitions.
- [x] 6. HTTP API: `/api/recordings…` and `/api/jobs/{id}/draft`, with API
      tests.
- [x] 7. Settings (`RECORDING_PASS_SECONDS`, `RECORDING_IDLE_SECONDS`) and
      wiring in `bootstrap`.
- [x] 8. Web page: record, stop, timer, text so far, fallback download.
- [x] 9. Documentation: requirements, architecture, design, API, a how-to,
      configuration, README.
- [x] 10. Verification with the real models and a real browser (below).

## Risks

| Risk | Handling |
| --- | --- |
| Text differs slightly from transcribing the whole file at once, because the recogniser sees less context per piece. | Pieces end at sentence boundaries and the newest five seconds are redone. Compared in the verification below. |
| Safari records MP4 instead of WebM. | The server accepts whatever ffmpeg decodes, but only WebM/Opus is covered by tests. Stated in the how-to. |
| A long backlog of files delays the passes. | Nothing is lost: the recording is then transcribed after the fact, as before. |
| Microphone access needs a secure context. | Works on `localhost`; over the network it needs HTTPS. Stated in the how-to. |

## Results

Verified on 2026-11-13 on the reference machine (CPU, 16 threads,
`large-v3-turbo`, pyannote community-1), with a copy of the system built
from this branch.

**Automated tests:** 353 pass (268 before), lint clean. 15 new scenarios in
`recording.feature`.

**With the real models**, a 6-minute stretch of a two-person meeting:

| Run | Result |
| --- | --- |
| Streamed over the API in real time, a piece every 5 s | 9 passes of 9 to 13 s each for about 45 s of audio. At stop, 306 of 360 s were transcribed; the rest took 2 s. Done 222 s after stop, 2 speakers. |
| Recorded in Chrome through the web page (microphone replaced by the same audio) | Text so far appeared after 44 s and grew every 30 to 45 s. Done 220 s after stop, 2 speakers, 360.06 s long. |
| Same audio uploaded as a file, twice | Done after 228 s and 281 s. In the second run: 80 s speech-to-text, 199 s speaker identification. |

What this shows, and what it does not:

- The mechanism works end to end, including with a real browser.
- When the recording stops, the speech-to-text work (about 80 s for this
  clip) is already done but for a few seconds.
- Speaker identification took between about 145 and 215 s for the same clip
  from run to run. On a clip this short that variation is as large as the
  saving, so the totals above do not show the saving cleanly. The expected
  saving for a long meeting is the speech-to-text share measured at the top
  of this plan (about 13 of 46 minutes); that was not re-measured with a
  75-minute live recording.

**Text compared with transcribing the file in one go:** 91% of the words are
identical and in the same order (streamed: 91.0%, Chrome: 91.2%). The
differences are spread over the whole clip, not gathered at the borders
between passes (9 of 65 lie within 4 s of one, which is what chance gives),
and are mostly filler words. For scale: transcribing the same audio in one
go, but starting 7 s later, gives 89.9% identical words. On this
conversational recording the passes change the text no more than Whisper's
own sensitivity to where it starts. Which version is more accurate was not
judged.

**Decoder:** starting part of the way into an Opus file is 7 ms early; a file
cut off at an arbitrary byte decodes up to the cut.

**Not verified:** Firefox and Safari; a recording longer than 6 minutes; a
real microphone (Chrome was fed the audio as a fake capture device);
recording while a long file is being processed.
