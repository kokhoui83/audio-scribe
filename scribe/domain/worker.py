"""What a worker reports about itself."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

LOADING = "loading"
READY = "ready"
ERROR = "error"


@dataclass(frozen=True)
class WorkerState:
    id: str
    status: str  # LOADING, READY or ERROR
    heartbeat_at: datetime
    message: str | None = None
    device: str = ""
    speech_model: str = ""
    speaker_model: str = ""
