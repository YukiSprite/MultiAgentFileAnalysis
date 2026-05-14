"""Virtual file-system tool interface."""

from dataclasses import dataclass


@dataclass(slots=True)
class DirectoryEntry:
    """A visible item returned by v_ls."""

    path: str
    kind: str
    description: str


@dataclass(slots=True)
class GrepHit:
    """A keyword hit returned by v_grep."""

    path: str
    line_number: int
    line: str
    context: list[str]


class VirtualFileSystem:
    """Controlled browsing protocol for agents."""

    def v_ls(self, path: str) -> list[DirectoryEntry]:
        """List one virtual directory level."""
        raise NotImplementedError

    def v_cat(self, path: str) -> str:
        """Read one virtual file with truncation handled by the implementation."""
        raise NotImplementedError

    def v_grep(self, path: str, pattern: str) -> list[GrepHit]:
        """Search exact text in a virtual path scope."""
        raise NotImplementedError
