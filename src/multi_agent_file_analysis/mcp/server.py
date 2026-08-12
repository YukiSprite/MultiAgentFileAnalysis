"""Read-only MCP server backed by the indexed virtual filesystem."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import cast

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from multi_agent_file_analysis.config import AppConfig
from multi_agent_file_analysis.core import RunMode
from multi_agent_file_analysis.index import PageIndexLoader, PageIndexRepository
from multi_agent_file_analysis.vfs import VirtualFileSystem

from .schema import (
    DirectoryListingOutput,
    EvidenceVerificationOutput,
    FileReadOutput,
    FindOutput,
    GrepOutput,
    MetadataOutput,
    SearchOutput,
    StatOutput,
)

VFS_MCP_TOOL_NAMES = frozenset(
    {
        "v_ls",
        "v_cat",
        "v_read_range",
        "v_grep",
        "v_search",
        "v_find",
        "v_stat",
        "verify_quote",
        "get_metadata",
    }
)


def _read_only_annotations(title: str) -> ToolAnnotations:
    return ToolAnnotations(
        title=title,
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )


def create_vfs_mcp_server(
    vfs: VirtualFileSystem,
    *,
    name: str = "multi-agent-file-analysis-vfs",
) -> MCPServer:
    """Create an MCP server whose tools are confined to one injected VFS."""
    server = MCPServer(
        name=name,
        title="MultiAgentFileAnalysis Virtual Filesystem",
        version="0.2.0",
        instructions=(
            "Use these read-only tools to browse and search the mounted Page "
            "Index. Paths are POSIX virtual paths rooted at '/'. Only indexed "
            "documents are visible; host filesystem paths and shell execution "
            "are unavailable. Read and search responses are budget-limited and "
            "may be marked truncated."
        ),
    )

    @server.tool(
        annotations=_read_only_annotations("List virtual directory"),
        structured_output=True,
    )
    def v_ls(
        path: str = "/",
        offset: int = 0,
        limit: int | None = None,
        query: str | None = None,
    ) -> DirectoryListingOutput:
        """List one virtual directory level with pagination and optional filtering."""
        return cast(
            DirectoryListingOutput,
            asdict(vfs.v_ls(path, offset=offset, limit=limit, query=query)),
        )

    @server.tool(
        annotations=_read_only_annotations("Read virtual file"),
        structured_output=True,
    )
    def v_cat(
        path: str,
        start_line: int = 1,
        end_line: int | None = None,
    ) -> FileReadOutput:
        """Read a bounded line range from one indexed virtual file."""
        return cast(
            FileReadOutput,
            asdict(vfs.v_cat(path, start_line=start_line, end_line=end_line)),
        )

    @server.tool(
        annotations=_read_only_annotations("Read explicit virtual line range"),
        structured_output=True,
    )
    def v_read_range(
        path: str,
        start_line: int,
        end_line: int,
    ) -> FileReadOutput:
        """Read an explicit bounded line range from an indexed virtual file."""
        return cast(
            FileReadOutput,
            asdict(vfs.v_read_range(path, start_line, end_line)),
        )

    @server.tool(
        annotations=_read_only_annotations("Grep virtual files"),
        structured_output=True,
    )
    def v_grep(
        path: str,
        pattern: str,
        case_sensitive: bool = False,
        whole_word: bool = False,
        context_lines: int | None = None,
        limit: int | None = None,
    ) -> GrepOutput:
        """Search a virtual file or directory for a bounded literal pattern."""
        return cast(
            GrepOutput,
            asdict(
                vfs.v_grep(
                    path,
                    pattern,
                    case_sensitive=case_sensitive,
                    whole_word=whole_word,
                    context_lines=context_lines,
                    limit=limit,
                )
            ),
        )

    @server.tool(
        annotations=_read_only_annotations("Search indexed documents"),
        structured_output=True,
    )
    def v_search(
        query: str,
        scope: str = "/",
        limit: int | None = None,
        filters: dict[str, str] | None = None,
    ) -> SearchOutput:
        """Rank indexed virtual files with bounded metadata-aware lexical search."""
        return cast(
            SearchOutput,
            asdict(
                vfs.v_search(
                    query,
                    scope=scope,
                    limit=limit,
                    filters=filters,
                )
            ),
        )

    @server.tool(
        annotations=_read_only_annotations("Find indexed virtual nodes"),
        structured_output=True,
    )
    def v_find(
        path: str = "/",
        name: str = "*",
        kind: str | None = None,
        limit: int | None = None,
        filters: dict[str, str] | None = None,
    ) -> FindOutput:
        """Find indexed virtual nodes by glob, kind, and optional metadata filters."""
        return cast(
            FindOutput,
            asdict(
                vfs.v_find(
                    path,
                    name=name,
                    kind=kind,
                    limit=limit,
                    filters=filters,
                )
            ),
        )

    @server.tool(
        annotations=_read_only_annotations("Stat indexed virtual node"),
        structured_output=True,
    )
    def v_stat(path: str) -> StatOutput:
        """Return safe metadata for one indexed virtual path."""
        return cast(StatOutput, asdict(vfs.v_stat(path)))

    @server.tool(
        annotations=_read_only_annotations("Verify source quote"),
        structured_output=True,
    )
    def verify_quote(path: str, quote: str) -> EvidenceVerificationOutput:
        """Verify that a quote occurs verbatim and bind it to source coordinates."""
        return cast(
            EvidenceVerificationOutput,
            asdict(vfs.verify_quote(path, quote)),
        )

    @server.tool(
        annotations=_read_only_annotations("Read indexed metadata"),
        structured_output=True,
    )
    def get_metadata(path: str) -> MetadataOutput:
        """Return Page Index metadata for one virtual path."""
        return {"path": path, "metadata": vfs.get_metadata(path)}

    return server


def load_virtual_file_system(
    page_index_path: Path,
    knowledge_base_root: Path,
    *,
    max_file_chars: int = 12_000,
) -> VirtualFileSystem:
    """Load and validate only the services required by the VFS MCP server."""
    config = AppConfig(
        page_index_path=page_index_path.resolve(),
        knowledge_base_root=knowledge_base_root.resolve(),
        run_mode=RunMode.DRY_RUN,
        max_file_chars=max_file_chars,
    )
    config.validate()
    page_index = PageIndexLoader().load(config.page_index_path)
    repository = PageIndexRepository(page_index, config.knowledge_base_root)
    return VirtualFileSystem(repository, config)


def serve_vfs_mcp_stdio(
    page_index_path: Path,
    knowledge_base_root: Path,
    *,
    max_file_chars: int = 12_000,
) -> None:
    """Load one VFS mount and serve it over the local MCP stdio transport."""
    vfs = load_virtual_file_system(
        page_index_path,
        knowledge_base_root,
        max_file_chars=max_file_chars,
    )
    create_vfs_mcp_server(vfs).run(transport="stdio")
