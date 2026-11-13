"""Process: load the speech models and work through the queue."""

from __future__ import annotations

import contextlib
import logging
import signal
import threading

from scribe import bootstrap
from scribe.entrypoints import logs

log = logging.getLogger("scribe.worker")
RELOAD_SECONDS = 60  # between attempts to load models that would not load
RETRY_SECONDS = 5  # after an unexpected error, e.g. the database restarting


def main() -> None:
    logs.configure()
    settings = bootstrap.settings()
    worker = bootstrap.worker()
    stop = threading.Event()

    def on_signal(*_) -> None:
        log.info("stopping; the current job goes back to the queue")
        worker.request_stop()
        stop.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, on_signal)

    def keep_alive() -> None:
        # A separate thread, so leases are renewed even while the main thread
        # is deep inside a model call.
        while not stop.wait(settings.heartbeat_seconds):
            try:
                worker.keep_alive()
            except Exception as exc:
                log.warning("heartbeat failed: %s", exc)

    threading.Thread(target=keep_alive, name="keep-alive", daemon=True).start()
    log.info(
        "worker starting: device=%s engine=%s whisper=%s diarize=%s",
        settings.device,
        settings.speech_engine,
        settings.whisper_model,
        f"on {settings.diarization_device}" if settings.diarize else "off",
    )
    while not stop.is_set():
        try:
            if not worker.tick():
                stop.wait(settings.poll_seconds if worker.ready else RELOAD_SECONDS)
        except Exception:
            log.exception("unexpected error; trying again in %d s", RETRY_SECONDS)
            stop.wait(RETRY_SECONDS)
    with contextlib.suppress(Exception):  # the database may already be gone
        worker.sign_off()
    log.info("stopped")


if __name__ == "__main__":
    main()
