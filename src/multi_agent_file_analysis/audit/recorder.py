"""Audit sink implementations."""

import json
from pathlib import Path
from typing import Protocol

from .events import AuditEvent


class AuditRecorder(Protocol):
    """Receives structured workflow events."""

    def record(self, event: AuditEvent) -> None:
        ...


class MemoryAuditRecorder:
    """Records audit events to an in-memory list for tests and debugging."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)


class JsonlAuditRecorder:
    """Records audit events as JSONL lines to a file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def record(self, event: AuditEvent) -> None:
        payload: dict = {
            "event_type": str(event.event_type),
            "run_id": event.run_id,
            "message": event.message,
        }
        payload.update(event.payload)
        line = json.dumps(payload, ensure_ascii=False)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
