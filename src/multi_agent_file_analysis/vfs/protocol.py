"""Virtual file-system tool interface."""

from dataclasses import dataclass

from multi_agent_file_analysis.core import ToolName


@dataclass(slots=True)
class DirectoryEntry:
    """A visible item returned by v_ls."""

    path: str
    kind: str
    description: str
    title: str | None = None
    tags: list[str] | None = None


@dataclass(slots=True)
class DirectoryListing:
    """Structured result for v_ls."""

    path: str
    entries: list[DirectoryEntry]
    truncated: bool = False


@dataclass(slots=True)
class FileReadResult:
    """Structured result for v_cat."""

    path: str
    content: str
    truncated: bool
    total_chars: int | None = None
    source_path: str | None = None


@dataclass(slots=True)
class GrepHit:
    """A keyword hit returned by v_grep."""

    path: str
    line_number: int
    line: str
    context: list[str]


@dataclass(slots=True)
class GrepResult:
    """Structured result for v_grep."""

    path: str
    pattern: str
    hits: list[GrepHit]
    truncated: bool = False


@dataclass(slots=True)
class VfsToolCall:
    """A single virtual tool invocation request."""

    tool_name: ToolName
    path: str
    pattern: str | None = None


class VirtualFileSystem:
    """Controlled browsing protocol for agents."""

    def v_ls(self, path: str) -> DirectoryListing:
        """List one virtual directory level."""
        raise NotImplementedError

    def v_cat(self, path: str) -> FileReadResult:
        """Read one virtual file with truncation handled by the implementation."""
        raise NotImplementedError

    def v_grep(self, path: str, pattern: str) -> GrepResult:
        """Search exact text in a virtual path scope."""
        raise NotImplementedError
