"""Schema placeholders for the virtual page index.

The Page Index is the map that turns a physical knowledge base into a controlled
virtual tree. It should contain enough summaries for Explorer to choose useful
paths without reading every file.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class NodeKind(StrEnum):
    """Kinds of nodes exposed in the virtual page index."""

    DIRECTORY = "directory"
    FILE = "file"


@dataclass(slots=True)
class IndexNode:
    """A directory or file exposed by the virtual file system.

    path is virtual, source is physical. Directory nodes usually have children
    and no source; file nodes usually have source and no children.
    """

    path: str
    kind: NodeKind
    description: str
    source: str | None = None
    title: str | None = None
    tags: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    children: list["IndexNode"] = field(default_factory=list)


@dataclass(slots=True)
class SourceDocument:
    """A physical document mapped into the virtual file system.

    This metadata lets loaders validate encodings, detect stale files by
    checksum, and later support non-Markdown content types.
    """

    source: str
    content_type: str = "text/markdown"
    checksum: str | None = None
    encoding: str = "utf-8"


@dataclass(slots=True)
class PageIndex:
    """In-memory representation of the knowledge-base map.

    VFS implementations should resolve all virtual paths through this object or
    a PageIndexRepository built from it.
    """

    version: str
    root: IndexNode
    documents: list[SourceDocument] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
