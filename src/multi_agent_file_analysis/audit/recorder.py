"""Audit sink boundary."""

from typing import Protocol

from .events import AuditEvent


class AuditRecorder(Protocol):
    """Receives structured workflow events."""

    def record(self, event: AuditEvent) -> None:
        """Persist or forward one audit event."""
        ...
