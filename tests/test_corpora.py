from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from multi_agent_file_analysis.corpora import CorpusCatalog
from multi_agent_file_analysis.core import ConfigError


class CorpusCatalogTests(unittest.TestCase):
    def test_discovers_markers_chm_manifests_and_top_level_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            knowledge_base = Path(temporary) / "knowledge_base"

            openssh = knowledge_base / "ops" / "openssh"
            openssh.mkdir(parents=True)
            (openssh / ".mafa-corpus.yaml").write_text(
                "id: openssh\n"
                "name: OpenSSH\n"
                "description: SSH operations.\n",
                encoding="utf-8",
            )
            (openssh / "config.md").write_text("# SSH\n", encoding="utf-8")

            chm_mount = knowledge_base / "chm_imports" / "book-preview"
            chm_mount.mkdir(parents=True)
            (chm_mount / "manifest.json").write_text(
                json.dumps(
                    {
                        "archive_name": "Book.v2026.01.02.chm",
                        "archive_sha256": "abc",
                        "pages_converted": 1,
                        "mount_name": "book-preview",
                    }
                ),
                encoding="utf-8",
            )
            (chm_mount / "page.md").write_text("# Book\n", encoding="utf-8")

            plain = knowledge_base / "plain_docs"
            plain.mkdir(parents=True)
            (plain / "guide.MD").write_text("# Guide\n", encoding="utf-8")

            catalog = CorpusCatalog.discover(knowledge_base)

            self.assertEqual(
                ["Book", "OpenSSH", "plain docs"],
                [corpus.name for corpus in catalog.corpora],
            )
            self.assertEqual(
                [
                    "chm_imports/book-preview",
                    "ops/openssh",
                    "plain_docs",
                ],
                [corpus.relative_path.as_posix() for corpus in catalog.corpora],
            )
            self.assertEqual(
                ["chm-manifest", "marker", "top-level-directory"],
                [corpus.discovery_source for corpus in catalog.corpora],
            )

    def test_catalog_reflects_addition_and_removal_without_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            knowledge_base = Path(temporary) / "knowledge_base"
            first = knowledge_base / "first"
            second = knowledge_base / "second"
            first.mkdir(parents=True)
            (first / "one.md").write_text("one", encoding="utf-8")

            self.assertEqual(
                ["first"],
                [item.name for item in CorpusCatalog.discover(knowledge_base).corpora],
            )

            second.mkdir()
            (second / "two.md").write_text("two", encoding="utf-8")
            (first / "one.md").unlink()

            self.assertEqual(
                ["second"],
                [item.name for item in CorpusCatalog.discover(knowledge_base).corpora],
            )

    def test_invalid_marker_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            knowledge_base = Path(temporary) / "knowledge_base"
            corpus = knowledge_base / "invalid"
            corpus.mkdir(parents=True)
            (corpus / ".mafa-corpus.yaml").write_text(
                "id: ../escape\nname: Invalid\n",
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                CorpusCatalog.discover(knowledge_base)

    def test_empty_marked_directory_is_not_offered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            knowledge_base = Path(temporary) / "knowledge_base"
            corpus = knowledge_base / "empty"
            corpus.mkdir(parents=True)
            (corpus / ".mafa-corpus.yaml").write_text(
                "id: empty\nname: Empty\n",
                encoding="utf-8",
            )

            catalog = CorpusCatalog.discover(knowledge_base)

            self.assertEqual((), catalog.corpora)

    def test_symlinked_corpus_branch_is_not_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            knowledge_base = base / "knowledge_base"
            outside = base / "outside"
            knowledge_base.mkdir()
            outside.mkdir()
            (outside / "secret.md").write_text("secret", encoding="utf-8")
            (knowledge_base / "escape").symlink_to(outside, target_is_directory=True)

            catalog = CorpusCatalog.discover(knowledge_base)

            self.assertEqual((), catalog.corpora)


if __name__ == "__main__":
    unittest.main()
