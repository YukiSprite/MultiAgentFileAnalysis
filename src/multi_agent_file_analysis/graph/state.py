"""Shared state passed between graph nodes.

DiagnosisState is the workflow's single source of truth. Agents and nodes should
communicate by reading and updating this state instead of keeping hidden global
state or passing ad-hoc dictionaries between layers.
"""

from dataclasses import dataclass, field
from typing import Any

from multi_agent_file_analysis.core import (
    AgentRole,
    EvidenceKind,
    ReviewDecision,
    ToolName,
    TrustLevel,
    WorkflowStage,
    WorkflowStatus,
)


@dataclass(slots=True)
class RoleUsage:
    """Token and call accounting for one agent role."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0
    failures: int = 0
    calls_without_usage: int = 0

    def record_call(self) -> None:
        """Count one model call that reported usage."""
        self.calls += 1

    def record_missing_usage(self) -> None:
        """Count one successful model call whose provider omitted usage."""
        self.calls += 1
        self.calls_without_usage += 1

    def record_failure(self) -> None:
        """Count one model call that raised."""
        self.calls += 1
        self.failures += 1

    def add_tokens(self, prompt: int, completion: int, total: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += total

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "calls": self.calls,
            "failures": self.failures,
            "calls_without_usage": self.calls_without_usage,
        }


@dataclass(slots=True)
class StageTiming:
    """Accumulated wall-clock cost of one workflow stage.

    Repeated entries into the same stage add up and bump ``entries`` so callers
    can tell one long pass from many short retries.
    """

    seconds: float = 0.0
    entries: int = 0

    def add(self, seconds: float) -> None:
        self.seconds += max(0.0, seconds)
        self.entries += 1

    def to_dict(self) -> dict[str, float | int]:
        return {"seconds": self.seconds, "entries": self.entries}


@dataclass(slots=True)
class RunMetrics:
    """Usage and latency ledger for one diagnosis run.

    Keys are the string values of ``AgentRole`` and ``WorkflowStage``. Dicts are
    used instead of fixed fields so a new role or stage does not require a model
    change or a migration.
    """

    roles: dict[str, RoleUsage] = field(default_factory=dict)
    stages: dict[str, StageTiming] = field(default_factory=dict)
    started_at: float | None = None
    ended_at: float | None = None

    def role(self, role: AgentRole | str) -> RoleUsage:
        key = str(role)
        usage = self.roles.get(key)
        if usage is None:
            usage = self.roles[key] = RoleUsage()
        return usage

    def stage(self, stage: WorkflowStage | str) -> StageTiming:
        key = str(stage)
        timing = self.stages.get(key)
        if timing is None:
            timing = self.stages[key] = StageTiming()
        return timing

    @property
    def total_tokens(self) -> int:
        return sum(usage.total_tokens for usage in self.roles.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "roles": {
                key: usage.to_dict() for key, usage in sorted(self.roles.items())
            },
            "stages": {
                key: timing.to_dict()
                for key, timing in sorted(self.stages.items())
            },
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "total_tokens": self.total_tokens,
        }


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
    supports_obligations: list[str] = field(default_factory=list)
    truncated: bool = False
    verified: bool = False
    digest_verified: bool = True

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
class RetrievalPlan:
    """Model-authored evidence contract for one Explorer attempt.

    The plan is deliberately kept separate from evidence: it says what must be
    proved and which searches should be attempted, but none of its text is a
    source-backed fact. Keeping it in shared state makes failed runs auditable.
    """

    evidence_obligations: list[str] = field(default_factory=list)
    exact_literals: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)


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
    trust: TrustLevel = TrustLevel.USER_ASSERTED


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
    rejected_command: str | None = None
    attempt: int = 1


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
    - accounting: metrics;
    - suspension/finalization: human_request, final_answer, partial_answer, errors.
    """

    user_query: str
    run_id: str = ""
    status: WorkflowStatus = WorkflowStatus.CREATED
    stage: WorkflowStage = WorkflowStage.INTAKE
    metrics: RunMetrics = field(default_factory=RunMetrics)
    user_context: list[str] = field(default_factory=list)
    runtime_context: list[RuntimeContextItem] = field(default_factory=list)
    exploration_log: list[ExplorationStep] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    retrieval_plan: RetrievalPlan | None = None
    uncovered_evidence_obligations: list[str] = field(default_factory=list)
    diagnosis_draft: DiagnosisDraft | None = None
    critic_notes: list[str] = field(default_factory=list)
    critic_report: CriticReport | None = None
    human_request: HumanRequest | None = None
    final_answer: str | None = None
    partial_answer: str | None = None
    errors: list[str] = field(default_factory=list)
    workflow_iterations: int = 0
    exploration_attempts: int = 0
    reasoning_attempts: int = 0
    review_attempts: int = 0
    resume_count: int = 0
    next_stage: WorkflowStage | None = None
    last_transition_reason: str | None = None
