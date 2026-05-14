"""Common agent contracts.

Agents are intentionally small role objects. They receive DiagnosisState and
AgentContext, then return AgentResult. They should not own workflow routing
policy beyond suggesting a next_stage in the result.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from multi_agent_file_analysis.core import AgentResultStatus, AgentRole, WorkflowStage

if TYPE_CHECKING:
    from multi_agent_file_analysis.audit import AuditRecorder
    from multi_agent_file_analysis.graph.state import DiagnosisState
    from multi_agent_file_analysis.llm import LLMClient


@dataclass(slots=True)
class AgentContext:
    """Runtime dependencies shared by agent steps.

    AgentContext keeps infrastructure out of DiagnosisState. The state should
    remain serializable domain data; clients, audit sinks, and runtime metadata
    belong here.
    """

    run_id: str
    llm_client: "LLMClient | None" = None
    audit_recorder: "AuditRecorder | None" = None
    metadata: dict[str, str] | None = None


@dataclass(slots=True)
class AgentResult:
    """Generic result emitted by an agent step.

    The message should be concise and operational, suitable for audit logs and
    debugging. Long model outputs should be stored in structured state fields
    such as diagnosis_draft or critic_report.
    """

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
