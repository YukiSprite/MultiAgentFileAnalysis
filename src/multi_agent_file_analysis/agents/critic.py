"""Critic agent boundary.

Critic is the evidence and safety reviewer. Its job is to make the system less
eager, not more verbose: unsupported claims should be rejected or sent back for
more evidence.
"""

from multi_agent_file_analysis.agents.base import AgentContext, AgentResult
from multi_agent_file_analysis.core import AgentRole
from multi_agent_file_analysis.graph.state import DiagnosisState
from multi_agent_file_analysis.llm import LLMClient


class CriticAgent:
    """Reviews diagnosis drafts against collected evidence.

    Future implementation should compare each draft claim and recommended action
    against DiagnosisState.evidence and runtime_context, then write CriticReport.
    """

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
