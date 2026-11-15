# Working on Audio Scribe

Instructions for anyone changing this repository, human or coding agent.
The longer explanations are in [docs/how-to/development.md](docs/how-to/development.md),
[docs/architecture.md](docs/architecture.md) and [docs/design.md](docs/design.md).

## Commands

```sh
./t.sh                          # format check, lint and every test (in Docker, with PostgreSQL)
./t.sh tests/unit -x            # a subset; arguments go to pytest
./t.sh -m FR-34                 # the scenarios that verify one requirement
docker compose up -d --build    # run the system at http://localhost:8090
```

A change is finished when `./t.sh` passes. After changing
`requirements/*.txt` or the `Dockerfile`, add `--build`:
`docker compose -f compose.test.yaml run --rm --build test`.

## Workflow: specification first

Work in this order. Do not write production code before a test fails for it.

1. **Requirement.** Add or change a line in `docs/requirements.md`. New
   behaviour gets a new ID (`FR-nn`, `QR-nn`); IDs are never reused.
2. **Scenario.** Describe the behaviour in `tests/features/*.feature`, tagged
   with the requirement ID. Add steps to `tests/acceptance/test_features.py`
   only when no existing phrase fits.
3. **Red.** Run it and check that it fails for the reason you expect.
4. **Unit tests** for the domain rule or the adapter behaviour the scenario
   needs. Contract tests for anything a repository must do.
5. **Green.** The simplest code that passes, in the innermost layer where it
   makes sense.
6. **Refactor**, then `./t.sh`.
7. **Documentation** in the same change (see below).

Larger features start with a plan in `docs/plans/<feature>.md`: why, scope,
decisions with the alternatives that were rejected, steps, risks, and what was
verified at the end.

## Architecture rules

Dependencies point inwards only. `tests/unit/test_architecture.py` enforces
this.

```
entrypoints -> bootstrap -> adapters -> application -> domain
```

- `scribe/domain` holds the business rules: what may happen to a job and
  when, how a transcript is built. Standard library only.
- `scribe/application` holds the use cases and the ports (`ports.py`) they
  need. No framework, no database, no speech library.
- `scribe/adapters` holds one implementation per port.
- `scribe/bootstrap.py` is the only place that creates adapters.
- `scribe/entrypoints` are thin: parse input, call a use case, format output.

Further rules:

- A job changes state only through a method of `Job`, applied with
  `JobRepository.update(job_id, mutate)`. SQL never decides a rule.
- Time comes from the `Clock` port. Never call `datetime.now()` or `sleep()`
  in domain or application code; this is what lets tests "wait" instantly.
- Use cases receive their collaborators through the constructor.
- A new `JobRepository` method needs a contract test, which then runs against
  both the in-memory and the PostgreSQL implementation.
- Database changes are additive and idempotent (`CREATE … IF NOT EXISTS`,
  `ADD COLUMN IF NOT EXISTS`); existing installations upgrade on start.
- Speech models are never loaded in tests. They sit behind ports and are
  replaced by the fakes in `tests/fakes.py`.

## Code style

- Python 3.12, `ruff format` and `ruff check` (line length 110), type hints
  on every function.
- Names say what a thing is for; a module starts with a docstring that
  explains its role.
- Comments explain why, not what. No commented-out code.
- Small functions, no speculative options. Add a setting only when someone
  needs to change the value.
- Error messages are written for the operator: say what happened and, where
  possible, what to do.
- Test names are sentences (`test_a_job_is_claimed_only_once`).

## Documentation to keep in step

| Changed | Update |
| --- | --- |
| Behaviour | `docs/requirements.md`, the feature files |
| A port, layer, container or key decision | `docs/architecture.md` |
| A mechanism (queue, files, pipeline) | `docs/design.md` |
| A setting | `docs/how-to/configuration.md`, `.env.example`, `compose.yaml`, `tests/unit/test_settings.py` |
| An endpoint | `docs/how-to/api.md` |
| How to use or operate it | the matching file in `docs/how-to/` and the tables in `README.md` and `docs/README.md` |

State what was not verified (a GPU you do not have, a browser you did not
try) rather than leaving it out.

## Git

- Branch from `main`: `feature/<name>` or `fix/<name>`. Never commit to
  `main` directly.
- One logical change per commit; the subject says what changes for the user,
  in the imperative ("Add live recording").
- Do not commit `.env`, `data/`, `models/` or editor settings.
- Commit and push only when asked.
