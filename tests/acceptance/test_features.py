"""Step definitions for tests/features/*.feature."""

from __future__ import annotations

import io

from pytest_bdd import given, parsers, scenarios, then, when

from scribe.application.management import OriginalMissing, TranscriptNotReady
from scribe.domain.job import InvalidTransition, JobOptions
from scribe.domain.worker import ERROR, READY
from tests.fakes import NOT_AUDIO, recording

scenarios("intake.feature", "transcription.feature", "reliability.feature", "management.feature")

DEFAULT_RECORDING = recording(("anna", "Hello there."))


def _table(datatable) -> list[dict[str, str]]:
    header, *rows = datatable
    return [dict(zip(header, row, strict=True)) for row in rows]


def _script(datatable) -> str:
    return recording(*((row["voice"], row["says"]) for row in _table(datatable)))


# ------------------------------------------------------------------ settings


@given("speaker identification is turned off")
def _(world):
    world.diarize = False


@given(parsers.parse('the default language is "{language}"'))
def _(world, language):
    world.default_language = language


@given(parsers.parse('the output formats are "{formats}"'))
def _(world, formats):
    world.output_formats = tuple(f.strip() for f in formats.split(","))


@given("originals are not archived")
def _(world):
    world.archive_originals = False


# -------------------------------------------------------------------- inbox


@given(parsers.parse('a recording "{name}" is dropped in the inbox'))
def _(world, name):
    world.drop(name, DEFAULT_RECORDING)


@given(parsers.parse('an empty file "{name}" is dropped in the inbox'))
def _(world, name):
    world.drop(name, "")


@given("the watcher scans the inbox")
@when("the watcher scans the inbox")
def _(world):
    world.watcher.scan()


@when(parsers.parse('more data is written to "{name}" in the inbox'))
def _(world, name):
    world.drop(name, DEFAULT_RECORDING * 2)


@when(parsers.parse("the watcher has seen the inbox unchanged for {seconds:d} seconds"))
def _(world, seconds):
    world.watcher.scan()
    world.clock.advance(seconds)
    world.watcher.scan()


@given(parsers.re(r"(?P<seconds>\d+) seconds? pass(es)?"))
@when(parsers.re(r"(?P<seconds>\d+) seconds? pass(es)?"))
def _(world, seconds):
    world.clock.advance(int(seconds))


@given(
    parsers.parse('"{name}" was taken from the inbox by a watcher that crashed before registering the job')
)
def _(world, name):
    world.drop(name, DEFAULT_RECORDING)
    world.files.stage_from_inbox(name, "job-that-never-was")
    assert world.folder("inbox") == []


@when("the system recovers orphaned files")
def _(world):
    world.housekeeper.recover_orphans()


# ------------------------------------------------------------ queued / done


@given(parsers.parse('a queued recording "{name}" in which:'))
def _(world, name, datatable):
    world.queue_recording(name, _script(datatable))


@given(parsers.parse('a queued recording "{name}"'))
def _(world, name):
    world.queue_recording(name, DEFAULT_RECORDING)


@given(parsers.parse('a queued recording "{name}" without speech'))
def _(world, name):
    world.queue_recording(name, "(silence)\n")


@given(parsers.parse('a queued file "{name}" that cannot be decoded'))
def _(world, name):
    world.queue_recording(name, NOT_AUDIO)


@given(parsers.parse('a finished recording "{name}" in which:'))
def _(world, name, datatable):
    world.queue_recording(name, _script(datatable))
    world.work()
    assert world.job(name).status == "done"


@given(parsers.parse('a finished recording "{name}"'))
def _(world, name):
    world.queue_recording(name, DEFAULT_RECORDING)
    world.work()
    assert world.job(name).status == "done"


@given("the worker processes the queue")
@when("the worker processes the queue")
def _(world):
    world.work()


# ---------------------------------------------------------------- failures


@given(parsers.re(r'the speech recogniser will fail (?P<times>\d+) times? with "(?P<message>.+)"'))
def _(world, times, message):
    world.recognizer.failures = [message] * int(times)


@given(parsers.parse('a worker crashes while processing "{name}"'))
def _(world, name):
    world.crash_worker_on(name)


@given("the housekeeper runs")
@when("the housekeeper runs")
def _(world):
    world.housekeeper.reap()


@given(parsers.parse('transcribing "{name}" takes {minutes:d} minutes'))
def _(world, name, minutes):
    world.slow_minutes = minutes


@when("the worker processes the queue while the housekeeper runs every minute")
def _(world):
    def slowly(progress):
        for minute in range(world.slow_minutes):
            world.clock.advance(60)
            progress(minute / world.slow_minutes)
            world.housekeeper.reap()

    world.recognizer.during.append(slowly)
    world.work()


@given("the worker is asked to stop while transcribing")
def _(world):
    world.recognizer.during.append(lambda progress: world.worker.request_stop())


@given("the job is cancelled while it is being transcribed")
def _(world):
    def cancel(progress):
        world.service.cancel(world.jobs.list()[0].id)

    world.recognizer.during.append(cancel)


@given(parsers.parse('the speech models cannot be loaded because "{reason}"'))
def _(world, reason):
    world.engines_error = reason


@when("the speech models become available")
def _(world):
    world.engines_error = None


# ------------------------------------------------------------ user actions


@when(parsers.parse('"{name}" is uploaded with language "{language}" and {speakers:d} speakers'))
def _(world, name, language, speakers):
    world.service.submit_upload(
        name, io.BytesIO(DEFAULT_RECORDING.encode()), JobOptions(language=language, num_speakers=speakers)
    )


