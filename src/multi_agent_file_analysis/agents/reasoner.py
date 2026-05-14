"""Reasoner agent boundary."""

from multi_agent_file_analysis.agents.base import AgentContext, AgentResult
from multi_agent_file_analysis.core import AgentRole
from multi_agent_file_analysis.graph.state import DiagnosisState
from multi_agent_file_analysis.llm import LLMClient


class ReasonerAgent:
    """Builds a diagnosis from user context and collected evidence."""

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
