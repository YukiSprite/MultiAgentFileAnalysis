"""Graph workflow boundary."""

from typing import TYPE_CHECKING

from multi_agent_file_analysis.agents import AgentContext, CriticAgent, ExplorerAgent, ReasonerAgent
from multi_agent_file_analysis.audit import AuditRecorder
from multi_agent_file_analysis.graph.plan import WorkflowPlan
from multi_agent_file_analysis.graph.state import DiagnosisState

if TYPE_CHECKING:
    from multi_agent_file_analysis.hitl import HITLSession


class DiagnosisWorkflow:
    """Coordinates agent execution and HITL suspension/resume."""

    def __init__(
        self,
        explorer: ExplorerAgent,
        reasoner: ReasonerAgent,
        critic: CriticAgent,
        hitl_session: "HITLSession | None" = None,
        audit_recorder: AuditRecorder | None = None,
    ) -> None:
        self._explorer = explorer
        self._reasoner = reasoner
        self._critic = critic
        self._hitl_session = hitl_session
        self._audit_recorder = audit_recorder

    def plan(self) -> WorkflowPlan:
        """Return the static workflow plan."""
        raise NotImplementedError

    def run(
        self,
        state: DiagnosisState,
        context: AgentContext | None = None,
    ) -> DiagnosisState:
        """Run the diagnosis workflow until it finishes or needs user input."""
        raise NotImplementedError

    def resume(
        self,
        state: DiagnosisState,
        user_input: str,
        context: AgentContext | None = None,
    ) -> DiagnosisState:
        """Resume a suspended workflow with user-provided context."""
        raise NotImplementedError
