"""Shared state passed between graph nodes."""

from dataclasses import dataclass, field


@dataclass(slots=True)
class EvidenceItem:
    """Evidence extracted from the knowledge base."""

    source_path: str
    summary: str
    quote: str | None = None


@dataclass(slots=True)
class HumanRequest:
    """A request for user-provided runtime information."""

    prompt: str
    expected_input: str


@dataclass(slots=True)
class DiagnosisState:
    """State shared by Explorer, Reasoner, Critic, and HITL nodes."""

    user_query: str
    user_context: list[str] = field(default_factory=list)
    exploration_log: list[str] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    diagnosis_draft: str | None = None
    critic_notes: list[str] = field(default_factory=list)
    human_request: HumanRequest | None = None
    final_answer: str | None = None
