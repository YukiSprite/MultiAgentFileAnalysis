"""Critic agent boundary."""

from multi_agent_file_analysis.agents.base import AgentContext, AgentResult
from multi_agent_file_analysis.core import AgentRole
from multi_agent_file_analysis.graph.state import DiagnosisState
from multi_agent_file_analysis.llm import LLMClient


class CriticAgent:
    """Reviews diagnosis drafts against collected evidence."""

    role = AgentRole.CRITIC

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm_client = llm_client

    def run(
        self,
        state: DiagnosisState,
        context: AgentContext | None = None,
    ) -> AgentResult:
        """Approve the draft or request another pass."""
        raise NotImplementedError
