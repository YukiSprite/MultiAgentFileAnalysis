"""Common agent contracts."""

from dataclasses import dataclass


@dataclass(slots=True)
class AgentResult:
    """Generic result emitted by an agent step."""

    status: str
    message: str
