from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mcp.client import Client

from multi_agent_file_analysis.config import AppConfig
from multi_agent_file_analysis.index import (
    IndexNode,
    NodeKind,
    PageIndex,
    PageIndexRepository,
)
from multi_agent_file_analysis.mcp import (
    VFS_MCP_TOOL_NAMES,
    create_vfs_mcp_server,
    load_virtual_file_system,
)
from multi_agent_file_analysis.vfs import VirtualFileSystem


class VfsMCPServerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.root = base / "kb"
        (self.root / "openssh").mkdir(parents=True)
        self.source = self.root / "openssh" / "forwarding.md"
        self.source.write_text(
            "# Forwarding\n\n"
            "AllowTcpForwarding accepts yes, all, no, local, or remote.\n\n"
            "## Scope\n\nMatch blocks can narrow the rule.\n",
            encoding="utf-8",
        )
        self.index_path = base / "index.yaml"
        self.index_path.write_text(
            "version: '0.2'\n"
            "root:\n"
            "  path: /\n"
            "  kind: directory\n"
            "  children:\n"
            "    - path: /openssh\n"
            "      kind: directory\n"
            "      children:\n"
            "        - path: /openssh/forwarding.md\n"
            "          kind: file\n"
            "          description: Forwarding directives\n"
            "          source: openssh/forwarding.md\n"
            "          metadata:\n"
            "            product: openssh\n"
            "            version: 9.x\n",
            encoding="utf-8",
        )
        root = IndexNode(
            path="/",
            kind=NodeKind.DIRECTORY,
            description="root",
            children=[
                IndexNode(
                    path="/openssh",
                    kind=NodeKind.DIRECTORY,
                    description="OpenSSH manuals",
                    children=[
                        IndexNode(
                            path="/openssh/forwarding.md",
                            kind=NodeKind.FILE,
                            description="Forwarding directives",
                            source="openssh/forwarding.md",
                            metadata={"product": "openssh", "version": "9.x"},
                        )
                    ],
                )
            ],
        )
        config = AppConfig(
            page_index_path=self.index_path,
            knowledge_base_root=self.root,
        )
        vfs = VirtualFileSystem(
            PageIndexRepository(PageIndex(version="0.2", root=root), self.root),
            config,
        )
        self.server = create_vfs_mcp_server(vfs)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    async def test_registers_complete_read_only_tool_surface(self) -> None:
        async with Client(self.server) as client:
            result = await client.list_tools()

        tools = {tool.name: tool for tool in result.tools}
        self.assertEqual(VFS_MCP_TOOL_NAMES, tools.keys())
        for tool in tools.values():
            self.assertIsNotNone(tool.input_schema)
            self.assertIsNotNone(tool.output_schema)
            self.assertIn("properties", tool.output_schema)
            self.assertIsNotNone(tool.annotations)
            self.assertTrue(tool.annotations.read_only_hint)
            self.assertFalse(tool.annotations.destructive_hint)
            self.assertTrue(tool.annotations.idempotent_hint)
            self.assertFalse(tool.annotations.open_world_hint)

    async def test_all_vfs_operations_return_structured_mcp_results(self) -> None:
        path = "/openssh/forwarding.md"
        quote = "AllowTcpForwarding accepts yes, all, no, local, or remote."
        calls = [
            ("v_ls", {"path": "/"}),
            ("v_cat", {"path": path, "start_line": 1, "end_line": 3}),
            ("v_read_range", {"path": path, "start_line": 3, "end_line": 3}),
            ("v_grep", {"path": "/", "pattern": "AllowTcpForwarding"}),
            ("v_search", {"query": "AllowTcpForwarding", "scope": "/"}),
            ("v_find", {"path": "/", "name": "*.md", "kind": "file"}),
            ("v_stat", {"path": path}),
            ("verify_quote", {"path": path, "quote": quote}),
            ("get_metadata", {"path": path}),
        ]

        async with Client(self.server) as client:
            results = {
                name: await client.call_tool(name, arguments)
                for name, arguments in calls
            }

        for name, result in results.items():
            self.assertFalse(result.is_error, name)
            self.assertIsInstance(result.structured_content, dict, name)
        self.assertEqual(
            "/openssh", results["v_ls"].structured_content["entries"][0]["path"]
        )
        self.assertIn(
            "AllowTcpForwarding", results["v_cat"].structured_content["content"]
        )
        self.assertEqual(1, len(results["v_grep"].structured_content["hits"]))
        self.assertEqual(1, len(results["v_search"].structured_content["hits"]))
        self.assertEqual(1, len(results["v_find"].structured_content["entries"]))
        self.assertEqual("file", results["v_stat"].structured_content["kind"])
        self.assertEqual(3, results["verify_quote"].structured_content["line_start"])
        self.assertEqual(
            "openssh",
            results["get_metadata"].structured_content["metadata"]["product"],
        )

    async def test_mcp_results_and_errors_do_not_expose_host_paths(self) -> None:
        virtual_path = "/openssh/forwarding.md"
        async with Client(self.server) as client:
            successful = await client.call_tool("v_cat", {"path": virtual_path})
            self.assertFalse(successful.is_error)
            self.assertEqual(
                virtual_path,
                successful.structured_content["source_path"],
            )
            self.assertNotIn(str(self.root), successful.model_dump_json(by_alias=True))

            self.source.unlink()
            failed = await client.call_tool("v_cat", {"path": virtual_path})

        self.assertTrue(failed.is_error)
        self.assertNotIn(str(self.root), failed.model_dump_json(by_alias=True))
        self.assertIn(virtual_path, failed.model_dump_json(by_alias=True))

    def test_runtime_loader_mounts_only_the_requested_index(self) -> None:
        vfs = load_virtual_file_system(self.index_path, self.root)

        listing = vfs.v_ls("/")

        self.assertEqual(["/openssh"], [entry.path for entry in listing.entries])


if __name__ == "__main__":
    unittest.main()
