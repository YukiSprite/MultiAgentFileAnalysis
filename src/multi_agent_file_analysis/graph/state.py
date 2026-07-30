"""Shared state passed between graph nodes.

DiagnosisState is the workflow's single source of truth. Agents and nodes should
communicate by reading and updating this state instead of keeping hidden global
state or passing ad-hoc dictionaries between layers.
"""

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
    """Evidence extracted from the knowledge base.

    Evidence is the bridge between retrieval and reasoning. The final answer
    should only make claims that can be traced back to one or more EvidenceItem
    objects.
    """

    source_path: str
    summary: str
    kind: EvidenceKind = EvidenceKind.RULE
    quote: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    source_version: str | None = None
    section: str | None = None
    retrieval_query: str | None = None
    content_hash: str | None = None
    applicability_conditions: list[str] = field(default_factory=list)
    truncated: bool = False
    verified: bool = False

    @property
    def citation_key(self) -> str:
        """Stable citation key used by deterministic validation."""
        if self.line_start is None:
            return self.source_path
        if self.line_end and self.line_end != self.line_start:
            return f"{self.source_path}:L{self.line_start}-L{self.line_end}"
        return f"{self.source_path}:L{self.line_start}"


@dataclass(slots=True)
class ExplorationStep:
    """One trace entry for Explorer tool usage.

    This is a human-readable workflow trace. AuditEvent is the structured sink;
    ExplorationStep is kept in state so Reasoner, Critic, and debuggers can see
    how evidence was collected.
    """

    tool_name: ToolName
    path: str
    query: str | None = None
    result_summary: str | None = None


@dataclass(slots=True)
class RuntimeContextItem:
    """User-provided runtime context such as logs or config snippets.

    Runtime context is intentionally separated from knowledge-base evidence:
    it describes the user's live environment, while EvidenceItem describes
    static rules found in documentation.
    """

    label: str
    content: str
    source_hint: str | None = None
    request_id: str | None = None
    verified: bool = False


@dataclass(slots=True)
class DiagnosisDraft:
    """Reasoner's provisional answer before critic review.

    This object is not safe to show as final output until CriticAgent approves
    it. Keeping it structured makes it easier for Critic to check every action
    and every cited source.
    """

    summary: str
    root_cause: str | None = None
    recommended_actions: list[str] = field(default_factory=list)
    cited_evidence: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    confidence: str | None = None


@dataclass(slots=True)
class HumanRequest:
    """A request for user-provided runtime information.

    The system should use this when it needs facts from a real environment.
    suggested_command should be read-only and user-run; the model should never
    execute it against the user's machine or server by itself.
    """

    prompt: str
    expected_input: str
    reason: str | None = None
    suggested_command: str | None = None
    request_id: str = ""
    command_approved: bool = False
    command_warning: str | None = None


@dataclass(slots=True)
class CriticReport:
    """Critic's structured review of a diagnosis draft.

    A report with APPROVED means the draft can be finalized. Other decisions
    should route the workflow back to evidence collection, revision, or failure
    depending on the workflow policy.
    """

    decision: ReviewDecision
    notes: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DiagnosisState:
    """State shared by Explorer, Reasoner, Critic, and HITL nodes.

    Field groups:
    - identity and lifecycle: run_id, status, stage;
    - user inputs: user_query, user_context, runtime_context;
    - retrieval trace: exploration_log, evidence;
    - reasoning and review: diagnosis_draft, critic_report, critic_notes;
    - suspension/finalization: human_request, final_answer, errors.
    """

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
    workflow_iterations: int = 0
    exploration_attempts: int = 0
    reasoning_attempts: int = 0
    review_attempts: int = 0
    resume_count: int = 0
    next_stage: WorkflowStage | None = None
    last_transition_reason: str | None = None
