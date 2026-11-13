# Record a meeting

Record in the web page and have the transcript sooner: speech is turned into
text while the recording is still going on. When you stop, only the last
seconds and speaker identification are left.

## Record

1. Open <http://localhost:8090>.
2. Optionally set the language and the number of speakers. They apply to the
   recording as they do to an upload.
3. Click **Record** and allow the browser to use the microphone.
4. The recording appears in the job list as *recording*. After half a minute
   or so the text so far appears under the button and keeps growing. The
   newest five to ten seconds are always missing: they are transcribed again
   once more has been said.
5. Click **Stop**. The job changes to *processing*: the rest is transcribed,
   then speakers are identified. After that it is a job like any other:
   view, download, name the speakers, re-run.

The transcript is written to `data/output/Recording <date> <time>.md` and the
audio is kept in `data/archive/`.

Keep the tab open while recording. If you close it, or the connection is lost
for more than two minutes (`RECORDING_IDLE_SECONDS`), the recording is ended
and what arrived is transcribed.

## How much time it saves

It saves the speech-to-text part of the work, not speaker identification.
Measured on a 16-thread CPU with `large-v3-turbo` and a 75-minute meeting:

| | After the meeting ends |
| --- | --- |
| Upload the finished file | about 46 min (13 min speech-to-text, 33 min speakers) |
| Record in the page | about 34 min (speakers only) |

These figures come from separate measurements of the two stages on an
uploaded file, not from a 75-minute live recording. On a GPU, where speaker
identification takes a few minutes, the transcript is
ready shortly after the meeting. With `DIARIZE=false`, or *Identify speakers*
unticked, it is ready within seconds of stopping.

The saving depends on speech-to-text being faster than real time. With a
slow machine or a large backlog of other files the recording is simply
transcribed later; nothing is lost.

## Good to know

- **Microphone only.** The page records what the microphone hears. The other
  side of a video call is only recorded if it comes out of the loudspeakers.
- **`localhost` or HTTPS.** Browsers refuse microphone access to pages loaded
  over plain HTTP from another machine. If you expose the page on the network
  (`BIND_ADDR=0.0.0.0`), put it behind a reverse proxy with HTTPS to record
  from other machines.
- **Other files are not blocked.** A recording in progress only needs the
  worker for a few seconds every half minute; files in the queue are
  processed in between. The other way round, a long file that is being
  processed delays the next pass until it is done.
- **Browsers.** Chrome, Edge and Firefox record WebM/Opus, which is what the
  automated tests cover. Safari records MP4; the server accepts it, but this
  has not been tried.
- **The text is not word for word what uploading the finished file would
  give**, because the recogniser works through the recording in pieces. In a
  test with a six-minute conversation about 9% of the words differed, mostly
  filler words, spread evenly rather than at the borders between pieces.
  That is as much as Whisper's output changes when the same file is merely
  started a few seconds later. To redo a recording in one go, click
  **Re-run** on the finished job.

## If something goes wrong

| What you see | What happened | What to do |
| --- | --- | --- |
| "The microphone cannot be used" | The browser or the operating system denied access. | Allow the microphone for the page in the browser's site settings. |
| "This browser cannot record here" | The page is not on `localhost` or HTTPS. | See above. |
| "The server no longer accepts this recording", with a *Save the recording* link | The job was cancelled or deleted, or the server considered the recording ended. | Save the recording with the link and upload it as a file. |
| "The server cannot be reached", with the same link | The API did not answer five times in a row. | Save the recording; check `docker compose ps`; upload the file when the service is back. |
| The text so far stays empty | No worker is running, or it is busy with a long file. | The banner at the top says if no worker is running. The recording is still stored and will be transcribed. |

## From a script

The same mechanism is available over HTTP for any source of audio; see
[Send a recording while it is being made](api.md#send-a-recording-while-it-is-being-made).
