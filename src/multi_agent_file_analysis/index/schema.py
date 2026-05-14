"""Schema placeholders for the virtual page index."""

from dataclasses import dataclass, field
from enum import StrEnum


class NodeKind(StrEnum):
    """Kinds of nodes exposed in the virtual page index."""

    DIRECTORY = "directory"
    FILE = "file"


@dataclass(slots=True)
class IndexNode:
    """A directory or file exposed by the virtual file system."""

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
    """A physical document mapped into the virtual file system."""

    source: str
    content_type: str = "text/markdown"
    checksum: str | None = None
    encoding: str = "utf-8"


@dataclass(slots=True)
class PageIndex:
    """In-memory representation of the knowledge-base map."""

    version: str
    root: IndexNode
    documents: list[SourceDocument] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
