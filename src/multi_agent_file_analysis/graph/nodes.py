"""Workflow node boundaries."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from multi_agent_file_analysis.agents import AgentContext, CriticAgent, ExplorerAgent, ReasonerAgent
from multi_agent_file_analysis.core import WorkflowStage, WorkflowStatus
from multi_agent_file_analysis.graph.state import DiagnosisState

if TYPE_CHECKING:
    from multi_agent_file_analysis.hitl import HITLSession


@dataclass(slots=True)
class NodeResult:
    """Result emitted by one graph node."""

    status: WorkflowStatus
    current_stage: WorkflowStage
    next_stage: WorkflowStage | None = None
    message: str | None = None


class WorkflowNode(Protocol):
    """Callable boundary for graph nodes."""

    stage: WorkflowStage

    def run(self, state: DiagnosisState, context: AgentContext | None = None) -> NodeResult:
        """Execute one graph node."""
        ...


class ExplorerNode:
    """Graph node wrapping ExplorerAgent."""

    stage = WorkflowStage.EXPLORE

    def __init__(self, agent: ExplorerAgent) -> None:
        self._agent = agent

    def run(self, state: DiagnosisState, context: AgentContext | None = None) -> NodeResult:
        """Run Explorer and select the next workflow stage."""
        raise NotImplementedError


class ReasonerNode:
    """Graph node wrapping ReasonerAgent."""

    stage = WorkflowStage.REASON

    def __init__(self, agent: ReasonerAgent) -> None:
        self._agent = agent

    def run(self, state: DiagnosisState, context: AgentContext | None = None) -> NodeResult:
        """Run Reasoner and select critique or HITL."""
        raise NotImplementedError


class CriticNode:
    """Graph node wrapping CriticAgent."""

    stage = WorkflowStage.CRITIQUE

    def __init__(self, agent: CriticAgent) -> None:
        self._agent = agent

    def run(self, state: DiagnosisState, context: AgentContext | None = None) -> NodeResult:
        """Run Critic and select finalize, revise, or re-explore."""
        raise NotImplementedError


class HITLNode:
    """Graph node wrapping human-in-the-loop suspension."""

    stage = WorkflowStage.REQUEST_HUMAN_INPUT

    def __init__(self, session: "HITLSession") -> None:
        self._session = session

    def run(self, state: DiagnosisState, context: AgentContext | None = None) -> NodeResult:
        """Suspend the workflow and expose a human request."""
        raise NotImplementedError
