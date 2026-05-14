"""Schema placeholders for the virtual page index."""

from dataclasses import dataclass, field
from typing import Literal


NodeKind = Literal["directory", "file"]


@dataclass(slots=True)
class IndexNode:
    """A directory or file exposed by the virtual file system."""

    path: str
    kind: NodeKind
    description: str
    source: str | None = None
    children: list["IndexNode"] = field(default_factory=list)


@dataclass(slots=True)
class PageIndex:
    """In-memory representation of the knowledge-base map."""

    version: str
    root: IndexNode
