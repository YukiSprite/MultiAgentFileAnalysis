"""Common agent contracts.

Agents are intentionally small role objects. They receive DiagnosisState and
AgentContext, then return AgentResult. They should not own workflow routing
policy beyond suggesting a next_stage in the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from multi_agent_file_analysis.core import AgentResultStatus, AgentRole, WorkflowStage

if TYPE_CHECKING:
    from multi_agent_file_analysis.audit import AuditRecorder
    from multi_agent_file_analysis.graph.state import DiagnosisState
    from multi_agent_file_analysis.llm import LLMClient, LLMRequest, LLMResponse


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


def call_llm(
    state: "DiagnosisState",
    role: AgentRole,
    llm: "LLMClient",
    request: "LLMRequest",
) -> "LLMResponse":
    """Call the model and account the call on the run's metrics ledger.

    Every agent goes through here so usage, missing-usage and failure counts are
    recorded once per call instead of being re-implemented per agent. Exceptions
    are re-raised unchanged: accounting must never alter fail-closed behaviour.
    """
    usage = state.metrics.role(role)
    try:
        response = llm.complete(request)
    except Exception:
        usage.record_failure()
        raise
    if response.usage is None:
        usage.record_missing_usage()
    else:
        usage.record_call()
        usage.add_tokens(
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
            response.usage.total_tokens,
        )
    return response
