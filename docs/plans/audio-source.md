# Choosing the audio source

Status: done. Not tried in a real browser by the author; see Verification.

## Why

The web page recorded `getUserMedia({ audio: true })`, the default
microphone. The far end of a Teams, Slack or Zoom call was only recorded if
it came out of loudspeakers, so a meeting could not be recorded cleanly.

## Scope

In: choosing an input device (which includes virtual loopback devices),
recording the audio of a shared tab or screen, mixing it with the microphone
(FR-59). Documentation of loopback devices and OBS.

Out: anything on the server. Capture stays in the browser and the server
keeps accepting whatever ffmpeg decodes. Separate tracks per participant.
Level meters.

## Decisions

**1. Capture stays in the browser.** Considered and rejected: capturing a
device on the server with ffmpeg. The worker runs in Docker (on a Mac it
runs natively, but the page may be used from another machine), so the server
cannot see the user's sound devices.

**2. Three ways in, none needing code on the machine:** a device list
(`enumerateDevices`, `deviceId`), `getDisplayMedia` for shared audio, and the
two mixed through the Web Audio API (`MediaStreamAudioDestinationNode`) into
one stream for the unchanged `MediaRecorder`. Considered and rejected: a
desktop helper or browser extension for system audio. It would work
everywhere but is another thing to install and maintain.

**3. Browsers cannot share whole-system audio on macOS**, so a loopback
device is documented for it and for desktop apps; OBS is documented as one
way to feed such a device. Considered and rejected: bundling a virtual audio
driver; it needs a kernel-level install and licensing the project cannot
take on.

**4. A share without audio is an error, not a silent recording.** Choosing a
window instead of a tab, or forgetting the checkbox, gives a video-only
stream; the page refuses it with instructions.

**5. The last choice is remembered** in `localStorage`, used only as a
convenience; the page works without it.

## Steps

FR-59 in `docs/requirements.md`; a markup test in
`tests/integration/test_api.py`; the picker and `sourceStream()` in
`scribe/entrypoints/static/index.html`; `docs/how-to/recording.md`.

## Risks

| Risk | Handling |
| --- | --- |
| Device names are empty until the user has allowed the microphone | The list is read again after the first access and on `devicechange`. |
| Mixed mono audio blurs speakers | Diarization works on voices as before; a call with the far end heard through the mix is what it is built for. |
| A browser changes how `getDisplayMedia` audio works | The check for an audio track and the documentation table name the browsers that were assumed. |

## Verification

`./t.sh` covers the page markup only. Not verified: any of the capture paths
in a real browser (microphone list, tab share, system audio on Windows,
BlackHole on macOS, OBS, VB-Cable, PulseAudio) and Firefox and Safari. The
instructions for the loopback devices and OBS are from their documented
behaviour, not from trying them.
