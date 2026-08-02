"""Dynamic knowledge-corpus discovery and path isolation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from multi_agent_file_analysis.core import ConfigError

_CORPUS_MARKER = ".mafa-corpus.yaml"
_CORPUS_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_VERSION_SUFFIX = re.compile(
    r"(?i)(?:[._-]v?\d{4}(?:[._-]\d{1,2}){0,3})$"
)


@dataclass(slots=True, frozen=True)
class CorpusDefinition:
    """One discovered directory that can be mounted as the VFS root."""

    corpus_id: str
    name: str
    relative_path: Path
    description: str = ""
    discovery_source: str = "directory"

    def resolve_root(self, knowledge_base_root: Path) -> Path:
        """Resolve this corpus while preventing escape from the knowledge root."""
        knowledge_root = knowledge_base_root.resolve()
        if self.relative_path.is_absolute():
            raise ConfigError(
                f"Corpus {self.corpus_id} path must be relative: "
                f"{self.relative_path}"
            )
        unresolved = knowledge_root / self.relative_path
        if unresolved.is_symlink():
            raise ConfigError(
                f"Corpus {self.corpus_id} root must not be a symlink"
            )
        resolved = unresolved.resolve()
        if not resolved.is_relative_to(knowledge_root):
            raise ConfigError(
                f"Corpus {self.corpus_id} escapes the knowledge-base root"
            )
        return resolved


@dataclass(slots=True, frozen=True)
class CorpusCatalog:
    """Logical corpora dynamically discovered from the current filesystem."""

    corpora: tuple[CorpusDefinition, ...]

    @classmethod
    def discover(cls, knowledge_base_root: Path) -> CorpusCatalog:
        """Discover corpus boundaries without a central hard-coded registry.

        Discovery precedence for every top-level branch is:
        1. a local `.mafa-corpus.yaml` boundary;
        2. a CHM conversion `manifest.json` boundary;
        3. the top-level directory itself when it contains Markdown and no
           explicit boundaries were found below it.
        Once a boundary is found, nested content directories are not exposed as
        separate menu entries.
        """
        knowledge_root = knowledge_base_root.resolve()
        if not knowledge_root.is_dir():
            raise ConfigError(
                f"Knowledge-base root is not a directory: {knowledge_root}"
            )
        if knowledge_base_root.is_symlink():
            raise ConfigError("Knowledge-base root must not be a symlink")

        discovered: list[CorpusDefinition] = []
        for child in sorted(knowledge_root.iterdir(), key=lambda item: item.name):
            if (
                child.name.startswith(".")
                or child.is_symlink()
                or not child.is_dir()
            ):
                continue
            branch = cls._discover_boundaries(child, knowledge_root)
            if branch:
                discovered.extend(branch)
            elif cls._contains_markdown(child):
                discovered.append(
                    cls._directory_definition(child, knowledge_root)
                )

        discovered.sort(
            key=lambda corpus: (
                corpus.name.casefold(),
                corpus.relative_path.as_posix().casefold(),
            )
        )
        return cls(corpora=tuple(cls._make_ids_unique(discovered)))

    @classmethod
    def _discover_boundaries(
        cls,
        directory: Path,
        knowledge_root: Path,
    ) -> list[CorpusDefinition]:
        marker = directory / _CORPUS_MARKER
        if marker.is_file() and not marker.is_symlink():
            definition = cls._marker_definition(marker, directory, knowledge_root)
            return [definition] if cls._contains_markdown(directory) else []

        manifest = directory / "manifest.json"
        definition = cls._chm_definition(manifest, directory, knowledge_root)
        if definition is not None:
            return [definition] if cls._contains_markdown(directory) else []

        found: list[CorpusDefinition] = []
        for child in sorted(directory.iterdir(), key=lambda item: item.name):
            if (
                child.name.startswith(".")
                or child.is_symlink()
                or not child.is_dir()
            ):
                continue
            found.extend(cls._discover_boundaries(child, knowledge_root))
        return found

    @classmethod
    def _marker_definition(
        cls,
        marker: Path,
        directory: Path,
        knowledge_root: Path,
    ) -> CorpusDefinition:
        if marker.stat().st_size > 64 * 1024:
            raise ConfigError(f"Corpus marker is too large: {marker}")
        try:
            raw = yaml.safe_load(marker.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ConfigError(f"Invalid corpus marker {marker}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigError(f"Corpus marker must be a mapping: {marker}")

        name = " ".join(str(raw.get("name") or directory.name).split())
        corpus_id = str(raw.get("id") or "").strip()
        if corpus_id and not _CORPUS_ID.fullmatch(corpus_id):
            raise ConfigError(f"Invalid corpus id {corpus_id!r} in {marker}")
        if not corpus_id:
            corpus_id = cls._generated_id(name, directory, knowledge_root)
        description = " ".join(str(raw.get("description") or "").split())
        return CorpusDefinition(
            corpus_id=corpus_id,
            name=name or directory.name,
            relative_path=directory.relative_to(knowledge_root),
            description=description,
            discovery_source="marker",
        )

    @classmethod
    def _chm_definition(
        cls,
        manifest: Path,
        directory: Path,
        knowledge_root: Path,
    ) -> CorpusDefinition | None:
        if not manifest.is_file() or manifest.is_symlink():
            return None
        if manifest.stat().st_size > 1024 * 1024:
            return None
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            return None
        if not isinstance(raw, dict) or not {
            "archive_sha256",
            "pages_converted",
            "mount_name",
        }.issubset(raw):
            return None

        archive_name = str(raw.get("archive_name") or "").strip()
        archive_stem = Path(archive_name).stem if archive_name else ""
        friendly_name = _VERSION_SUFFIX.sub("", archive_stem).strip(" ._-")
        name = friendly_name or str(raw.get("mount_name") or directory.name)
        corpus_id = cls._generated_id(
            str(raw.get("mount_name") or name),
            directory,
            knowledge_root,
        )
        return CorpusDefinition(
            corpus_id=corpus_id,
            name=name,
            relative_path=directory.relative_to(knowledge_root),
            description=(
                f"由 {archive_name} 规范化得到的 CHM 知识库。"
                if archive_name
                else "自动发现的 CHM 知识库。"
            ),
            discovery_source="chm-manifest",
        )

    @classmethod
    def _directory_definition(
        cls,
        directory: Path,
        knowledge_root: Path,
    ) -> CorpusDefinition:
        name = directory.name.replace("_", " ")
        return CorpusDefinition(
            corpus_id=cls._generated_id(name, directory, knowledge_root),
            name=name,
            relative_path=directory.relative_to(knowledge_root),
            description="自动发现的 Markdown 知识库目录。",
            discovery_source="top-level-directory",
        )

    @staticmethod
    def _contains_markdown(directory: Path) -> bool:
        return any(
            path.is_file()
            and not path.is_symlink()
            and path.suffix.casefold() == ".md"
            for path in directory.rglob("*")
        )

    @staticmethod
    def _generated_id(
        value: str,
        directory: Path,
        knowledge_root: Path,
    ) -> str:
        slug = re.sub(r"[^a-z0-9_-]+", "-", value.casefold()).strip("-_")
        if not slug:
            relative = directory.relative_to(knowledge_root).as_posix()
            suffix = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:8]
            slug = f"corpus-{suffix}"
        if slug[0].isdigit():
            slug = "corpus-" + slug
        return slug[:64]

    @staticmethod
    def _make_ids_unique(
        corpora: list[CorpusDefinition],
    ) -> list[CorpusDefinition]:
        unique: list[CorpusDefinition] = []
        used: set[str] = set()
        for corpus in corpora:
            base = corpus.corpus_id
            candidate = base
            counter = 2
            while candidate.casefold() in used:
                suffix = f"-{counter}"
                candidate = base[: 64 - len(suffix)] + suffix
                counter += 1
            used.add(candidate.casefold())
            unique.append(
                corpus if candidate == base else replace(corpus, corpus_id=candidate)
            )
        return unique

    def available(
        self,
        knowledge_base_root: Path,
    ) -> list[tuple[CorpusDefinition, Path]]:
        """Resolve every discovered corpus for selection."""
        return [
            (corpus, corpus.resolve_root(knowledge_base_root))
            for corpus in self.corpora
        ]
