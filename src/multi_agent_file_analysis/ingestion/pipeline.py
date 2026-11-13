"""Offline ingestion for local Markdown and plain-text sources."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import yaml

from multi_agent_file_analysis.core import PageIndexError
from multi_agent_file_analysis.index import (
    IndexNode,
    NodeKind,
    PageIndex,
    PageIndexLoader,
    SourceDocument,
)

from .schema import DocumentSource, IngestedDocument, IngestionPlan


class KnowledgeBaseBuilder:
    """Normalize local sources and publish a deterministic Page Index."""

    def __init__(
        self,
        output_root: Path = Path("knowledge_base"),
        page_index_path: Path = Path("configs/page_index.yaml"),
    ) -> None:
        self._output_root = output_root
        self._page_index_path = page_index_path

    def plan(self, sources: list[DocumentSource]) -> IngestionPlan:
        if not sources:
            raise PageIndexError("At least one document source is required")
        for source in sources:
            path = self._local_path(source.uri)
            if not path.is_file():
                raise PageIndexError(f"Source file not found: {path}")
            if path.suffix.casefold() not in {".md", ".markdown", ".txt"}:
                raise PageIndexError(
                    f"Unsupported source type for {path}; use Markdown or text"
                )
        return IngestionPlan(
            sources=list(sources),
            output_root=self._output_root,
            page_index_path=self._page_index_path,
        )

    def ingest(self, plan: IngestionPlan) -> list[IngestedDocument]:
        output_root = (plan.output_root or self._output_root).resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        documents: list[IngestedDocument] = []
        used_paths: set[str] = set()

        for source in plan.sources:
            source_path = self._local_path(source.uri).resolve()
            virtual_path = source.metadata.get("virtual_path")
            if virtual_path:
                virtual_path = self._normalize_virtual_path(virtual_path)
            else:
                virtual_path = "/" + self._slug_filename(source_path, source)
            if virtual_path in used_paths:
                raise PageIndexError(f"Duplicate virtual path: {virtual_path}")
            used_paths.add(virtual_path)

            target = (output_root / virtual_path.lstrip("/")).resolve()
            if not target.is_relative_to(output_root):
                raise PageIndexError(
                    f"Ingestion target escapes output root: {virtual_path}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)

            content = source_path.read_text(encoding="utf-8", errors="replace")
            if source_path.suffix.casefold() == ".txt":
                title = source.title or source_path.stem
                content = f"# {title}\n\n{content}"
            if source_path != target:
                target.write_text(content, encoding="utf-8")

            description = (
                source.title
                or self._extract_heading(content)
                or source_path.stem.replace("_", " ")
            )
            documents.append(
                IngestedDocument(
                    source=source,
                    virtual_path=virtual_path,
                    local_path=target,
                    description=description,
                )
            )
        return documents

    def build_index(self, documents: list[IngestedDocument]) -> PageIndex:
        if not documents:
            raise PageIndexError("Cannot build an index without documents")
        output_root = self._output_root.resolve()
        root = IndexNode(
            path="/",
            kind=NodeKind.DIRECTORY,
            description="Versioned virtual knowledge-base root.",
        )
        directory_map: dict[str, IndexNode] = {"/": root}
        source_documents: list[SourceDocument] = []

        for document in sorted(documents, key=lambda item: item.virtual_path):
            virtual = self._normalize_virtual_path(document.virtual_path)
            parts = [part for part in virtual.split("/") if part]
            parent = root
            accumulated = ""
            for part in parts[:-1]:
                accumulated += "/" + part
                directory = directory_map.get(accumulated)
                if directory is None:
                    directory = IndexNode(
                        path=accumulated,
                        kind=NodeKind.DIRECTORY,
                        description=part.replace("_", " "),
                    )
                    parent.children.append(directory)
                    directory_map[accumulated] = directory
                parent = directory

            local_path = document.local_path.resolve()
            if not local_path.is_relative_to(output_root):
                raise PageIndexError(
                    f"Ingested file is outside output root: {local_path}"
                )
            digest = hashlib.sha256(local_path.read_bytes()).hexdigest()
            relative_source = local_path.relative_to(output_root).as_posix()
            metadata = dict(document.source.metadata)
            metadata.pop("virtual_path", None)
            metadata["sha256"] = digest
            metadata["content_type"] = "text/markdown"
            parent.children.append(
                IndexNode(
                    path=virtual,
                    kind=NodeKind.FILE,
                    description=document.description,
                    source=relative_source,
                    title=document.source.title,
                    tags=list(document.source.tags),
                    metadata=metadata,
                )
            )
            source_documents.append(
                SourceDocument(source=relative_source, checksum=digest)
            )

        self._sort_tree(root)
        index = PageIndex(
            version="0.2",
            root=root,
            documents=source_documents,
            metadata={"generated": "true"},
        )
        PageIndexLoader().validate(index)
        self._write_index(index, self._page_index_path)
        return index

    def build(self, sources: list[DocumentSource]) -> PageIndex:
        plan = self.plan(sources)
        documents = self.ingest(plan)
        return self.build_index(documents)

    @staticmethod
    def _local_path(uri: str) -> Path:
        if uri.startswith("file:"):
            parsed = urlparse(uri)
            if parsed.netloc not in {"", "localhost"}:
                raise PageIndexError(
                    f"Unsupported file URI host: {uri}"
                )
            return Path(url2pathname(parsed.path))
        parsed = urlparse(uri)
        # A Windows drive letter looks like a URI scheme ("C:\docs\a.md").
        is_windows_drive = (
            len(uri) >= 2 and uri[1] == ":" and uri[0].isalpha()
        )
        if parsed.scheme and not is_windows_drive:
            raise PageIndexError(
                f"Only local file sources are supported in this MVP: {uri}"
            )
        return Path(uri)

    @staticmethod
    def _normalize_virtual_path(path: str) -> str:
        parts = [part for part in path.replace("\\", "/").split("/") if part]
        if not parts or any(part in {".", ".."} for part in parts):
            raise PageIndexError(f"Invalid virtual path: {path}")
        normalized = "/" + "/".join(parts)
        if not normalized.casefold().endswith(".md"):
            normalized += ".md"
        return normalized

    @staticmethod
    def _slug_filename(path: Path, source: DocumentSource) -> str:
        stem = source.title or path.stem
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-").casefold()
        return (slug or "document") + ".md"

    @staticmethod
    def _extract_heading(content: str) -> str | None:
        for line in content.splitlines():
            if line.startswith("# "):
                return line[2:].strip() or None
        return None

    @classmethod
    def _sort_tree(cls, node: IndexNode) -> None:
        node.children.sort(key=lambda child: (child.kind == NodeKind.FILE, child.path))
        for child in node.children:
            cls._sort_tree(child)

    @classmethod
    def _write_index(cls, index: PageIndex, path: Path) -> None:
        payload = {
            "version": index.version,
            "metadata": index.metadata,
            "root": cls._node_to_mapping(index.root),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    @classmethod
    def _node_to_mapping(cls, node: IndexNode) -> dict:
        payload: dict = {
            "path": node.path,
            "kind": str(node.kind),
            "description": node.description,
        }
        if node.source:
            payload["source"] = node.source
        if node.title:
            payload["title"] = node.title
        if node.tags:
            payload["tags"] = node.tags
        if node.aliases:
            payload["aliases"] = node.aliases
        if node.metadata:
            payload["metadata"] = node.metadata
        if node.children:
            payload["children"] = [
                cls._node_to_mapping(child) for child in node.children
            ]
        return payload
