from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from multi_agent_file_analysis.config import AppConfig
from multi_agent_file_analysis.core import PageIndexError
from multi_agent_file_analysis.index import (
    IndexNode,
    NodeKind,
    PageIndex,
    PageIndexLoader,
    PageIndexRepository,
)
from multi_agent_file_analysis.vfs import VirtualFileSystem


class VirtualFileSystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.root = base / "kb"
        (self.root / "openssh").mkdir(parents=True)
        (self.root / "systemd").mkdir(parents=True)
        (self.root / "openssh" / "forwarding.md").write_text(
            "# Forwarding\n\n"
            "AllowTcpForwarding accepts yes, all, no, local, or remote.\n\n"
            "## Scope\n\nMatch blocks can narrow the rule.\n",
            encoding="utf-8",
        )
        (self.root / "systemd" / "restart.md").write_text(
            "# Restart policy\n\n"
            "Restart=on-failure applies after an abnormal service exit.\n",
            encoding="utf-8",
        )
        self.index_path = base / "index.yaml"
        self.index_path.write_text("version: '0.2'\nroot:\n  path: /\n", encoding="utf-8")
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
                            aliases=["SSH tunnel"],
                            metadata={"version": "9.x", "product": "openssh"},
                        )
                    ],
                ),
                IndexNode(
                    path="/systemd",
                    kind=NodeKind.DIRECTORY,
                    description="systemd manuals",
                    children=[
                        IndexNode(
                            path="/systemd/restart.md",
                            kind=NodeKind.FILE,
                            description="Service restart rules",
                            source="systemd/restart.md",
                            metadata={"version": "255", "product": "systemd"},
                        )
                    ],
                ),
            ],
        )
        index = PageIndex(version="0.2", root=root)
        config = AppConfig(
            page_index_path=self.index_path,
            knowledge_base_root=self.root,
            max_directory_entries=1,
            max_read_lines=2,
        )
        self.repository = PageIndexRepository(index, self.root)
        self.vfs = VirtualFileSystem(self.repository, config)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_directory_listing_is_paginated(self) -> None:
        first = self.vfs.v_ls("/")
        self.assertEqual(1, len(first.entries))
        self.assertTrue(first.truncated)
        self.assertEqual(1, first.next_offset)
        second = self.vfs.v_ls("/", offset=first.next_offset or 0)
        self.assertEqual(1, len(second.entries))
        self.assertFalse(second.truncated)

    def test_read_range_can_reach_later_content(self) -> None:
        result = self.vfs.v_read_range("/openssh/forwarding.md", 5, 6)
        self.assertEqual(5, result.start_line)
        self.assertIn("Scope", result.content)

    def test_grep_searches_a_directory_case_insensitively(self) -> None:
        result = self.vfs.v_grep("/", "allowtcpforwarding")
        self.assertEqual(2, result.files_searched)
        self.assertEqual(1, len(result.hits))
        self.assertEqual("/openssh/forwarding.md", result.hits[0].path)
        self.assertEqual("Forwarding", result.hits[0].section)

    def test_search_uses_aliases_and_metadata(self) -> None:
        result = self.vfs.v_search(
            "SSH tunnel",
            filters={"product": "openssh"},
        )
        self.assertEqual(1, len(result.hits))
        self.assertEqual("/openssh/forwarding.md", result.hits[0].path)

    def test_evidence_quote_is_bound_to_source(self) -> None:
        quote = "AllowTcpForwarding accepts yes, all, no, local, or remote."
        verified = self.vfs.verify_quote("/openssh/forwarding.md", quote)
        self.assertEqual(3, verified.line_start)
        self.assertEqual("Forwarding", verified.section)
        self.assertTrue(verified.content_hash)
        with self.assertRaises(Exception):
            self.vfs.verify_quote(
                "/openssh/forwarding.md",
                "AllowTcpForwarding accepts on or off.",
            )

    def test_source_path_cannot_escape_by_prefix_collision(self) -> None:
        sibling = self.root.parent / "kb-secret"
        sibling.mkdir()
        (sibling / "secret.md").write_text("secret", encoding="utf-8")
        index = PageIndex(
            version="0.2",
            root=IndexNode(
                path="/",
                kind=NodeKind.DIRECTORY,
                description="root",
                children=[
                    IndexNode(
                        path="/secret.md",
                        kind=NodeKind.FILE,
                        description="secret",
                        source="../kb-secret/secret.md",
                    )
                ],
            ),
        )
        repository = PageIndexRepository(index, self.root)
        with self.assertRaises(PageIndexError):
            repository.resolve_source_path("/secret.md")

    def test_virtual_path_traversal_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            self.vfs.v_ls("/openssh/../systemd")
        with self.assertRaises(PageIndexError):
            self.repository.get_node("/openssh/../systemd")

    def test_directory_scan_writes_relative_sources(self) -> None:
        output = self.root.parent / "generated.yaml"
        index = PageIndexLoader.scan_directory(self.root, output)
        sources = {document.source for document in index.documents}
        self.assertIn("openssh/forwarding.md", sources)
        reloaded = PageIndexLoader().load(output)
        repository = PageIndexRepository(reloaded, self.root)
        self.assertTrue(
            repository.resolve_source_path("/openssh/forwarding.md").is_file()
        )


if __name__ == "__main__":
    unittest.main()
