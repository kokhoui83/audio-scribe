# Record a meeting

Record in the web page and have the transcript sooner: speech is turned into
text while the recording is still going on. When you stop, only the last
seconds and speaker identification are left.

## Record

1. Open <http://localhost:8090>.
2. Optionally set the language and the number of speakers. They apply to the
   recording as they do to an upload.
3. Choose what to record (see [Choose what to record](#choose-what-to-record);
   the default is the microphone), click **Record** and allow what the browser asks.
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

## Choose what to record

The page records one of these. Pick the first that works for you:

| I want to record | Use | Install |
| --- | --- | --- |
| My own voice | **a microphone**, the default or one from the list | nothing |
| A call in a browser tab (Teams, Slack, Meet, Zoom on the web) | **a meeting**, then choose the tab and tick *Share tab audio* | nothing (Chrome or Edge) |
| A call in a desktop app, on Windows | **a meeting**, then choose *Entire screen* and tick *Share system audio* | nothing (Chrome or Edge) |
| A call in a desktop app, on a Mac | a **loopback device** chosen in the microphone list | BlackHole, see below |
| One application only, or a mix I build myself | **OBS** feeding a loopback device | OBS and a loopback device |

With **a meeting**, *Also record my microphone* is ticked by default so that
both sides of the call are in the recording: the page mixes the shared audio
with the microphone. Untick it to record the shared audio alone. If you stop
sharing with the browser's own *Stop sharing* button, the recording ends as if
you had clicked **Stop**. If the browser shares no audio (you forgot to tick
the box, or you use Firefox or Safari), the page says so instead of recording
silence.

Before the browser has been given microphone access it lists only the default
input. Click **Show all inputs** to allow access and see the others, for
example a loopback device. The browser keeps the microphone open while you
choose; start recording or click **Done choosing** to release it.

What the browser can share:

| | Windows | macOS | Linux |
| --- | --- | --- | --- |
| Microphone and other input devices | Chrome, Edge, Firefox, Safari | same | same |
| Audio of a tab | Chrome, Edge | Chrome, Edge | Chrome, Edge |
| Audio of the entire screen | Chrome, Edge | Chrome 141 or later on macOS 14.2 or later; otherwise use a loopback device | partly |

### A loopback device

A loopback device is a virtual sound card: an application plays into it and
the page records from it as from a microphone. It is the way to capture a
desktop app on a Mac without system-audio sharing, and it works with any browser.

**macOS (BlackHole)**

1. `brew install blackhole-2ch`, then restart the Mac if sound does not
   appear.
2. Open *Audio MIDI Setup*, click **+**, choose *Create Multi-Output Device*,
   and tick your speakers or headphones **and** *BlackHole 2ch*. Tick *Drift
   correction* for BlackHole. This lets you hear the call while it is copied.
3. In *System Settings → Sound → Output* select the Multi-Output Device (or
   select it only in the call app's audio settings).
4. In the page choose *a microphone* and select **BlackHole 2ch**.
5. To record your own voice too, create an *Aggregate Device* in Audio MIDI
   Setup that contains BlackHole 2ch and your microphone, and select that.
   (Or use a meeting share, which mixes the microphone in itself.)

Set the output back to the speakers afterwards; the Multi-Output Device has
no volume control.

**Windows (VB-Cable)**

1. Install VB-Cable from vb-audio.com. It adds *CABLE Input* (a playback
   device) and *CABLE Output* (a recording device).
2. Set the call app's speaker to **CABLE Input**.
3. To hear the call too: *Sound settings → More sound settings → Recording →
   CABLE Output → Properties → Listen*, tick *Listen to this device* and
   choose your speakers.
4. In the page choose *a microphone* and select **CABLE Output**.

On Windows, sharing the entire screen with system audio needs none of this.

**Linux (PulseAudio or PipeWire)**

```sh
pactl load-module module-null-sink sink_name=scribe sink_properties=device.description=Scribe
pactl load-module module-loopback source=scribe.monitor     # to hear it as well
```

Send the call app's output to *Scribe* (for example in `pavucontrol`) and
choose **Monitor of Scribe** in the page.

### OBS

OBS has no virtual microphone for audio (its virtual camera is video only),
so it needs a loopback device as above. It is worth it when you want the
audio of one application only, or a mix of several sources.

1. In OBS add *Application Audio Capture* (Windows) or *Audio Output
   Capture* as a source, and your microphone if you want it recorded.
2. *Settings → Audio → Advanced → Monitoring Device*: select the loopback
   device's playback side (*CABLE Input* or *BlackHole 2ch*).
3. In the mixer, open each source's *Advanced Audio Properties* and set
   *Audio Monitoring* to **Monitor and Output** (OBS's own recording and stream
   keep working) or **Monitor Only**.
4. In the page choose *a microphone* and select the loopback device
   (*CABLE Output* or *BlackHole 2ch*).

The page does not need OBS to be recording or streaming; it only needs OBS
to be running and playing audio into the device.

### From any other tool

Anything that can produce audio can send it through the API, for example
`ffmpeg` capturing a device; see [From a script](#from-a-script).

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

- **Meetings need a choice.** The default is the microphone, which hears the
  other side of a call only if it comes out of loudspeakers. To record both
  sides, see the next section.
- **`localhost` or HTTPS.** Browsers refuse microphone and screen-share access to pages loaded
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
| "The audio cannot be recorded: The microphone…" | The browser or the operating system denied access to the input. | Allow the microphone for the page in the browser's site settings. On macOS also check *System Settings → Privacy & Security → Microphone*. |
| "Sharing was not started" | The share dialog was cancelled or blocked. | Click **Record** again and choose a tab or screen. |
| "The shared screen or tab has no audio" | *Share audio* was not ticked, the chosen window has no audio, or the browser cannot share audio. | Share a tab or, on Windows, the entire screen, with audio ticked; use Chrome or Edge; or use a loopback device. |
| The recording is silent or has only my voice | The wrong device was chosen, or the call app does not play into the loopback device. | Play a sound and watch the level in the system's sound settings; check the call app's speaker setting. |
| "This browser cannot record here" | The page is not on `localhost` or HTTPS. | See above. |
| "The server no longer accepts this recording", with a *Save the recording* link | The job was cancelled or deleted, or the server considered the recording ended. | Save the recording with the link and upload it as a file. |
| "The server cannot be reached", with the same link | The API did not answer five times in a row. | Save the recording; check `docker compose ps`; upload the file when the service is back. |
| The text so far stays empty | No worker is running, or it is busy with a long file. | The banner at the top says if no worker is running. The recording is still stored and will be transcribed. |

## From a script

The same mechanism is available over HTTP for any source of audio; see
[Send a recording while it is being made](api.md#send-a-recording-while-it-is-being-made).
