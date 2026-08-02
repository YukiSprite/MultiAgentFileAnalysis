"""Safe offline CHM extraction and normalization into indexed Markdown."""

from __future__ import annotations

import hashlib
import html as html_module
import json
import os
import posixpath
import re
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

import yaml

from multi_agent_file_analysis.core import PageIndexError
from multi_agent_file_analysis.index import PageIndexLoader

from .html_markdown import HtmlToMarkdownConverter

_HTML_SUFFIXES = {".htm", ".html"}
_ASSET_SUFFIXES = {".bmp", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".webp"}
_ACTIVE_ASSET_SUFFIXES = {".svg"}
_EXTERNAL_SCHEMES = {"http", "https", "mailto"}
_BLOCKED_SCHEMES = {"data", "javascript", "vbscript"}


@dataclass(slots=True)
class ChmImportLimits:
    """Budgets enforced while handling an untrusted compiled help archive."""

    max_archive_bytes: int = 512 * 1024 * 1024
    max_extracted_bytes: int = 2 * 1024 * 1024 * 1024
    max_extracted_files: int = 50_000
    max_page_bytes: int = 10 * 1024 * 1024
    extraction_timeout_seconds: int = 180

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if value <= 0:
                raise PageIndexError(f"{name} must be greater than zero")


@dataclass(slots=True, frozen=True)
class ChmTocEntry:
    """One sitemap item parsed from a CHM .hhc table of contents."""

    title: str
    local: str
    depth: int
    breadcrumbs: tuple[str, ...]


@dataclass(slots=True)
class ChmImportResult:
    """Summary returned after conversion and index publication."""

    archive_path: Path
    output_directory: Path
    index_path: Path
    manifest_path: Path
    archive_sha256: str
    pages_converted: int
    assets_copied: int
    toc_entries: int
    unique_toc_pages: int
    missing_toc_pages: int
    skipped_pages: int
    indexed_documents: int
    warnings: list[str] = field(default_factory=list)
    cache_hit: bool = False


class _HhcParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[ChmTocEntry] = []
        self._depth = 0
        self._object: dict[str, str] | None = None
        self._object_depth = 0
        self._breadcrumbs: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        lowered = tag.casefold()
        if lowered == "ul":
            self._depth += 1
            return
        if lowered == "object":
            self._object = {}
            self._object_depth = max(0, self._depth - 1)
            return
        if lowered == "param" and self._object is not None:
            values = {key.casefold(): value or "" for key, value in attrs}
            name = values.get("name", "").casefold()
            value = values.get("value", "")
            if name and value:
                self._object[name] = value

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered == "object" and self._object is not None:
            self._finish_object()
            return
        if lowered == "ul":
            self._depth = max(0, self._depth - 1)

    def close(self) -> None:
        if self._object is not None:
            self._finish_object()
        super().close()

    def _finish_object(self) -> None:
        values = self._object or {}
        self._object = None
        title = " ".join(values.get("name", "").split())
        local = values.get("local", "").strip()
        if not title:
            return
        depth = self._object_depth
        if len(self._breadcrumbs) <= depth:
            self._breadcrumbs.extend("" for _ in range(depth + 1 - len(self._breadcrumbs)))
        self._breadcrumbs[depth] = title
        del self._breadcrumbs[depth + 1 :]
        breadcrumbs = tuple(item for item in self._breadcrumbs if item)
        self.entries.append(
            ChmTocEntry(
                title=title,
                local=local,
                depth=depth,
                breadcrumbs=breadcrumbs,
            )
        )


