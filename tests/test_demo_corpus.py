from __future__ import annotations

import unittest
from pathlib import Path

from multi_agent_file_analysis.config import AppConfig
from multi_agent_file_analysis.index import PageIndexLoader, PageIndexRepository
from multi_agent_file_analysis.vfs import VirtualFileSystem


class StructuredDemoCorpusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        index_path = self.root / "configs" / "page_index.ops_demo.yaml"
        kb_root = self.root / "knowledge_base"
        index = PageIndexLoader().load(index_path)
        self.vfs = VirtualFileSystem(
            PageIndexRepository(index, kb_root),
            AppConfig(index_path, kb_root),
        )

    def test_current_lab_forwarding_query_retrieves_multiple_layers(self) -> None:
        result = self.vfs.v_search(
            "current-lab contractors SSH 隧道被拒绝",
            scope="/",
        )
        paths = {hit.path for hit in result.hits[:8]}
        self.assertIn(
            "/openssh/ssh-policy-b/forwarding_policy.md",
            paths,
        )
        self.assertIn("/scope/environment_matrix.md", paths)
        self.assertIn("/incidents/ssh_tunnel_denied.md", paths)

    def test_restart_query_separates_versioned_profiles(self) -> None:
        result = self.vfs.v_grep("/systemd", "StartLimitBurst")
        paths = {hit.path for hit in result.hits}
        self.assertIn(
            "/systemd/unit-policy-a/restart_policy.md",
            paths,
        )
        self.assertIn(
            "/systemd/unit-policy-b/restart_policy.md",
            paths,
        )


if __name__ == "__main__":
    unittest.main()
