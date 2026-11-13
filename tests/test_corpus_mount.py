from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from multi_agent_file_analysis.app import mount_corpus
from multi_agent_file_analysis.core import RunMode
from multi_agent_file_analysis.corpora import CorpusCatalog


def _write_corpus(root: Path, name: str, corpus_id: str, content: str) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "rules.md").write_text(content, encoding="utf-8")
    (directory / ".mafa-corpus.yaml").write_text(
        f"id: {corpus_id}\nname: {name}\n",
        encoding="utf-8",
    )
    return directory


class CorpusMountTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.base = Path(self._temporary.name)
        self.knowledge_base = self.base / "knowledge_base"
        self.knowledge_base.mkdir()
        self.dnd = _write_corpus(
            self.knowledge_base,
            "dnd",
            "dnd",
            "# DND Rules\n\nDND_ALPHA is one.\n",
        )
        self.openssh = _write_corpus(
            self.knowledge_base,
            "openssh",
            "openssh",
            "# SSH Rules\n\nSSH_SECRET must stay isolated.\n",
        )
        self.catalog = CorpusCatalog.discover(self.knowledge_base)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _corpus(self, corpus_id: str):
        for corpus in self.catalog.corpora:
            if corpus.corpus_id == corpus_id:
                return corpus
        raise AssertionError(f"missing corpus {corpus_id}")

    def test_mount_builds_index_and_serves_selected_corpus(self) -> None:
        mount = mount_corpus(
            self._corpus("dnd"),
            self.knowledge_base,
            run_mode=RunMode.DRY_RUN,
            env_file_path=self.base / "missing.env",
        )
        try:
            self.assertEqual(1, mount.document_count)
            self.assertTrue(mount.index_path.is_file())
            self.assertEqual(self.dnd.resolve(), mount.corpus_root)
            hits = mount.services.vfs.v_grep("/", "DND_ALPHA")
            self.assertEqual(1, len(hits.hits))
        finally:
            mount.close()

    def test_close_removes_index_but_not_corpus_files(self) -> None:
        mount = mount_corpus(
            self._corpus("openssh"),
            self.knowledge_base,
            run_mode=RunMode.DRY_RUN,
            env_file_path=self.base / "missing.env",
        )
        index_dir = mount.index_dir
        before = {path: path.read_bytes() for path in self.openssh.rglob("*") if path.is_file()}

        mount.close()

        self.assertFalse(index_dir.exists())
        after = {path: path.read_bytes() for path in self.openssh.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertTrue(mount.closed)

    def test_close_is_idempotent(self) -> None:
        mount = mount_corpus(
            self._corpus("dnd"),
            self.knowledge_base,
            run_mode=RunMode.DRY_RUN,
            env_file_path=self.base / "missing.env",
        )
        mount.close()
        mount.close()
        self.assertTrue(mount.closed)

    def test_mount_isolates_selected_corpus(self) -> None:
        mount = mount_corpus(
            self._corpus("dnd"),
            self.knowledge_base,
            run_mode=RunMode.DRY_RUN,
            env_file_path=self.base / "missing.env",
        )
        try:
            self.assertEqual(0, len(mount.services.vfs.v_grep("/", "SSH_SECRET").hits))
            with self.assertRaises(Exception):
                mount.services.vfs.v_cat("/openssh/rules.md")
        finally:
            mount.close()


if __name__ == "__main__":
    unittest.main()
