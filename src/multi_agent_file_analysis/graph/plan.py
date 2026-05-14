"""Static graph plan models."""

from dataclasses import dataclass, field

from multi_agent_file_analysis.core import WorkflowStage


@dataclass(slots=True)
class WorkflowEdge:
    """A possible transition between two workflow stages."""

    source: WorkflowStage
    target: WorkflowStage
    condition: str | None = None


@dataclass(slots=True)
class WorkflowPlan:
    """Declarative description of the diagnosis workflow."""

    stages: list[WorkflowStage] = field(default_factory=list)
    edges: list[WorkflowEdge] = field(default_factory=list)
