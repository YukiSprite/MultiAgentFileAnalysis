"""Virtual file-system protocol exposed to retrieval agents."""

from .policy import VfsAccessPolicy
from .protocol import (
    DirectoryEntry,
    DirectoryListing,
    EvidenceVerification,
    FileReadResult,
    GrepHit,
    GrepResult,
    SearchHit,
    SearchResult,
    VfsToolCall,
    VirtualFileSystem,
)

__all__ = [
    "DirectoryEntry",
    "DirectoryListing",
    "EvidenceVerification",
    "FileReadResult",
    "GrepHit",
    "GrepResult",
    "SearchHit",
    "SearchResult",
    "VfsAccessPolicy",
    "VfsToolCall",
    "VirtualFileSystem",
]
