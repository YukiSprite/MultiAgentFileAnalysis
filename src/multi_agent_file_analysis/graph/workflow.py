"""Graph workflow boundary.

DiagnosisWorkflow owns the control flow. It decides which stage runs next, when
to suspend for human input, and when a final answer is ready. The concrete
retrieval, reasoning, and review work remains inside agents or HITL services.
"""

from typing import TYPE_CHECKING

from multi_agent_file_analysis.agents import AgentContext, CriticAgent, ExplorerAgent, ReasonerAgent
from multi_agent_file_analysis.audit import AuditRecorder
from multi_agent_file_analysis.graph.plan import WorkflowPlan
from multi_agent_file_analysis.graph.state import DiagnosisState

if TYPE_CHECKING:
    from multi_agent_file_analysis.hitl import HITLSession


class DiagnosisWorkflow:
    """Coordinates agent execution and HITL suspension/resume.

    The intended graph is:
    Explorer -> Reasoner -> Critic -> Finalize
                      |
                      v
                    HITL -> Reasoner

    Critic may also route back to Explorer when evidence is missing. Concrete
    transition policy belongs in this class, while agent-specific behavior
    belongs in the corresponding Agent class.
    """

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
        """Return the static workflow plan.

        The plan is useful for documentation, visualization, and tests. It
        should describe possible transitions without executing them.
        """
        raise NotImplementedError

    def run(
        self,
        state: DiagnosisState,
        context: AgentContext | None = None,
    ) -> DiagnosisState:
        """Run the diagnosis workflow until it finishes or needs user input.

        A future implementation should update state.status and state.stage at
        every transition, emit audit events, and stop cleanly when HITL is
        required.
        """
        raise NotImplementedError

    def resume(
        self,
        state: DiagnosisState,
        user_input: str,
        context: AgentContext | None = None,
    ) -> DiagnosisState:
        """Resume a suspended workflow with user-provided context.

        Resume should only be valid when state.status is WAITING_FOR_HUMAN.
        It should attach the user input to runtime_context, clear the pending
        human_request, and continue from the stage selected by workflow policy.
        """
        raise NotImplementedError
