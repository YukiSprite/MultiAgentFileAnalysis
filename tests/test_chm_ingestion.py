from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from multi_agent_file_analysis.config import AppConfig
from multi_agent_file_analysis.ingestion import (
    ChmExtractor,
    ChmImporter,
    HtmlToMarkdownConverter,
    decode_chm_text,
    parse_chm_toc,
)
from multi_agent_file_analysis.core import PageIndexError
from multi_agent_file_analysis.index import PageIndexLoader, PageIndexRepository
from multi_agent_file_analysis.vfs import VirtualFileSystem


class _FixtureExtractor:
    def __init__(self) -> None:
        self.calls = 0

    def extract(self, archive: Path, destination: Path) -> tuple[int, int]:
        del archive
        self.calls += 1
        files = {
            "示例.hhc": self._toc().encode("gb18030"),
            "章节/规则.htm": self._page().encode("gb18030"),
            "images/map.png": b"not-a-real-png",
        }
        total = 0
        for relative, content in files.items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            total += len(content)
        return len(files), total

    @staticmethod
    def _toc() -> str:
        return """
        <ul><li><object type="text/sitemap">
          <param name="Name" value="规则书">
          <param name="Local" value="章节/规则.htm">
        </object>
        <ul><li><object type="text/sitemap">
          <param name="Name" value="缺失章节">
          <param name="Local" value="章节/缺失.htm">
        </object></ul></ul>
        """

    @staticmethod
    def _page() -> str:
        return """
        <html><head><meta charset="gb2312"><title>狂暴规则</title>
        <script>alert('never execute')</script></head><body>
        <h1>狂暴规则</h1>
        <p>狂暴期间，你不能施展法术。</p>
        <table>
          <tr><th rowspan="2">等级</th><th colspan="2">狂暴</th></tr>
          <tr><th>次数</th><th>伤害</th></tr>
          <tr><td>1</td><td>2</td><td>+2</td></tr>
        </table>
        <img src="../images/map.png" alt="地图">
        <img src="https://tracker.invalid/pixel.png" alt="远程跟踪图">
        <a href="javascript:alert(1)">危险链接</a>
        </body></html>
        """


