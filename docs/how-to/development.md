# Development

## Run the tests

```sh
./t.sh                                   # lint + everything (starts PostgreSQL)
./t.sh tests/unit                        # a subset; arguments go to pytest
./t.sh -m FR-34                          # scenarios verifying one requirement
./t.sh tests/acceptance -k "crashed"     # by scenario name
```

Tests run in the `test` image (no speech models, about 1 GB). Source, tests
and `scripts/` are mounted, so no rebuild is needed after editing.

`./t.sh` stops the PostgreSQL container when it ends. If you run
`docker compose -f compose.test.yaml run --rm --build test` yourself (needed
after changing `requirements/*.txt` or the `Dockerfile`), the database keeps
running; remove it with `docker compose -f compose.test.yaml down`.

Without Docker: `pip install -r requirements/base.txt -r requirements/dev.txt`
and `pytest`; the PostgreSQL contract tests are skipped unless
`TEST_DATABASE_URL` is set, the ffmpeg tests unless ffmpeg is installed.

The rules in short, for people and coding agents alike, are in
[AGENTS.md](../../AGENTS.md).

## Continuous integration and releases

Two GitHub Actions workflows live in `.github/workflows/`:

| Workflow | When | What |
| --- | --- | --- |
| `ci.yml` | every pull request, every push to `main` | Builds the `test` image (cached) and runs `docker compose -f compose.test.yaml run --rm test`: the same format check, lint and tests as `./t.sh`. |
| `release.yml` | a pushed tag `v*` | Runs `ci.yml`, then pushes the `api` and the CPU `worker` images to `ghcr.io/<owner>/audio-scribe-api` and `-worker`, tagged `1.2.3`, `1.2` and `latest`. |

To release: `git tag v1.2.0 && git push origin v1.2.0`. The GPU and Vulkan
workers are not published; build them with the compose override files.
Making `ci` a required status check for `main` is a repository setting
(Settings, Branches), not part of the code.

## Workflow: specification first

1. **Requirement** — add or change a line in `docs/requirements.md`.
2. **Scenario** — describe the behaviour in `tests/features/*.feature`, tagged
   with the requirement ID. Add step definitions in
   `tests/acceptance/test_features.py` if new phrases are needed.
3. **Red** — run it and see it fail for the right reason.
4. **Unit tests** for the domain rule or adapter behaviour the scenario needs.
5. **Green** — the simplest code that passes, in the innermost layer where it
   makes sense.
6. **Refactor**, then `./t.sh` (lint, format check, all tests).

## Where things go

| You want to… | Change |
| --- | --- |
| Add an output format | A renderer in `domain/rendering.py` + entry in `FORMATS`; tests in `tests/unit/test_rendering.py`. API, settings and web page pick it up. |
| Change retry or lease rules | `domain/job.py`; `tests/unit/test_job.py` and `reliability.feature`. |
| Use another speech-to-text engine | A new adapter implementing `SpeechRecognizer`; wire it in `bootstrap.load_engines`. |
| Use another diarizer | A new adapter implementing `Diarizer`; same place. |
| Store jobs elsewhere | A new `JobRepository`; add it to the `stores` fixture in `tests/contract/test_job_repository.py` so it must pass the same contract. |
| Change how a recording in progress is cut into pieces | `Draft.extended` in `domain/draft.py`; `tests/unit/test_draft.py` and `recording.feature`. |
| Add an API endpoint | A method on `JobService` (with a scenario), then a route in `entrypoints/api.py` and a test in `tests/integration/test_api.py`. |

## Conventions

- The dependency rule (see [architecture](../architecture.md#layers)) is
  checked by `tests/unit/test_architecture.py`.
- Use cases receive their collaborators through the constructor; only
  `bootstrap.py` creates adapters.
- Time comes from the `Clock` port, never from `datetime.now()` in domain or
  application code — this is what lets the scenarios "wait" 120 seconds
  instantly.
- Formatting and lint: `ruff format .` and `ruff check .` (run by `./t.sh`).

## Trying the real models locally

The automated tests fake the speech models. To exercise the real ones:

```sh
WHISPER_MODEL=tiny docker compose up -d --build
cp some-recording.mp3 data/inbox/
docker compose logs -f worker
```

`tiny` downloads in seconds and is enough to see the pipeline work end to end.

To exercise whisper.cpp without a GPU, use the Vulkan image on the CPU:

```sh
WHISPER_MODEL=tiny SPEECH_ENGINE=whisper-cpp docker compose \
  -f compose.yaml -f compose.vulkan.yaml run --rm -e DEVICE=cpu worker
```
