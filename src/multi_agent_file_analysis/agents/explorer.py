"""Explorer agent boundary."""

from multi_agent_file_analysis.agents.base import AgentContext, AgentResult
from multi_agent_file_analysis.core import AgentRole
from multi_agent_file_analysis.graph.state import DiagnosisState
from multi_agent_file_analysis.vfs import VirtualFileSystem


class ExplorerAgent:
    """Collects rules and evidence from the virtual file system."""

    role = AgentRole.EXPLORER

    def __init__(self, vfs: VirtualFileSystem) -> None:
        self._vfs = vfs

    def run(
        self,
        state: DiagnosisState,
        context: AgentContext | None = None,
    ) -> AgentResult:
        """Explore the knowledge base and update diagnosis evidence."""
        raise NotImplementedError
