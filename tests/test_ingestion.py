from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from multi_agent_file_analysis.core import PageIndexError
from multi_agent_file_analysis.ingestion import (
    DocumentSource,
    KnowledgeBaseBuilder,
)
from multi_agent_file_analysis.index import PageIndexLoader, PageIndexRepository


class IngestionTests(unittest.TestCase):
    def test_windows_drive_paths_and_file_uris_are_local(self) -> None:
        self.assertEqual(
            Path("C:/docs/rule.md"),
            KnowledgeBaseBuilder._local_path("C:/docs/rule.md"),
        )
        with self.assertRaises(PageIndexError):
            KnowledgeBaseBuilder._local_path("https://example.com/rule.md")
        with self.assertRaises(PageIndexError):
            KnowledgeBaseBuilder._local_path("file://remote-host/rule.md")

    def test_local_markdown_is_ingested_and_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.md"
            source.write_text("# Service Rule\n\nExactSymbol=yes\n", encoding="utf-8")
            output_root = root / "kb"
            index_path = root / "page_index.yaml"
            builder = KnowledgeBaseBuilder(output_root, index_path)
            index = builder.build(
                [
                    DocumentSource(
                        uri=str(source),
                        title="Service Rule",
                        tags=["configuration"],
                        metadata={
                            "virtual_path": "/system/version/rule.md",
                            "version": "1.0",
                        },
                    )
                ]
            )
            self.assertEqual(1, len(index.documents))
            self.assertTrue(index_path.is_file())
            reloaded = PageIndexLoader().load(index_path)
            repository = PageIndexRepository(reloaded, output_root)
            resolved = repository.resolve_source_path(
                "/system/version/rule.md"
            )
            self.assertEqual("ExactSymbol=yes", resolved.read_text().splitlines()[2])


if __name__ == "__main__":
    unittest.main()
