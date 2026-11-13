"""Process: watch the inbox and keep the queue healthy.

Polls rather than using file-system events, because those do not cross
Docker bind mounts reliably (Windows, macOS, network shares)."""

from __future__ import annotations

import logging
import signal
import threading
import time

from scribe import bootstrap
from scribe.entrypoints import logs

log = logging.getLogger("scribe.watcher")
HOUSEKEEPING_SECONDS = 15
RETRY_SECONDS = 5


def main() -> None:
    logs.configure()
    settings = bootstrap.settings()
    watcher, housekeeper = bootstrap.inbox_watcher(), bootstrap.housekeeper()
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())

    housekeeper.recover_orphans()
    log.info("watching %s", settings.data_dir / "inbox")
    next_housekeeping = 0.0
    while not stop.is_set():
        try:
            watcher.scan()
            if time.monotonic() >= next_housekeeping:
                housekeeper.reap()
                next_housekeeping = time.monotonic() + HOUSEKEEPING_SECONDS
        except Exception:
            log.exception("scan failed; trying again in %d s", RETRY_SECONDS)
            stop.wait(RETRY_SECONDS)
        stop.wait(settings.scan_seconds)
    log.info("stopped")


if __name__ == "__main__":
    main()
