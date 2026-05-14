"""Public QA service boundary."""

from dataclasses import dataclass, field

from multi_agent_file_analysis.graph import DiagnosisState, DiagnosisWorkflow


@dataclass(slots=True)
class QARequest:
    """User-facing request for one QA or diagnosis run."""

    query: str
    context: list[str] = field(default_factory=list)
    run_id: str | None = None


@dataclass(slots=True)
class QAResponse:
    """User-facing response from the QA service."""

    state: DiagnosisState
    answer: str | None = None
    needs_human_input: bool = False


class QAService:
    """Application facade used by CLI, API, or tests."""

    def __init__(self, workflow: DiagnosisWorkflow) -> None:
        self._workflow = workflow

    def ask(self, request: QARequest) -> QAResponse:
        """Start a new QA workflow."""
        raise NotImplementedError

    def resume(self, state: DiagnosisState, user_input: str) -> QAResponse:
        """Resume a QA workflow that is waiting for human input."""
        raise NotImplementedError
