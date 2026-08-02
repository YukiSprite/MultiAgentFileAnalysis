"""Deterministic HTML-to-Markdown normalization for extracted help pages."""

from __future__ import annotations

import re
from collections.abc import Callable

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from lxml import etree
from lxml import html as lxml_html

LinkRewriter = Callable[[str, bool], str | None]

_SKIPPED_TAGS = {
    "applet",
    "embed",
    "head",
    "iframe",
    "link",
    "meta",
    "noscript",
    "object",
    "script",
    "style",
}


class HtmlToMarkdownConverter:
    """Convert legacy and Microsoft Word HTML into retrieval-friendly GFM."""

    version = "bs4-lxml-gfm-5"

    def convert(
        self,
        html: str,
        *,
        rewrite_link: LinkRewriter | None = None,
    ) -> str:
        soup = BeautifulSoup(html, "lxml")
        for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
            comment.extract()
        for tag in soup.find_all(True):
            # `decompose()` clears descendants too, but BeautifulSoup's original
            # ResultSet still contains those now-detached Tag objects.  Their
            # `attrs` value is None, so calling `get()` on a later descendant
            # would fail for pages with a hidden parent element.
            if tag.attrs is None:
                continue
            style = str(tag.get("style") or "").replace(" ", "").casefold()
            if tag.has_attr("hidden") or any(
                marker in style
                for marker in ("display:none", "visibility:hidden")
            ):
                tag.decompose()

        root = soup.body or soup
        try:
            markdown = self._render_children(root, rewrite_link=rewrite_link)
        except RecursionError:
            # Malformed legacy pages can contain hundreds of unclosed, nested
            # layout wrappers.  These tags are transparent to this renderer,
            # so strip them with libxml2 and retry without changing text or
            # semantic elements such as headings, tables, lists, and links.
            flattened = self._flatten_layout_wrappers(soup)
            root = flattened.body or flattened
            try:
                markdown = self._render_children(root, rewrite_link=rewrite_link)
            except RecursionError:
                # Preserve retrievable source text even if a hostile page uses
                # pathological nesting in semantic tags too.
                markdown = self._plain_text(root)
        markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
        markdown = re.sub(r"(?<=\S)\*\*\*\*(?=\S)", "** **", markdown)
        markdown = re.sub(r"[ \t]+\n", "\n", markdown)
        markdown = re.sub(r"\n{3,}", "\n\n", markdown)
        return markdown.strip() + "\n"

    @staticmethod
    def _flatten_layout_wrappers(soup: BeautifulSoup) -> BeautifulSoup:
        parser = lxml_html.HTMLParser(
            recover=True,
            no_network=True,
            huge_tree=True,
        )
        document = lxml_html.document_fromstring(soup.decode(), parser=parser)
        etree.strip_tags(document, "main", "div", "span", "font", "center")
        serialized = lxml_html.tostring(document, encoding="unicode")
        return BeautifulSoup(serialized, "lxml")

    @classmethod
    def _plain_text(cls, node: Tag | BeautifulSoup) -> str:
        return "\n\n".join(
            text
            for item in node.stripped_strings
            if (text := cls._normalize_text(str(item)).strip())
        )

    @staticmethod
    def extract_title(html: str, fallback: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        if soup.title:
            title = " ".join(soup.title.get_text(" ", strip=True).split())
            if title:
                return title
        for heading in soup.find_all(["h1", "h2", "h3"]):
            title = " ".join(heading.get_text(" ", strip=True).split())
            if title:
                return title
        return fallback

    def _render_children(
        self,
        node: Tag | BeautifulSoup,
        *,
        rewrite_link: LinkRewriter | None,
    ) -> str:
        return "".join(
            self._render(child, rewrite_link=rewrite_link)
            for child in node.children
        )

    def _render(
        self,
        node: Tag | NavigableString,
        *,
        rewrite_link: LinkRewriter | None,
    ) -> str:
        if isinstance(node, NavigableString):
            return self._normalize_text(str(node))
        if not isinstance(node, Tag):
            return ""

        name = node.name.casefold()
        if name in _SKIPPED_TAGS:
            return ""
        if name == "br":
            return "  \n"
        if name == "hr":
            return "\n\n---\n\n"
        if name == "table":
            return "\n\n" + self._table_to_markdown(node) + "\n\n"
        if name == "pre":
            content = node.get_text("", strip=False).strip("\n")
            fence = "````" if "```" in content else "```"
            return f"\n\n{fence}\n{content}\n{fence}\n\n"
        if name == "code":
            content = node.get_text("", strip=False).strip()
            fence = "``" if "`" in content else "`"
            return f"{fence}{content}{fence}" if content else ""
        if name in {"ul", "ol"}:
            return self._render_list(node, rewrite_link=rewrite_link)
        if name == "blockquote":
            content = self._render_children(
                node,
                rewrite_link=rewrite_link,
            ).strip()
            compacted: list[str] = []
            for line in content.splitlines():
                if not line.strip() and compacted and not compacted[-1].strip():
                    continue
                compacted.append(line)
            quoted = "\n".join(
                f"> {line}" if line else ">" for line in compacted
            )
            return f"\n\n{quoted}\n\n"

        content = self._render_children(node, rewrite_link=rewrite_link)
        stripped = content.strip()
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            if not stripped:
                return ""
            level = int(name[1])
            title = self._inline(stripped)
            return f"\n\n{'#' * level} {title}\n\n"
        if name in {"p", "article", "section"}:
            return f"\n\n{stripped}\n\n" if stripped else ""
        if name in {"strong", "b"}:
            return f"**{stripped}**" if stripped else ""
        if name in {"em", "i"}:
            return f"*{stripped}*" if stripped else ""
        if name == "a":
            href = str(node.get("href") or "").strip()
            label = stripped or href
            if not href:
                return label
            destination = rewrite_link(href, False) if rewrite_link else href
            if not destination:
                return label
            return f"[{label}]({destination})"
        if name == "img":
            source = str(node.get("src") or "").strip()
            if not source:
                return ""
            destination = rewrite_link(source, True) if rewrite_link else source
            if not destination:
                return ""
            alt = str(node.get("alt") or node.get("title") or "image").strip()
            return f"![{self._escape_label(alt)}]({destination})"
        if name == "dt":
            return f"\n\n**{stripped}**\n" if stripped else ""
        if name == "dd":
            return f": {stripped}\n" if stripped else ""
        if name in {"body", "html", "main", "div", "span", "font", "center"}:
            return content
        return content

    def _render_list(
        self,
        node: Tag,
        *,
        rewrite_link: LinkRewriter | None,
        depth: int = 0,
    ) -> str:
        ordered = node.name.casefold() == "ol"
        lines: list[str] = []
        index = 1
        for item in node.find_all("li", recursive=False):
            inline_parts: list[str] = []
            nested_lists: list[Tag] = []
            for child in item.children:
                if isinstance(child, Tag) and child.name.casefold() in {"ul", "ol"}:
                    nested_lists.append(child)
                else:
                    inline_parts.append(
                        self._render(child, rewrite_link=rewrite_link)
                    )
            text = self._inline("".join(inline_parts).strip())
            marker = f"{index}." if ordered else "-"
            if text:
                lines.append(f"{'  ' * depth}{marker} {text}")
            for nested in nested_lists:
                rendered = self._render_list(
                    nested,
                    rewrite_link=rewrite_link,
                    depth=depth + 1,
                ).strip("\n")
                if rendered:
                    lines.extend(rendered.splitlines())
            index += 1
        return "\n\n" + "\n".join(lines) + "\n\n" if lines else ""

    def _table_to_markdown(self, table: Tag) -> str:
        raw_rows: list[list[tuple[str, int, int]]] = []
        for row in table.find_all("tr"):
            if row.find_parent("table") is not table:
                continue
            cells: list[tuple[str, int, int]] = []
            for cell in row.find_all(["th", "td"], recursive=False):
                if cell.find_parent("table") is not table:
                    continue
                text = self._table_cell_text(cell)
                rowspan = self._positive_span(cell.get("rowspan"))
                colspan = self._positive_span(cell.get("colspan"))
                cells.append((text, rowspan, colspan))
            if cells:
                raw_rows.append(cells)

        if not raw_rows:
            text = self._table_cell_text(table)
            return text or "[empty table]"

        occupied: dict[tuple[int, int], str] = {}
        for row_index, cells in enumerate(raw_rows):
            column = 0
            for text, rowspan, colspan in cells:
                while (row_index, column) in occupied:
                    column += 1
                for row_offset in range(rowspan):
                    for column_offset in range(colspan):
                        occupied[(row_index + row_offset, column + column_offset)] = text
                column += colspan

        max_row = max(row for row, _ in occupied)
        max_column = max(column for _, column in occupied)
        rows = [
            [occupied.get((row, column), "") for column in range(max_column + 1)]
            for row in range(max_row + 1)
        ]
        while rows and not any(cell.strip() for cell in rows[0]):
            rows.pop(0)
        while rows and not any(cell.strip() for cell in rows[-1]):
            rows.pop()
        if not rows:
            return "[empty table]"

        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]

        rendered = [self._table_row(rows[0])]
        rendered.append("| " + " | ".join("---" for _ in range(width)) + " |")
        rendered.extend(self._table_row(row) for row in rows[1:])
        return "\n".join(rendered)

    @classmethod
    def _table_cell_text(cls, cell: Tag) -> str:
        line_break = "\ue000MAFA_TABLE_BREAK\ue001"
        for br in cell.find_all("br"):
            br.replace_with(line_break)
        text = cell.get_text(" ", strip=True)
        text = re.sub(r"[ \t\f\v]+", " ", text)
        text = re.sub(rf"\s*{re.escape(line_break)}\s*", "<br>", text)
        return text.strip()

    @staticmethod
    def _positive_span(value: object) -> int:
        try:
            return max(1, min(int(str(value or "1")), 100))
        except ValueError:
            return 1

    @staticmethod
    def _table_row(cells: list[str]) -> str:
        escaped = [
            cell.replace("\\", "\\\\").replace("|", "\\|")
            for cell in cells
        ]
        return "| " + " | ".join(escaped) + " |"

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = text.replace("\xa0", " ").replace("\u3000", " ")
        return re.sub(r"\s+", " ", text)

    @staticmethod
    def _inline(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _escape_label(text: str) -> str:
        return text.replace("[", "\\[").replace("]", "\\]")
