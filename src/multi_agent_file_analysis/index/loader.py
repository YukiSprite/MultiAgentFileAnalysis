"""Page-index YAML loading, validation, and deterministic generation."""

import hashlib
from pathlib import Path, PurePosixPath

import yaml

from multi_agent_file_analysis.core.errors import PageIndexError

from .schema import IndexNode, NodeKind, PageIndex, SourceDocument


class PageIndexLoader:
    """Loads and validates the static page index from YAML."""

    def load(self, path: Path) -> PageIndex:
        if not path.exists():
            raise PageIndexError(f"Page index file not found: {path}")
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise PageIndexError(f"Invalid YAML in page index: {exc}") from exc

        if not isinstance(raw, dict):
            raise PageIndexError("Page index root must be a mapping")

        version = raw.get("version", "0.1")
        root_raw = raw.get("root")
        if not isinstance(root_raw, dict):
            raise PageIndexError("Page index must have a 'root' mapping")

        root = self._parse_node(root_raw)
        if root.kind != NodeKind.DIRECTORY:
            raise PageIndexError("Root node must be a directory")

        documents = self._collect_documents(root)

        metadata = raw.get("metadata", {})
        if not isinstance(metadata, dict):
            raise PageIndexError("Page index metadata must be a mapping")
        index = PageIndex(
            version=str(version),
            root=root,
            documents=documents,
            metadata={str(k): str(v) for k, v in metadata.items()},
        )
        self.validate(index)
        return index

    def validate(self, index: PageIndex) -> None:
        seen: set[str] = set()

        def _check(node: IndexNode) -> None:
            norm = self._normalize_path(node.path)
            if norm in seen:
                raise PageIndexError(f"Duplicate virtual path: {norm}")
            seen.add(norm)

            if node.kind == NodeKind.DIRECTORY:
                if node.source is not None:
                    raise PageIndexError(
                        f"Directory node must not have source: {node.path}"
                    )
            elif node.kind == NodeKind.FILE:
                if node.source is None:
                    raise PageIndexError(
                        f"File node must have source: {node.path}"
                    )
                if node.children:
                    raise PageIndexError(
                        f"File node must not have children: {node.path}"
                    )
            else:
                raise PageIndexError(f"Unknown node kind for {node.path}: {node.kind}")

            for child in node.children:
                child_path = self._normalize_path(child.path)
                expected_parent = str(PurePosixPath(child_path).parent)
                if expected_parent == ".":
                    expected_parent = "/"
                if expected_parent != norm:
                    raise PageIndexError(
                        f"Child path {child.path} is not directly under parent "
                        f"{node.path}"
                    )
                _check(child)

        _check(index.root)

    def dump_example(self, path: Path) -> None:
        example = {
            "version": "0.1",
            "root": {
                "path": "/",
                "description": "Virtual root of the knowledge base.",
                "children": [
                    {
                        "path": "/examples",
                        "kind": "directory",
                        "description": "Example documents.",
                        "children": [
                            {
                                "path": "/examples/README.md",
                                "kind": "file",
                                "description": "Placeholder document.",
                                "source": "knowledge_base/README.md",
                            }
                        ],
                    }
                ],
            },
        }
        path.write_text(yaml.dump(example, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def _parse_node(self, raw: dict) -> IndexNode:
        path = raw.get("path", "")
        if not path or not isinstance(path, str):
            raise PageIndexError(f"Node missing valid path: {raw}")
        children_raw = raw.get("children", [])
        if not isinstance(children_raw, list):
            raise PageIndexError(f"children must be a list for node {path}")
        if any(not isinstance(child, dict) for child in children_raw):
            raise PageIndexError(f"Each child must be a mapping for node {path}")
        children = [self._parse_node(c) for c in children_raw]
        source = raw.get("source")
        tags = raw.get("tags", [])
        aliases = raw.get("aliases", [])
        metadata = raw.get("metadata", {})
        if not isinstance(tags, list) or not isinstance(aliases, list):
            raise PageIndexError(f"tags and aliases must be lists for node {path}")
        if not isinstance(metadata, dict):
            raise PageIndexError(f"metadata must be a mapping for node {path}")
        return IndexNode(
            path=self._normalize_path(path),
            kind=NodeKind(raw.get("kind", "directory")),
            description=str(raw.get("description", "")),
            source=str(source) if source else None,
            title=raw.get("title"),
            tags=[str(tag) for tag in tags],
            aliases=[str(alias) for alias in aliases],
            metadata={str(k): str(v) for k, v in metadata.items()},
            children=children,
        )

    @staticmethod
    def _normalize_path(path: str) -> str:
        if "\\" in path or "\x00" in path:
            raise PageIndexError(f"Invalid virtual path: {path}")
        if not path.startswith("/"):
            path = "/" + path
        parts = [p for p in path.split("/") if p]
        if any(part in {".", ".."} for part in parts):
            raise PageIndexError(f"Path traversal denied: {path}")
        return "/" + "/".join(parts) if parts else "/"

    @classmethod
    def scan_directory(
        cls, knowledge_base_root: Path, output_path: Path
    ) -> PageIndex:
        """Scan knowledge_base/ and generate a page index YAML, then load it.

        Creates virtual paths mirroring the physical directory structure.
        Extracts the first markdown heading as the file description.
        """
        root_dir = knowledge_base_root.resolve()
        if not root_dir.is_dir():
            raise PageIndexError(
                f"Knowledge-base root is not a directory: {root_dir}"
            )
        yaml_data = {
            "version": "0.1",
            "metadata": {
                "generated": "true",
                "source_root": str(root_dir),
            },
            "root": {
                "path": "/",
                "description": "Auto-generated virtual root.",
                "children": [],
            },
        }

        _scan_dir(root_dir, root_dir, yaml_data["root"]["children"])
        _write_yaml(yaml_data, output_path)
        return cls().load(output_path)

    @staticmethod
    def _collect_documents(root: IndexNode) -> list[SourceDocument]:
        docs: list[SourceDocument] = []

        def _walk(node: IndexNode) -> None:
            if node.kind == NodeKind.FILE and node.source:
                docs.append(
                    SourceDocument(
                        source=node.source,
                        checksum=node.metadata.get("sha256"),
                    )
                )
            for child in node.children:
                _walk(child)

        _walk(root)
        return docs


def _write_yaml(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def _scan_dir(
    root_dir: Path,
    current_dir: Path,
    children: list[dict],
) -> None:
    entries = sorted(current_dir.iterdir(), key=lambda p: (p.is_file(), p.name))
    for entry in entries:
        if entry.name.startswith(".") or entry.name.startswith("_"):
            continue
        if entry.is_symlink():
            continue

        if entry.is_dir():
            sub_children: list[dict] = []
            children.append(
                {
                    "path": _to_virtual_path(root_dir, entry),
                    "kind": "directory",
                    "description": entry.name.replace("_", " "),
                    "children": sub_children,
                }
            )
            _scan_dir(root_dir, entry, sub_children)

        elif entry.suffix == ".md":
            description = _extract_heading(entry)
            digest = hashlib.sha256(entry.read_bytes()).hexdigest()
            children.append(
                {
                    "path": _to_virtual_path(root_dir, entry),
                    "kind": "file",
                    "description": description,
                    "source": str(entry.relative_to(root_dir)),
                    "metadata": {
                        "sha256": digest,
                        "content_type": "text/markdown",
                    },
                }
            )


def _to_virtual_path(root_dir: Path, entry: Path) -> str:
    rel = entry.relative_to(root_dir)
    return "/" + str(rel).replace("\\", "/")


def _extract_heading(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("## "):
                return stripped[2:].strip()
        return path.stem.replace("_", " ")
    except Exception:
        return path.stem.replace("_", " ")
