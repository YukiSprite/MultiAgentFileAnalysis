"""Page-index repository — virtual path resolution and traversal."""

from collections.abc import Iterator
from pathlib import Path

from multi_agent_file_analysis.core.errors import PageIndexError

from .schema import IndexNode, NodeKind, PageIndex


class PageIndexRepository:
    """Resolves virtual paths against an in-memory page index."""

    def __init__(self, index: PageIndex, knowledge_base_root: Path) -> None:
        self._index = index
        self._knowledge_base_root = knowledge_base_root.resolve()
        self._node_map: dict[str, IndexNode] = {}
        self._build_map(index.root)

    def get_node(self, virtual_path: str) -> IndexNode:
        norm = self._normalize(virtual_path)
        node = self._node_map.get(norm)
        if node is None:
            raise PageIndexError(f"Virtual path not found in index: {norm}")
        return node

    def list_children(self, virtual_path: str) -> list[IndexNode]:
        node = self.get_node(virtual_path)
        if node.kind != NodeKind.DIRECTORY:
            raise PageIndexError(f"Not a virtual directory: {virtual_path}")
        return list(node.children)

    def resolve_source_path(self, virtual_path: str) -> Path:
        node = self.get_node(virtual_path)
        if node.source is None:
            raise PageIndexError(f"Node has no source mapping: {virtual_path}")
        resolved = (self._knowledge_base_root / node.source).resolve()
        if not resolved.is_relative_to(self._knowledge_base_root):
            raise PageIndexError(
                f"Source path escapes knowledge_base_root: {node.source}"
            )
        return resolved

    def iter_nodes(self, virtual_path: str = "/") -> Iterator[IndexNode]:
        """Yield a node and all descendants in deterministic tree order."""
        root = self.get_node(virtual_path)
        yield root
        for child in root.children:
            yield from self.iter_nodes(child.path)

    def iter_files(self, virtual_path: str = "/") -> Iterator[IndexNode]:
        """Yield indexed file nodes below a file or directory scope."""
        node = self.get_node(virtual_path)
        if node.kind == NodeKind.FILE:
            yield node
            return
        for candidate in self.iter_nodes(virtual_path):
            if candidate.kind == NodeKind.FILE:
                yield candidate

    @property
    def index(self) -> PageIndex:
        return self._index

    @staticmethod
    def _normalize(path: str) -> str:
        if "\\" in path or "\x00" in path:
            raise PageIndexError(f"Invalid virtual path: {path}")
        if not path.startswith("/"):
            path = "/" + path
        parts = [p for p in path.split("/") if p]
        if any(part in {".", ".."} for part in parts):
            raise PageIndexError(f"Path traversal denied: {path}")
        return "/" + "/".join(parts) if parts else "/"

    def _build_map(self, node: IndexNode) -> None:
        self._node_map[self._normalize(node.path)] = node
        for child in node.children:
            self._build_map(child)
