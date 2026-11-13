# Getting started

## Prerequisites

- Docker with Docker Compose v2
- About 5 GB of disk for images and models
- For speaker identification: a free Hugging Face account

## 1. Configure

```sh
cp .env.example .env
```

Get the token for the speaker model (needed once, for the download):

1. Sign in at <https://huggingface.co>.
2. Open <https://hf.co/pyannote/speaker-diarization-community-1> and accept
   the conditions.
3. Create a token of type *Read* at <https://hf.co/settings/tokens>.
4. Put it in `.env`: `HF_TOKEN=hf_...`

No account? Set `DIARIZE=false`; transcripts then have no speaker labels.

## 2. Start

```sh
docker compose up -d --build
```

The first build downloads PyTorch (several minutes). On first start the worker
downloads the Whisper model (about 1.6 GB for the default `large-v3-turbo`)
and the speaker model. Follow along with:

```sh
docker compose logs -f worker
```

## 3. Transcribe

- **Folder:** copy files into `data/inbox/`. Sub-folders are fine and are
  mirrored in the output.
- **Browser:** open <http://localhost:8090> and drop files on the page. You
  can set the language and the number of speakers per upload.

A file is picked up once it has stopped changing for 5 seconds.

## 4. Collect

| Folder | Content |
| --- | --- |
| `data/output/` | `name.md` (and other formats if configured) |
| `data/archive/` | The original, after success |
| `data/failed/` | The original and `name.error.txt`, after final failure |

In the web page, **View** shows the transcript, lets you name the speakers
(the files on disk are updated) and download any format.

## 5. Stop

```sh
docker compose stop      # a running job goes back to the queue
docker compose down      # also removes the containers; data and models are kept
```

## Tips for better results

- If you know how many people speak, say so (web page field, or
  `num_speakers` in the API): it makes speaker identification more accurate.
- Set `DEFAULT_LANGUAGE` if all your recordings are in one language.
- On CPU, `WHISPER_MODEL=small` is several times faster than the default at
  some cost in accuracy.
