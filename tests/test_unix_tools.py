from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from multi_agent_file_analysis.config import AppConfig
from multi_agent_file_analysis.index import (
    IndexNode,
    NodeKind,
    PageIndex,
    PageIndexRepository,
)
from multi_agent_file_analysis.vfs import (
    UnixFileSystemSession,
    VirtualFileSystem,
    unix_tool_schemas,
)


class UnixFileSystemToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        root = base / "kb"
        (root / "openssh").mkdir(parents=True)
        (root / "openssh" / "forwarding.md").write_text(
            "# Forwarding\n\n"
            "AllowTcpForwarding yes\n\n"
            "## Contractors\n\n"
            "Match Group contractors\n"
            "    DisableForwarding yes\n",
            encoding="utf-8",
        )
        index_path = base / "index.yaml"
        index_path.write_text("version: '0.2'\nroot:\n  path: /\n", encoding="utf-8")
        index = PageIndex(
            version="0.2",
            root=IndexNode(
                path="/",
                kind=NodeKind.DIRECTORY,
                description="root",
                children=[
                    IndexNode(
                        path="/openssh",
                        kind=NodeKind.DIRECTORY,
                        description="OpenSSH",
                        children=[
                            IndexNode(
                                path="/openssh/forwarding.md",
                                kind=NodeKind.FILE,
                                description="Forwarding policy",
                                source="openssh/forwarding.md",
                                tags=["openssh"],
                                metadata={
                                    "version": "9.x",
                                    "authority": "test",
                                },
                            )
                        ],
                    )
                ],
            ),
        )
        config = AppConfig(
            page_index_path=index_path,
            knowledge_base_root=root,
            max_read_lines=20,
        )
        repository = PageIndexRepository(index, root)
        self.session = UnixFileSystemSession(
            VirtualFileSystem(repository, config)
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_navigation_and_relative_cat_look_like_a_unix_workspace(self) -> None:
        self.assertEqual("/", self.session.execute("pwd").stdout)
        changed = self.session.execute("cd", {"path": "/openssh"})
        self.assertEqual(0, changed.exit_code)
        listing = self.session.execute("ls", {"path": "."})
        self.assertIn("/openssh/forwarding.md", listing.stdout)
        content = self.session.execute("cat", {"path": "forwarding.md"})
        self.assertEqual(0, content.exit_code)
        self.assertIn("DisableForwarding yes", content.stdout)
        self.assertEqual("/openssh/forwarding.md", content.data["path"])

    def test_grep_find_and_stat_are_backed_by_index_metadata(self) -> None:
        grep = self.session.execute(
            "grep",
            {"pattern": "disableforwarding", "path": "/", "context": 1},
        )
        self.assertEqual(0, grep.exit_code)
        self.assertIn("/openssh/forwarding.md:8", grep.stdout)

        find = self.session.execute(
            "find",
            {"path": "/", "name": "*forward*", "type": "file"},
        )
        self.assertEqual("/openssh/forwarding.md", find.stdout)

        stat = self.session.execute("stat", {"path": find.stdout})
        payload = json.loads(stat.stdout)
        self.assertEqual("file", payload["type"])
        self.assertEqual("9.x", payload["metadata"]["version"])
        self.assertNotIn(self.temporary.name, stat.stdout)

    def test_grep_limit_bounds_noisy_exact_matches(self) -> None:
        result = self.session.execute(
            "grep",
            {"pattern": "yes", "path": "/", "limit": 1},
        )

        self.assertEqual(0, result.exit_code)
        self.assertEqual(1, result.data["matches"])
        self.assertTrue(result.truncated)

    def test_unknown_or_mutating_commands_are_not_available(self) -> None:
        result = self.session.execute("rm", {"path": "/openssh/forwarding.md"})
        self.assertEqual(127, result.exit_code)
        self.assertIn("command not found", result.stderr)

    def test_parent_navigation_cannot_escape_virtual_root(self) -> None:
        result = self.session.execute("cd", {"path": "../../../../"})
        self.assertEqual(0, result.exit_code)
        self.assertEqual("/", self.session.cwd)

    def test_native_schema_uses_familiar_read_only_tool_names(self) -> None:
        names = {schema["name"] for schema in unix_tool_schemas()}
        self.assertEqual(
            {"pwd", "cd", "ls", "find", "stat", "cat", "head", "tail", "grep", "search"},
            names,
        )


if __name__ == "__main__":
    unittest.main()
