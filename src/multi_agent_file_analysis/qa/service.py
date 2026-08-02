"""Public QA service facade."""

import uuid
from dataclasses import dataclass, field

from multi_agent_file_analysis.graph.state import DiagnosisState, WorkflowStatus
from multi_agent_file_analysis.core.errors import WorkflowError

from ..graph.workflow import DiagnosisWorkflow


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
    is_partial: bool = False


class QAService:
    """Application facade used by CLI, API, or tests."""

    def __init__(self, workflow: DiagnosisWorkflow) -> None:
        self._workflow = workflow
        # Track sessions for resume
        self._sessions: dict[str, DiagnosisState] = {}

    def ask(self, request: QARequest) -> QAResponse:
        query = request.query.strip()
        if not query:
            raise WorkflowError("Question must not be empty")
        run_id = request.run_id or uuid.uuid4().hex[:12]
        if run_id in self._sessions:
            raise WorkflowError(
                f"Run {run_id} is waiting for input; resume it instead"
            )
        state = DiagnosisState(
            user_query=query,
            run_id=run_id,
            user_context=request.context,
        )

        state = self._workflow.run(state)

        if state.status == WorkflowStatus.WAITING_FOR_HUMAN:
            self._sessions[run_id] = state
            return QAResponse(
                state=state,
                answer=state.partial_answer,
                needs_human_input=True,
                is_partial=state.partial_answer is not None,
            )

        self._sessions.pop(run_id, None)
        return QAResponse(
            state=state,
            answer=state.final_answer or state.partial_answer,
            needs_human_input=False,
            is_partial=state.final_answer is None and state.partial_answer is not None,
        )

    def resume(self, state: DiagnosisState, user_input: str) -> QAResponse:
        state = self._workflow.resume(state, user_input)

        if state.status == WorkflowStatus.WAITING_FOR_HUMAN:
            self._sessions[state.run_id] = state
            return QAResponse(
                state=state,
                answer=state.partial_answer,
                needs_human_input=True,
                is_partial=state.partial_answer is not None,
            )

        self._sessions.pop(state.run_id, None)
        return QAResponse(
            state=state,
            answer=state.final_answer or state.partial_answer,
            needs_human_input=False,
            is_partial=state.final_answer is None and state.partial_answer is not None,
        )

    def resume_by_id(self, run_id: str, user_input: str) -> QAResponse:
        state = self._sessions.get(run_id)
        if state is None:
            raise WorkflowError(f"No suspended workflow found for run {run_id}")
        return self.resume(state, user_input)

    def get_session(self, run_id: str) -> DiagnosisState | None:
        return self._sessions.get(run_id)
