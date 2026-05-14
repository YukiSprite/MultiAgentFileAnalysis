"""Virtual file-system protocol exposed to retrieval agents."""

from .policy import VfsAccessPolicy
from .protocol import (
    DirectoryEntry,
    DirectoryListing,
    FileReadResult,
    GrepHit,
    GrepResult,
    VfsToolCall,
    VirtualFileSystem,
)

__all__ = [
    "DirectoryEntry",
    "DirectoryListing",
    "FileReadResult",
    "GrepHit",
    "GrepResult",
    "VfsAccessPolicy",
    "VfsToolCall",
    "VirtualFileSystem",
]