@when(parsers.parse('"{name}" is uploaded without speaker identification'))
def _(world, name):
    world.service.submit_upload(name, io.BytesIO(DEFAULT_RECORDING.encode()), JobOptions(diarize=False))


@when(parsers.parse('the transcript of "{name}" is requested as "{fmt}"'))
def _(world, name, fmt):
    world.attempt(lambda: world.service.transcript_text(world.job(name).id, fmt))


@when(parsers.parse('the speakers of "{name}" are named:'))
def _(world, name, datatable):
    names = {row["label"]: row["name"] for row in _table(datatable)}
    world.service.rename_speakers(world.job(name).id, names)


@given(parsers.parse('the file "{name}" in the failed folder is replaced by a proper recording'))
def _(world, name):
    path = world.data_dir / "failed" / name
    assert path.exists()
    path.write_text(DEFAULT_RECORDING, encoding="utf-8")


@when(parsers.parse('the job for "{name}" is retried'))
def _(world, name):
    world.attempt(lambda: world.service.retry(world.job(name).id))


@when(parsers.parse('the job for "{name}" is cancelled'))
def _(world, name):
    world.attempt(lambda: world.service.cancel(world.job(name).id))


@when(parsers.parse('the job for "{name}" is deleted'))
def _(world, name):
    world.service.delete(world.job(name).id)


# ------------------------------------------------------------------ outcomes


@then("no job exists")
def _(world):
    assert world.jobs.list() == []


@then(parsers.re(r'the job for "(?P<name>.+)" is (?P<status>queued|processing|done|failed|cancelled)'))
def _(world, name, status):
    job = world.job(name)
    assert job.status == status, f"{job.status}: {job.error}"


@then(parsers.re(r'the job for "(?P<name>.+)" took (?P<attempts>\d+) attempts?'))
def _(world, name, attempts):
    assert world.job(name).attempts == int(attempts)


@then(parsers.parse('the job for "{name}" has the error "{message}"'))
def _(world, name, message):
    assert message in world.job(name).error


@then(parsers.parse('the job for "{name}" reports {count:d} speakers'))
def _(world, name, count):
    assert world.job(name).num_speakers == count


@then(parsers.parse('the job for "{name}" reports the language "{language}"'))
def _(world, name, language):
    assert world.job(name).language == language
    assert world.recognizer.languages_requested[-1] in (None, language)


@then(parsers.parse("the speaker model was told to expect {count:d} speakers"))
def _(world, count):
    assert world.diarizer.options_seen[-1].num_speakers == count


@then("the inbox is empty")
def _(world):
    assert world.folder("inbox") == []


@then(parsers.parse('"{name}" is still in the inbox'))
def _(world, name):
    assert name in world.folder("inbox")


@then(parsers.re(r'the (?P<which>\w+) folder contains "(?P<name>[^"]+)"'))
def _(world, which, name):
    assert name in world.folder(which), world.folder(which)


@then(parsers.re(r'the (?P<which>\w+) folder contains only "(?P<name>[^"]+)"'))
def _(world, which, name):
    assert world.folder(which) == [name]


@then(parsers.re(r'the (?P<which>\w+) folder contains "(?P<name>[^"]+)" explaining "(?P<reason>[^"]+)"'))
def _(world, which, name, reason):
    assert reason in (world.data_dir / which / name).read_text()


@then(parsers.parse("the {which} folder is empty"))
def _(world, which):
    assert world.folder(which) == []


@then("no staged files remain")
def _(world):
    assert world.folder("staging") == []
    assert not any((world.data_dir / ".work").iterdir())


@then(parsers.parse('the output file "{name}" contains:'))
def _(world, name, docstring):
    text = (world.data_dir / "output" / name).read_text(encoding="utf-8")
    assert docstring in text, text


@then(parsers.parse('the output file "{name}" does not contain "{text}"'))
def _(world, name, text):
    assert text not in (world.data_dir / "output" / name).read_text(encoding="utf-8")


@then(parsers.parse("{count:d} transcripts exist in the output folder"))
def _(world, count):
    assert len(world.folder("output")) == count


@then(parsers.parse("{count:d} originals exist in the archive folder"))
def _(world, count):
    assert len(world.folder("archive")) == count


@then(parsers.parse('the response starts with "{start}"'))
def _(world, start):
    assert world.refusal is None, world.refusal
    assert world.response.startswith(start)


@then("the request is refused because the transcript is not ready")
def _(world):
    assert isinstance(world.refusal, TranscriptNotReady)


@then("the request is refused because the original file is gone")
def _(world):
    assert isinstance(world.refusal, OriginalMissing)


@then("the request is refused because the job is done")
def _(world):
    assert isinstance(world.refusal, InvalidTransition)


@then(parsers.parse('the worker reports the error "{message}"'))
def _(world, message):
    (state,) = world.registry.list()
    assert state.status == ERROR and message in state.message


@then("the worker reports that it is ready")
def _(world):
    (state,) = world.registry.list()
    assert state.status == READY and state.message is None


@then(parsers.parse("the health report counts {done:d} done and {queued:d} queued job"))
def _(world, done, queued):
    counts = world.service.health().jobs
    assert (counts["done"], counts["queued"]) == (done, queued)


@then(parsers.re(r"the health report lists (?P<count>\d+) worker that is (?P<negation>not )?alive"))
def _(world, count, negation):
    workers = world.service.health().workers
    assert len(workers) == int(count)
    assert all(w.alive is (negation is None) for w in workers)
