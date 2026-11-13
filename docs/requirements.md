# Requirements

Audio Scribe turns audio recordings into text transcripts that say who spoke
when. It runs unattended on one machine with Docker Compose.

Each requirement has an ID. The executable specifications in
[`tests/features/`](../tests/features) are tagged with the IDs they verify.

## 1. Stakeholders and context

| Who | Needs |
| --- | --- |
| Operator | Start the system with one command, drop files in a folder, get transcripts back. |
| Occasional user | Upload a file in a browser, or record a meeting there, and read and download the transcript. |
| Integrator | Submit files and fetch results from scripts over HTTP. |

Out of scope: identifying speakers while a recording is still going on,
recording the sound of other applications, user accounts and authentication,
summarisation or any other language-model post-processing, speaker recognition
across files (a "Speaker 1" in one file is unrelated to "Speaker 1" in another).

## 2. Functional requirements

### Intake

| ID | Requirement |
| --- | --- |
| FR-01 | The system watches an inbox folder, including sub-folders, and queues every new audio file it finds. |
| FR-02 | A file is only queued once it has stopped changing for a configurable time, so a file that is still being copied is never processed half-written. |
| FR-03 | Files that are not audio (by extension), hidden files and temporary download files are left untouched. |
| FR-04 | Popular audio formats are accepted (mp3, wav, m4a, aac, flac, ogg, opus, wma, aiff, amr, …), as are video containers (mp4, mkv, mov, webm, …), of which the audio track is used. |
| FR-05 | A file can also be submitted through the HTTP API or the web page, with per-file options: language, whether to identify speakers, and the expected number of speakers. |

### Transcription

| ID | Requirement |
| --- | --- |
| FR-10 | Speech is converted to text with timestamps. The spoken language is detected automatically unless one is given. |
| FR-11 | For conversations, each stretch of speech is attributed to a distinct speaker, labelled "Speaker 1", "Speaker 2", … in order of first appearance. |
| FR-12 | Speaker identification can be turned off globally or per file; the transcript then has no speaker labels. |
| FR-13 | Speech-to-text and speaker identification use dedicated local speech models. No large language model is used, and no audio or text leaves the machine. |
| FR-14 | A recording without speech produces an empty transcript, not a failure. |

### Live recording

| ID | Requirement |
| --- | --- |
| FR-50 | A recording can be made in the web page (microphone) or sent through the HTTP API piece by piece; the audio is stored on the server as it arrives. |
| FR-51 | Speech-to-text starts while the recording is still going on, so that when it ends only the remainder is left to transcribe. |
| FR-52 | Text is kept only once it is settled: the newest seconds are transcribed again when more audio has arrived, and a piece ends where the recogniser ends a sentence, so no sentence is cut in two. |
| FR-53 | When the recording ends, speakers are identified over the whole recording, and the result is a job and a transcript like those of any file: all formats, archived original, speaker names, re-run. |
| FR-54 | The text transcribed so far can be read while the recording is going on. |
| FR-55 | Each piece of audio is stored exactly once and in order: a piece that is sent twice changes nothing, a piece that would leave a gap is refused. |
| FR-56 | A recording that receives no audio for a configurable time (a closed browser, a lost connection) is ended automatically and transcribed with what arrived. |
| FR-57 | A recording in progress does not occupy a worker: other jobs are processed in between. What has been transcribed survives a restart or crash of the worker. |
| FR-58 | A recording that has ended or was cancelled accepts no more audio; one that ends without any audio leaves no job behind. |

### Output

| ID | Requirement |
| --- | --- |
| FR-20 | For every finished file a transcript is written to the output folder, mirroring the sub-folder the file was dropped in. |
| FR-21 | Supported formats are Markdown, plain text, JSON (with word timings), SRT and WebVTT. Markdown is the default; the set of formats written is configurable. |
| FR-22 | Any supported format can be fetched for any finished job through the API, regardless of which formats were written to disk. |
| FR-23 | A transcript never overwrites the transcript of a different file with the same name. |
| FR-24 | After success the original file is moved to an archive folder (or deleted, if so configured). |
| FR-25 | Speakers can be given real names after the fact; the names appear in every format and the files on disk are updated. |

### Queue and robustness

| ID | Requirement |
| --- | --- |
| FR-30 | Work is managed as jobs in a durable queue. Queued and finished jobs survive a restart of any or all containers. |
| FR-31 | A job is processed by exactly one worker at a time, also when several workers run. |
| FR-32 | A job that fails for a transient reason is retried automatically with increasing delay, up to a configurable number of attempts. |
| FR-33 | A file that cannot be decoded as audio fails immediately, without retries. |
| FR-34 | If a worker dies or hangs while processing, its job is detected and returned to the queue; a job that repeatedly kills its worker is failed once its attempts are used up. |
| FR-35 | When a job fails for good, the original is moved to a failed folder together with a text file explaining why. |
| FR-36 | Stopping a worker gracefully returns its job to the queue without using up an attempt. |
| FR-37 | A file that was taken from the inbox but never registered as a job (crash in between) is put back in the inbox on the next start. |
| FR-38 | A worker whose models cannot be loaded (for example a missing Hugging Face token) takes no jobs, reports the reason, and keeps trying; queued jobs wait instead of failing. |

### Operation

| ID | Requirement |
| --- | --- |
| FR-40 | Jobs can be listed with status, stage and progress; a failed, cancelled or finished job can be re-run; a queued or running job can be cancelled; a job can be deleted. |
| FR-41 | A web page shows the queue and worker state, accepts uploads and recordings, and shows and downloads transcripts. |
| FR-42 | A health endpoint reports whether the database is reachable, the number of jobs per status, and the state of every worker. |

## 3. Quality requirements

| ID | Requirement |
| --- | --- |
| QR-01 | **Deployment:** the whole system starts with `docker compose up`; the only prerequisite is Docker (plus the NVIDIA Container Toolkit for CUDA). The one exception is Apple Metal, which containers cannot reach: there the worker runs on the host. |
| QR-02 | **Hardware:** runs on CPU only by default; a GPU is enabled by configuration, without code changes: NVIDIA (CUDA) and AMD/Intel (Vulkan) with a compose override file, Apple (Metal) with a host worker. |
| QR-08 | **No silent slow-down:** a worker configured for a GPU that it cannot use reports this and takes no jobs, rather than computing on the CPU. |
| QR-03 | **Privacy:** after the one-time model download the system works with no network access. |
| QR-04 | **Security:** the web page and API are reachable from the local machine only, unless the operator opts in to exposing them. |
| QR-05 | **Maintainability:** business rules do not depend on frameworks, the database or the speech models; these sit behind interfaces and can be replaced. |
| QR-06 | **Testability:** all behaviour above is covered by automated tests that run without downloading any model. |
| QR-07 | **Observability:** every component logs to standard output; failures are visible in the web page and on disk. |

## 4. Constraints

- Speaker identification uses the `pyannote` community model, which needs a
  free Hugging Face token once, to download it.
- Accuracy and speed are those of the chosen Whisper model and the hardware.
- Transcribing while recording only helps where speech-to-text is faster than
  real time, and it does not shorten speaker identification, which on a CPU
  is the larger part of the work.
- A browser only gives access to the microphone on `localhost` or over HTTPS.
