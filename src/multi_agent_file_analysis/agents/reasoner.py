"""Reasoner agent boundary.

Reasoner is the diagnostic brain. It consumes user context and Explorer's
evidence, then writes a structured draft or asks for human-provided runtime
data.
"""

from multi_agent_file_analysis.agents.base import AgentContext, AgentResult
from multi_agent_file_analysis.core import AgentRole
from multi_agent_file_analysis.graph.state import DiagnosisState
from multi_agent_file_analysis.llm import LLMClient


class ReasonerAgent:
    """Builds a diagnosis from user context and collected evidence.

    Future implementation may use LLMClient to produce DiagnosisDraft, but it
    should not call VFS tools. If evidence is insufficient because runtime state
    is missing, it should create HumanRequest instead of guessing.
    """

    role = AgentRole.REASONER

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm_client = llm_client

    def run(
        self,
        state: DiagnosisState,
        context: AgentContext | None = None,
    ) -> AgentResult:
        """Produce a diagnosis draft or request more user-provided context."""
        raise NotImplementedError
