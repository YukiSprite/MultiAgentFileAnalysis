"""Structured events emitted by the workflow."""

from dataclasses import dataclass, field
from enum import StrEnum


class AuditEventType(StrEnum):
    """Event categories used for traceability."""

    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_STAGE_CHANGED = "workflow_stage_changed"
    TOOL_CALLED = "tool_called"
    AGENT_STARTED = "agent_started"
    AGENT_FINISHED = "agent_finished"
    HUMAN_INPUT_REQUESTED = "human_input_requested"
    HUMAN_INPUT_RECEIVED = "human_input_received"
    WORKFLOW_FINISHED = "workflow_finished"


@dataclass(slots=True)
class ToolAuditPayload:
    """Audit payload for a virtual tool call."""

    tool_name: str
    path: str
    query: str | None = None
    result_summary: str | None = None


@dataclass(slots=True)
class AuditEvent:
    """A traceable event emitted by agents, VFS, or workflow nodes."""

    event_type: AuditEventType
    run_id: str
    message: str
    payload: dict[str, str] = field(default_factory=dict)