class ChmExtractor:
    """Run extract_chmLib without a shell and enforce bounded output."""

    def __init__(
        self,
        binary: str = "extract_chmLib",
        limits: ChmImportLimits | None = None,
    ) -> None:
        self._binary = binary
        self._limits = limits or ChmImportLimits()
        self._limits.validate()

    def extract(self, archive: Path, destination: Path) -> tuple[int, int]:
        archive = archive.resolve()
        destination = destination.resolve()
        if not archive.is_file():
            raise PageIndexError(f"CHM archive not found: {archive}")
        if archive.stat().st_size > self._limits.max_archive_bytes:
            raise PageIndexError(
                f"CHM archive exceeds {self._limits.max_archive_bytes} bytes"
            )
        with archive.open("rb") as stream:
            if stream.read(4) != b"ITSF":
                raise PageIndexError(f"Not a CHM/ITSF archive: {archive}")
        if destination.exists() and any(destination.iterdir()):
            raise PageIndexError(f"Extraction directory is not empty: {destination}")
        destination.mkdir(parents=True, exist_ok=True)

        executable = self._resolve_binary()
        started = time.monotonic()
        with tempfile.TemporaryFile(mode="w+b") as log:
            process = subprocess.Popen(
                [executable, str(archive), str(destination)],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                shell=False,
                start_new_session=True,
            )
            violation: str | None = None
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed > self._limits.extraction_timeout_seconds:
                    violation = (
                        "CHM extraction exceeded "
                        f"{self._limits.extraction_timeout_seconds} seconds"
                    )
                    self._terminate(process)
                    break
                try:
                    file_count, total_bytes = self._measure_tree(destination)
                except Exception:
                    self._terminate(process)
                    process.wait()
                    raise
                if file_count > self._limits.max_extracted_files:
                    violation = (
                        f"CHM extraction exceeded {self._limits.max_extracted_files} files"
                    )
                    self._terminate(process)
                    break
                if total_bytes > self._limits.max_extracted_bytes:
                    violation = (
                        "CHM extraction exceeded "
                        f"{self._limits.max_extracted_bytes} bytes"
                    )
                    self._terminate(process)
                    break
                time.sleep(0.05)

            return_code = process.wait()
            if violation:
                raise PageIndexError(violation)
            if return_code != 0:
                log.seek(0, os.SEEK_END)
                length = log.tell()
                log.seek(max(0, length - 4096))
                tail = log.read().decode("utf-8", errors="replace").strip()
                raise PageIndexError(
                    f"CHM extraction failed with exit {return_code}: {tail}"
                )

        file_count, total_bytes = self._measure_tree(destination)
        if file_count > self._limits.max_extracted_files:
            raise PageIndexError(
                f"CHM extraction exceeded {self._limits.max_extracted_files} files"
            )
        if total_bytes > self._limits.max_extracted_bytes:
            raise PageIndexError(
                f"CHM extraction exceeded {self._limits.max_extracted_bytes} bytes"
            )
        return file_count, total_bytes

    def _resolve_binary(self) -> str:
        if "/" in self._binary:
            candidate = Path(self._binary).resolve()
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        resolved = shutil.which(self._binary)
        if not resolved:
            raise PageIndexError(
                f"CHM extractor not found: {self._binary}; install a package "
                "providing extract_chmLib (for example Ubuntu libchm-bin)"
            )
        return resolved

    def _measure_tree(self, root: Path) -> tuple[int, int]:
        files = 0
        total = 0
        for path in root.rglob("*"):
            if path.is_symlink():
                raise PageIndexError(f"Symlink rejected in extracted CHM: {path}")
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                raise PageIndexError(f"Extracted path escapes destination: {path}")
            if path.is_file():
                files += 1
                total += path.stat().st_size
        return files, total

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            process.kill()