class ChmIngestionTests(unittest.TestCase):
    def test_gb2312_alias_decodes_with_gb18030(self) -> None:
        raw = '<meta charset="gb2312"><p>中文规则</p>'.encode("gb18030")
        content, encoding, lossy = decode_chm_text(raw)
        self.assertIn("中文规则", content)
        self.assertEqual("gb18030", encoding)
        self.assertFalse(lossy)

    def test_hhc_parser_preserves_nested_breadcrumbs(self) -> None:
        entries = parse_chm_toc(_FixtureExtractor._toc())
        self.assertEqual(2, len(entries))
        self.assertEqual(("规则书",), entries[0].breadcrumbs)
        self.assertEqual(("规则书", "缺失章节"), entries[1].breadcrumbs)
        self.assertEqual(1, entries[1].depth)

    def test_hhc_folder_without_local_is_kept_as_breadcrumb(self) -> None:
        entries = parse_chm_toc(
            "<ul><li><object><param name='Name' value='第一章'></object>"
            "<ul><li><object><param name='Name' value='规则'>"
            "<param name='Local' value='rule.htm'></object></ul></ul>"
        )
        self.assertEqual(2, len(entries))
        self.assertEqual("", entries[0].local)
        self.assertEqual(("第一章", "规则"), entries[1].breadcrumbs)

    def test_word_table_is_rendered_as_gfm_with_spans_expanded(self) -> None:
        markdown = HtmlToMarkdownConverter().convert(_FixtureExtractor._page())
        self.assertIn("| 等级 | 狂暴 | 狂暴 |", markdown)
        self.assertIn("| 等级 | 次数 | 伤害 |", markdown)
        self.assertIn("| 1 | 2 | +2 |", markdown)
        self.assertNotIn("[TABLE]", markdown)
        self.assertNotIn("alert('never execute')", markdown)

    def test_table_escapes_pipes_and_preserves_cell_line_breaks(self) -> None:
        markdown = HtmlToMarkdownConverter().convert(
            "<table><tr><th>Name</th><th>Rule</th></tr>"
            "<tr><td>A|B</td><td>first<br>second</td></tr></table>"
        )
        self.assertIn("| A\\|B | first<br>second |", markdown)

    def test_hidden_parent_with_descendants_is_removed_safely(self) -> None:
        markdown = HtmlToMarkdownConverter().convert(
            "<div style='display: none'><span data-value='nested'>"
            "hidden rule</span></div><p>visible rule</p>"
        )

        self.assertNotIn("hidden rule", markdown)
        self.assertIn("visible rule", markdown)

    def test_deep_legacy_layout_wrappers_preserve_semantic_content(self) -> None:
        markdown = HtmlToMarkdownConverter().convert(
            "<div>" * 400
            + "<h2>Deep rule</h2>"
            + "<table><tr><th>Name</th><th>Value</th></tr>"
            + "<tr><td>AC</td><td>21</td></tr></table>"
            + "</div>" * 400
        )

        self.assertIn("## Deep rule", markdown)
        self.assertIn("| AC | 21 |", markdown)

    def test_extractor_rejects_non_chm_before_invoking_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "invalid.chm"
            archive.write_bytes(b"this is not an ITSF archive")
            with self.assertRaises(PageIndexError):
                ChmExtractor(binary="definitely-missing-extractor").extract(
                    archive,
                    root / "output",
                )

    def test_legacy_omitted_li_end_tags_remain_separate_items(self) -> None:
        markdown = HtmlToMarkdownConverter().convert(
            "<ul><li>第一项<li>第二项<li>第三项</ul>"
        )
        self.assertIn("- 第一项\n- 第二项\n- 第三项", markdown)

    def test_adjacent_bold_and_blockquote_spacing_are_normalized(self) -> None:
        markdown = HtmlToMarkdownConverter().convert(
            "<blockquote><p><b>中文</b><b>English</b></p>"
            "<ul><li>规则</li></ul></blockquote>"
        )
        self.assertIn("**中文** **English**", markdown)
        self.assertIn(">\n> - 规则", markdown)
        self.assertNotIn(">\n>\n>", markdown)

    def test_archive_becomes_indexed_markdown_with_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "book.chm"
            archive.write_bytes(b"ITSF fixture")
            knowledge_base = root / "knowledge_base"
            index_path = root / "page_index.yaml"
            extractor = _FixtureExtractor()
            importer = ChmImporter(extractor=extractor)  # type: ignore[arg-type]

            result = importer.import_archive(
                archive,
                knowledge_base,
                index_path,
                mount_name="book",
            )

            self.assertEqual(1, result.pages_converted)
            self.assertEqual(1, result.assets_copied)
            self.assertEqual(1, result.missing_toc_pages)
            self.assertEqual(2, result.indexed_documents)
            self.assertTrue((result.output_directory / "CONTENTS.md").is_file())
            converted = result.output_directory / "章节/规则.md"
            content = converted.read_text(encoding="utf-8")
            self.assertIn("archive_sha256:", content)
            self.assertIn("| 等级 | 狂暴 | 狂暴 |", content)
            self.assertIn("![地图](../images/map.png)", content)
            self.assertIn("危险链接", content)
            self.assertNotIn("javascript:", content)
            self.assertNotIn("tracker.invalid", content)

            index = PageIndexLoader().load(index_path)
            repository = PageIndexRepository(index, knowledge_base)
            virtual_path = "/chm_imports/book/章节/规则.md"
            node = repository.get_node(virtual_path)
            self.assertEqual("chm", node.metadata["source_format"])
            self.assertEqual("/章节/规则.htm", node.metadata["chm_inner_path"])
            self.assertEqual("gb18030", node.metadata["source_encoding"])
            self.assertIn("规则书", node.metadata["toc_paths"])
            source_document = next(
                document
                for document in index.documents
                if document.source == "chm_imports/book/章节/规则.md"
            )
            self.assertEqual("utf-8", source_document.encoding)

            vfs = VirtualFileSystem(
                repository,
                AppConfig(index_path, knowledge_base),
            )
            grep = vfs.v_grep("/", "不能施展法术")
            self.assertEqual(1, len(grep.hits))
            self.assertEqual(virtual_path, grep.hits[0].path)
            self.assertEqual(
                "狂暴期间，你不能施展法术。",
                vfs.verify_quote(
                    virtual_path,
                    "狂暴期间，你不能施展法术。",
                ).quote,
            )
            self.assertEqual(0, len(vfs.v_grep("/", "source_archive").hits))

            cached = importer.import_archive(
                archive,
                knowledge_base,
                index_path,
                mount_name="book",
            )
            self.assertTrue(cached.cache_hit)
            self.assertEqual(1, extractor.calls)

            without_assets = importer.import_archive(
                archive,
                knowledge_base,
                index_path,
                mount_name="book-no-assets",
                copy_assets=False,
            )
            self.assertEqual(0, without_assets.assets_copied)
            self.assertFalse(
                (without_assets.output_directory / "images/map.png").exists()
            )
            no_assets_content = (
                without_assets.output_directory / "章节/规则.md"
            ).read_text(encoding="utf-8")
            self.assertNotIn("![地图]", no_assets_content)


if __name__ == "__main__":
    unittest.main()
