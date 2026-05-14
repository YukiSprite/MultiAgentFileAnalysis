"""Page-index repository boundary.

The repository is the query layer over PageIndex. It centralizes path
normalization and source resolution so VFS does not need to understand the
details of tree traversal.
"""

from pathlib import Path

from .schema import IndexNode, PageIndex


class PageIndexRepository:
    """Resolves virtual paths against an in-memory page index.

    Future implementations must prevent path traversal. resolve_source_path()
    should only return files under knowledge_base_root.
    """

    def __init__(self, index: PageIndex, knowledge_base_root: Path) -> None:
        self._index = index
        self._knowledge_base_root = knowledge_base_root

    def get_node(self, virtual_path: str) -> IndexNode:
        """Return one index node by virtual path."""
        raise NotImplementedError

    def list_children(self, virtual_path: str) -> list[IndexNode]:
        """Return direct children for one virtual directory."""
        raise NotImplementedError

    def resolve_source_path(self, virtual_path: str) -> Path:
        """Map a virtual file path to its physical source document path."""
        raise NotImplementedError
