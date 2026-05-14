"""Shared state passed between graph nodes."""

from dataclasses import dataclass, field

from multi_agent_file_analysis.core import (
    EvidenceKind,
    ReviewDecision,
    ToolName,
    WorkflowStage,
    WorkflowStatus,
)


@dataclass(slots=True)
class EvidenceItem:
    """Evidence extracted from the knowledge base."""

    source_path: str
    summary: str
    kind: EvidenceKind = EvidenceKind.RULE
    quote: str | None = None
    line_start: int | None = None
    line_end: int | None = None


@dataclass(slots=True)
class ExplorationStep:
    """One trace entry for Explorer tool usage."""

    tool_name: ToolName
    path: str
    query: str | None = None
    result_summary: str | None = None


@dataclass(slots=True)
class RuntimeContextItem:
    """User-provided runtime context such as logs or config snippets."""

    label: str
    content: str
    source_hint: str | None = None


@dataclass(slots=True)
class DiagnosisDraft:
    """Reasoner's provisional answer before critic review."""

    summary: str
    root_cause: str | None = None
    recommended_actions: list[str] = field(default_factory=list)
    cited_evidence: list[str] = field(default_factory=list)


@dataclass(slots=True)
class HumanRequest:
    """A request for user-provided runtime information."""

    prompt: str
    expected_input: str
    reason: str | None = None
    suggested_command: str | None = None


@dataclass(slots=True)
class CriticReport:
    """Critic's structured review of a diagnosis draft."""

    decision: ReviewDecision
    notes: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DiagnosisState:
    """State shared by Explorer, Reasoner, Critic, and HITL nodes."""

    user_query: str
    run_id: str = ""
    status: WorkflowStatus = WorkflowStatus.CREATED
    stage: WorkflowStage = WorkflowStage.INTAKE
    user_context: list[str] = field(default_factory=list)
    runtime_context: list[RuntimeContextItem] = field(default_factory=list)
    exploration_log: list[ExplorationStep] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    diagnosis_draft: DiagnosisDraft | None = None
    critic_notes: list[str] = field(default_factory=list)
    critic_report: CriticReport | None = None
    human_request: HumanRequest | None = None
    final_answer: str | None = None
    errors: list[str] = field(default_factory=list)