class ChmImporter:
    """Convert one CHM archive into a versioned Markdown corpus and Page Index."""

    manifest_version = "3"

    def __init__(
        self,
        *,
        extractor: ChmExtractor | None = None,
        converter: HtmlToMarkdownConverter | None = None,
        limits: ChmImportLimits | None = None,
    ) -> None:
        self._limits = limits or ChmImportLimits()
        self._limits.validate()
        self._extractor = extractor or ChmExtractor(limits=self._limits)
        self._converter = converter or HtmlToMarkdownConverter()

    def import_archive(
        self,
        archive_path: Path,
        knowledge_base_root: Path,
        index_path: Path,
        *,
        mount_name: str | None = None,
        copy_assets: bool = True,
        force: bool = False,
    ) -> ChmImportResult:
        archive = archive_path.resolve()
        knowledge_root = knowledge_base_root.resolve()
        index_path = index_path.resolve()
        if not archive.is_file():
            raise PageIndexError(f"CHM archive not found: {archive}")
        archive_hash = self._sha256(archive)
        mount = self._safe_mount_name(mount_name or archive.stem)
        imports_root = knowledge_root / "chm_imports"
        output_directory = (imports_root / mount).resolve()
        knowledge_root.mkdir(parents=True, exist_ok=True)
        imports_root.mkdir(parents=True, exist_ok=True)
        if not output_directory.is_relative_to(imports_root.resolve()):
            raise PageIndexError(f"Invalid CHM mount name: {mount}")

        cached = self._cached_result(
            archive,
            archive_hash,
            output_directory,
            index_path,
            knowledge_root,
            copy_assets=copy_assets,
        )
        if cached and not force:
            return cached
        if output_directory.exists() and not force:
            raise PageIndexError(
                f"CHM output already exists: {output_directory}; use --force to replace it"
            )

        staging = Path(
            tempfile.mkdtemp(prefix=f".{mount}.staging-", dir=imports_root)
        ).resolve()
        warnings: list[str] = []
        try:
            with tempfile.TemporaryDirectory(prefix="mafa-chm-extract-") as temporary:
                extracted_root = Path(temporary).resolve()
                extracted_files, extracted_bytes = self._extractor.extract(
                    archive,
                    extracted_root,
                )
                stats = self._convert_extracted(
                    archive=archive,
                    archive_hash=archive_hash,
                    extracted_root=extracted_root,
                    output_root=staging,
                    copy_assets=copy_assets,
                    warnings=warnings,
                )
                stats["extracted_files"] = extracted_files
                stats["extracted_bytes"] = extracted_bytes
                manifest = {
                    "manifest_version": self.manifest_version,
                    "converter_version": self._converter.version,
                    "archive_name": archive.name,
                    "archive_sha256": archive_hash,
                    "mount_name": mount,
                    "copy_assets": copy_assets,
                    "max_page_bytes": self._limits.max_page_bytes,
                    **stats,
                    "warnings": warnings[:1000],
                }
                self._write_json(staging / "manifest.json", manifest)

            self._publish(staging, output_directory, force=force)
            index = PageIndexLoader.scan_directory(knowledge_root, index_path)
            manifest_path = output_directory / "manifest.json"
            return ChmImportResult(
                archive_path=archive,
                output_directory=output_directory,
                index_path=index_path,
                manifest_path=manifest_path,
                archive_sha256=archive_hash,
                pages_converted=int(stats["pages_converted"]),
                assets_copied=int(stats["assets_copied"]),
                toc_entries=int(stats["toc_entries"]),
                unique_toc_pages=int(stats["unique_toc_pages"]),
                missing_toc_pages=int(stats["missing_toc_pages"]),
                skipped_pages=int(stats["skipped_pages"]),
                indexed_documents=len(index.documents),
                warnings=warnings,
            )
        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise

    def _convert_extracted(
        self,
        *,
        archive: Path,
        archive_hash: str,
        extracted_root: Path,
        output_root: Path,
        copy_assets: bool,
        warnings: list[str],
    ) -> dict[str, int]:
        all_html_paths = sorted(
            (
                path
                for path in extracted_root.rglob("*")
                if path.is_file() and path.suffix.casefold() in _HTML_SUFFIXES
            ),
            key=lambda path: self._relative(path, extracted_root).casefold(),
        )
        html_paths = [
            path
            for path in all_html_paths
            if path.stat().st_size <= self._limits.max_page_bytes
        ]
        skipped_html_paths = [
            path
            for path in all_html_paths
            if path.stat().st_size > self._limits.max_page_bytes
        ]
        for path in skipped_html_paths:
            warnings.append(
                f"Skipped oversized HTML page: {self._relative(path, extracted_root)}"
            )
        page_outputs = self._build_output_map(html_paths, extracted_root)
        asset_paths = sorted(
            (
                path
                for path in extracted_root.rglob("*")
                if path.is_file() and path.suffix.casefold() in _ASSET_SUFFIXES
            ),
            key=lambda path: self._relative(path, extracted_root).casefold(),
        )
        asset_outputs = (
            {
                self._relative(path, extracted_root).casefold(): PurePosixPath(
                    self._relative(path, extracted_root)
                )
                for path in asset_paths
            }
            if copy_assets
            else {}
        )
        active_assets = [
            path
            for path in extracted_root.rglob("*")
            if path.is_file() and path.suffix.casefold() in _ACTIVE_ASSET_SUFFIXES
        ]
        if active_assets:
            warnings.append(
                f"Skipped {len(active_assets)} active SVG assets for safe rendering"
            )

        toc_entries = self._load_toc(extracted_root, warnings)
        toc_map: dict[str, list[str]] = {}
        unique_toc_pages: set[str] = set()
        missing_toc_pages: set[str] = set()
        for entry in toc_entries:
            local = self._normalize_toc_local(entry.local)
            if not local:
                continue
            key = local.casefold()
            unique_toc_pages.add(key)
            toc_map.setdefault(key, []).append(" / ".join(entry.breadcrumbs))
            if key not in page_outputs:
                missing_toc_pages.add(key)
        if missing_toc_pages:
            warnings.append(
                f"{len(missing_toc_pages)} unique TOC targets are absent from the archive"
            )

        skipped_pages = len(skipped_html_paths)
        pages_converted = 0
        for source_path in html_paths:
            relative = self._relative(source_path, extracted_root)
            output_relative = page_outputs[relative.casefold()]
            raw = source_path.read_bytes()
            decoded, encoding, replacement = decode_chm_text(raw)
            if replacement:
                warnings.append(f"Lossy decoding used for {relative}")
            title_fallback = source_path.stem
            toc_paths = list(dict.fromkeys(toc_map.get(relative.casefold(), [])))
            if toc_paths:
                title_fallback = toc_paths[0].rsplit(" / ", 1)[-1]
            title = self._converter.extract_title(decoded, title_fallback)

            def _rewrite(reference: str, image: bool) -> str | None:
                return self._rewrite_link(
                    reference,
                    image=image,
                    current_source=PurePosixPath(relative),
                    current_output=output_relative,
                    page_outputs=page_outputs,
                    asset_outputs=asset_outputs,
                )

            body = self._converter.convert(decoded, rewrite_link=_rewrite)
            metadata: dict[str, object] = {
                "title": title,
                "tags": ["chm", "imported-help"],
                "source_format": "chm",
                "source_archive": archive.name,
                "archive_sha256": archive_hash,
                "chm_inner_path": "/" + relative,
                "source_encoding": encoding,
                "converter_version": self._converter.version,
            }
            if toc_paths:
                metadata["toc_paths"] = toc_paths[:20]
            content = self._render_page(metadata, title, body)
            target = (output_root / str(output_relative)).resolve()
            if not target.is_relative_to(output_root):
                raise PageIndexError(f"Converted page escapes output root: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            pages_converted += 1

        assets_copied = 0
        if copy_assets:
            for source_path in asset_paths:
                relative = self._relative(source_path, extracted_root)
                target = (output_root / relative).resolve()
                if not target.is_relative_to(output_root):
                    raise PageIndexError(f"Asset escapes output root: {relative}")
                if source_path.stat().st_size > self._limits.max_page_bytes:
                    warnings.append(f"Skipped oversized asset: {relative}")
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_path, target)
                assets_copied += 1

        contents = self._render_contents(
            archive=archive,
            archive_hash=archive_hash,
            entries=toc_entries,
            page_outputs=page_outputs,
            missing=missing_toc_pages,
        )
        (output_root / "CONTENTS.md").write_text(contents, encoding="utf-8")
        return {
            "pages_converted": pages_converted,
            "assets_copied": assets_copied,
            "toc_entries": len(toc_entries),
            "unique_toc_pages": len(unique_toc_pages),
            "missing_toc_pages": len(missing_toc_pages),
            "skipped_pages": skipped_pages,
        }

    def _load_toc(
        self,
        extracted_root: Path,
        warnings: list[str],
    ) -> list[ChmTocEntry]:
        entries: list[ChmTocEntry] = []
        toc_paths = sorted(
            path
            for path in extracted_root.rglob("*")
            if path.is_file() and path.suffix.casefold() == ".hhc"
        )
        for toc_path in toc_paths:
            if toc_path.stat().st_size > self._limits.max_page_bytes:
                warnings.append(
                    f"Skipped oversized TOC: {self._relative(toc_path, extracted_root)}"
                )
                continue
            decoded, _, replacement = decode_chm_text(toc_path.read_bytes())
            if replacement:
                warnings.append(f"Lossy decoding used for TOC {toc_path.name}")
            entries.extend(parse_chm_toc(decoded))
        if not entries:
            warnings.append("No usable .hhc table of contents was found")
        return entries

    @staticmethod
    def _build_output_map(
        html_paths: list[Path],
        extracted_root: Path,
    ) -> dict[str, PurePosixPath]:
        outputs: dict[str, PurePosixPath] = {}
        used: set[str] = set()
        for path in html_paths:
            relative = ChmImporter._relative(path, extracted_root)
            candidate = PurePosixPath(relative).with_suffix(".md")
            if str(candidate).casefold() in used:
                suffix = hashlib.sha1(relative.encode("utf-8")).hexdigest()[:8]
                candidate = candidate.with_name(f"{candidate.stem}-{suffix}.md")
            used.add(str(candidate).casefold())
            outputs[relative.casefold()] = candidate
        return outputs

    def _rewrite_link(
        self,
        reference: str,
        *,
        image: bool,
        current_source: PurePosixPath,
        current_output: PurePosixPath,
        page_outputs: dict[str, PurePosixPath],
        asset_outputs: dict[str, PurePosixPath],
    ) -> str | None:
        reference = html_module.unescape(reference).strip()
        if not reference:
            return None
        lowered = reference.casefold()
        if lowered.startswith("mk:@msitstore:") or lowered.startswith("ms-its:"):
            reference = reference.split("::", 1)[-1]
        parsed = urlsplit(reference)
        scheme = parsed.scheme.casefold()
        if scheme in _BLOCKED_SCHEMES:
            return None
        if scheme in _EXTERNAL_SCHEMES:
            return None if image else reference
        if scheme and len(scheme) > 1:
            return None
        if not parsed.path and parsed.fragment:
            return "#" + parsed.fragment

        decoded_path = unquote(parsed.path).replace("\\", "/")
        if decoded_path.startswith("/"):
            combined = PurePosixPath(decoded_path.lstrip("/"))
        else:
            combined = current_source.parent / decoded_path
        normalized = self._normalize_posix(combined)
        if normalized is None:
            return None
        key = str(normalized).casefold()
        output = asset_outputs.get(key) if image else page_outputs.get(key)
        if output is None and not image:
            suffix = normalized.suffix.casefold()
            if suffix in _HTML_SUFFIXES:
                output = normalized.with_suffix(".md")
        if output is None and image:
            output = asset_outputs.get(key)
        if output is None:
            return None

        relative = posixpath.relpath(str(output), str(current_output.parent))
        relative = relative.replace(" ", "%20").replace("(", "%28").replace(")", "%29")
        if parsed.query:
            relative += "?" + parsed.query
        if parsed.fragment:
            relative += "#" + parsed.fragment
        return relative

    def _render_contents(
        self,
        *,
        archive: Path,
        archive_hash: str,
        entries: list[ChmTocEntry],
        page_outputs: dict[str, PurePosixPath],
        missing: set[str],
    ) -> str:
        metadata = {
            "title": f"{archive.stem} contents",
            "tags": ["chm", "table-of-contents"],
            "source_format": "chm",
            "source_archive": archive.name,
            "archive_sha256": archive_hash,
            "converter_version": self._converter.version,
        }
        lines = [
            "# CHM Table of Contents",
            "",
            f"Source archive: `{archive.name}`",
            "",
        ]
        for entry in entries:
            local = self._normalize_toc_local(entry.local)
            key = local.casefold() if local else ""
            indent = "  " * min(entry.depth, 20)
            if not local:
                lines.append(f"{indent}- {entry.title}")
                continue
            target = page_outputs.get(key)
            if target:
                fragment = ""
                if "#" in entry.local:
                    fragment = "#" + entry.local.split("#", 1)[1]
                destination = str(target).replace(" ", "%20") + fragment
                lines.append(f"{indent}- [{entry.title}]({destination})")
            else:
                marker = " missing" if key in missing else " unavailable"
                lines.append(f"{indent}- {entry.title} _[{marker.strip()}]_")
        body = "\n".join(lines).strip() + "\n"
        return self._render_page(metadata, "CHM Table of Contents", body)

    @staticmethod
    def _render_page(metadata: dict[str, object], title: str, body: str) -> str:
        frontmatter = yaml.safe_dump(
            metadata,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ).strip()
        body = body.strip()
        first_content = next((line.strip() for line in body.splitlines() if line.strip()), "")
        if not first_content.startswith("#"):
            body = f"# {title}\n\n{body}"
        return f"---\n{frontmatter}\n---\n\n{body}\n"

    def _cached_result(
        self,
        archive: Path,
        archive_hash: str,
        output_directory: Path,
        index_path: Path,
        knowledge_root: Path,
        *,
        copy_assets: bool,
    ) -> ChmImportResult | None:
        manifest_path = output_directory / "manifest.json"
        if not manifest_path.is_file():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if (
            manifest.get("archive_sha256") != archive_hash
            or manifest.get("archive_name") != archive.name
            or manifest.get("converter_version") != self._converter.version
            or manifest.get("manifest_version") != self.manifest_version
            or manifest.get("copy_assets") != copy_assets
            or manifest.get("max_page_bytes") != self._limits.max_page_bytes
        ):
            return None
        index = PageIndexLoader.scan_directory(knowledge_root, index_path)
        return ChmImportResult(
            archive_path=archive,
            output_directory=output_directory,
            index_path=index_path,
            manifest_path=manifest_path,
            archive_sha256=archive_hash,
            pages_converted=int(manifest.get("pages_converted", 0)),
            assets_copied=int(manifest.get("assets_copied", 0)),
            toc_entries=int(manifest.get("toc_entries", 0)),
            unique_toc_pages=int(manifest.get("unique_toc_pages", 0)),
            missing_toc_pages=int(manifest.get("missing_toc_pages", 0)),
            skipped_pages=int(manifest.get("skipped_pages", 0)),
            indexed_documents=len(index.documents),
            warnings=[str(item) for item in manifest.get("warnings", [])],
            cache_hit=True,
        )

    @staticmethod
    def _publish(staging: Path, destination: Path, *, force: bool) -> None:
        if not destination.exists():
            staging.rename(destination)
            return
        if not force:
            raise PageIndexError(f"CHM output already exists: {destination}")
        backup = destination.with_name(
            f".{destination.name}.backup-{uuid.uuid4().hex[:8]}"
        )
        destination.rename(backup)
        try:
            staging.rename(destination)
        except Exception:
            backup.rename(destination)
            raise
        shutil.rmtree(backup)

    @staticmethod
    def _safe_mount_name(value: str) -> str:
        normalized = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE).strip(".-")
        if not normalized or normalized in {".", ".."}:
            raise PageIndexError(f"Invalid CHM mount name: {value}")
        return normalized

    @staticmethod
    def _relative(path: Path, root: Path) -> str:
        return path.relative_to(root).as_posix()

    @staticmethod
    def _normalize_toc_local(value: str) -> str:
        path = value.split("#", 1)[0].split("?", 1)[0]
        path = unquote(path).replace("\\", "/").lstrip("/")
        normalized = ChmImporter._normalize_posix(PurePosixPath(path))
        return str(normalized) if normalized else ""

    @staticmethod
    def _normalize_posix(path: PurePosixPath) -> PurePosixPath | None:
        parts: list[str] = []
        for part in path.parts:
            if part in {"", ".", "/"}:
                continue
            if part == "..":
                if not parts:
                    return None
                parts.pop()
                continue
            if "\x00" in part:
                return None
            parts.append(part)
        return PurePosixPath(*parts) if parts else None

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def decode_chm_text(raw: bytes) -> tuple[str, str, bool]:
    """Decode a CHM text member using BOM/meta hints and conservative fallbacks."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig", False
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
        return raw.decode(encoding), encoding, False

    head = raw[:16_384].decode("ascii", errors="ignore")
    match = re.search(
        r"charset\s*=\s*['\"]?([A-Za-z0-9._-]+)",
        head,
        flags=re.IGNORECASE,
    )
    declared = match.group(1).casefold() if match else None
    aliases = {
        "gb2312": "gb18030",
        "gb_2312-80": "gb18030",
        "gbk": "gb18030",
        "x-gbk": "gb18030",
    }
    candidates: list[str] = []
    for candidate in (
        aliases.get(declared or "", declared),
        "utf-8",
        "gb18030",
        "big5",
        "windows-1252",
    ):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    for encoding in candidates:
        try:
            return raw.decode(encoding), encoding, False
        except (LookupError, UnicodeDecodeError):
            continue
    fallback = aliases.get(declared or "", declared) or "utf-8"
    try:
        return raw.decode(fallback, errors="replace"), fallback, True
    except LookupError:
        return raw.decode("utf-8", errors="replace"), "utf-8", True


def parse_chm_toc(content: str) -> list[ChmTocEntry]:
    """Parse WinHelp sitemap HTML while tolerating omitted closing LI tags."""
    parser = _HhcParser()
    parser.feed(content)
    parser.close()
    return parser.entries
