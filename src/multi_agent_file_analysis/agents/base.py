"""Common agent contracts."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from multi_agent_file_analysis.core import AgentResultStatus, AgentRole, WorkflowStage

if TYPE_CHECKING:
    from multi_agent_file_analysis.audit import AuditRecorder
    from multi_agent_file_analysis.graph.state import DiagnosisState
    from multi_agent_file_analysis.llm import LLMClient


@dataclass(slots=True)
class AgentContext:
    """Runtime dependencies shared by agent steps."""

    run_id: str
    llm_client: "LLMClient | None" = None
    audit_recorder: "AuditRecorder | None" = None
    metadata: dict[str, str] | None = None


@dataclass(slots=True)
class AgentResult:
    """Generic result emitted by an agent step."""

    role: AgentRole
    status: AgentResultStatus
    message: str
    next_stage: WorkflowStage | None = None


class Agent(Protocol):
    """Common callable contract for all agents."""

    role: AgentRole

    def run(
        self,
        state: "DiagnosisState",
        context: AgentContext | None = None,
    ) -> AgentResult:
        """Run one agent step against the shared diagnosis state."""
        ...
