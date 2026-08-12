"""Standalone stdio entry point for the VFS MCP server."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .server import serve_vfs_mcp_stdio


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Serve one indexed MultiAgentFileAnalysis VFS over MCP stdio"
    )
    add_server_arguments(parser)
    args = parser.parse_args(argv)
    return run_server_from_args(args)


def add_server_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--page-index",
        type=Path,
        default=Path("configs/page_index.example.yaml"),
        help="Path to the Page Index YAML",
    )
    parser.add_argument(
        "--knowledge-base",
        type=Path,
        default=Path("knowledge_base"),
        help="Root used to resolve Page Index source paths",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=12_000,
        help="Maximum characters returned by one virtual file read",
    )


def run_server_from_args(args: argparse.Namespace) -> int:
    try:
        serve_vfs_mcp_stdio(
            args.page_index,
            args.knowledge_base,
            max_file_chars=args.max_chars,
        )
    except Exception as exc:
        # stderr is safe for diagnostics; stdout is reserved for MCP frames.
        print(f"VFS MCP initialization failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
