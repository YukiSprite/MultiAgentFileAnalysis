"""Virtual file-system protocol exposed to retrieval agents."""

from .policy import VfsAccessPolicy
from .protocol import (
    DirectoryEntry,
    DirectoryListing,
    EvidenceVerification,
    FileReadResult,
    FindEntry,
    FindResult,
    GrepHit,
    GrepResult,
    SearchHit,
    SearchResult,
    StatResult,
    VfsToolCall,
    VirtualFileSystem,
)
from .unix import UnixFileSystemSession, UnixToolResult, unix_tool_schemas

__all__ = [
    "DirectoryEntry",
    "DirectoryListing",
    "EvidenceVerification",
    "FileReadResult",
    "FindEntry",
    "FindResult",
    "GrepHit",
    "GrepResult",
    "SearchHit",
    "SearchResult",
    "StatResult",
    "VfsAccessPolicy",
    "VfsToolCall",
    "VirtualFileSystem",
    "UnixFileSystemSession",
    "UnixToolResult",
    "unix_tool_schemas",
]
