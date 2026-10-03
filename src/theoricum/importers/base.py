"""Importer protocol and helpers shared by every question source format."""

import hashlib
import html
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol

from theoricum.models import PackMeta, QuestionData
from theoricum.topics import normalize_text


class PackError(Exception):
    """A source that cannot be imported at all. The message is shown to the user (Spanish)."""


@dataclass(slots=True)
class ImportResult:
    meta: PackMeta
    questions: list[QuestionData] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ImportContext:
    questions_dir: Path
    path: Path

    @property
    def rel_path(self) -> str:
        return self.path.relative_to(self.questions_dir).as_posix()

    def file_ref(self, relative_to_source: str) -> str | None:
        """Build a `file:` image ref for a path relative to the source file, or None if it escapes."""
        candidate = (self.path.parent / relative_to_source).resolve()
        try:
            rel = candidate.relative_to(self.questions_dir.resolve())
        except ValueError:
            return None
        return "file:" + rel.as_posix()


class Importer(Protocol):
    kind: str

    def detect(self, path: Path) -> bool:
        """Cheap check: does this file belong to this importer?"""
        ...

    def related_files(self, path: Path) -> list[Path]:
        """Extra files whose changes must trigger a re-import (e.g. sidecars)."""
        ...

    def load(self, ctx: ImportContext) -> ImportResult: ...


def sidecar_path(path: Path) -> Path:
    """Optional per-source settings file: same file name plus `.toml` (e.g. `deck.apkg.toml`)."""
    return path.with_name(path.name + ".toml")


# --- HTML helpers (Anki fields, scraped pages) -------------------------------------------------

_BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_BLOCK_END_RE = re.compile(r"</\s*(?:p|div|li|h[1-6]|tr)\s*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_SOUND_RE = re.compile(r"\[sound:[^\]]*\]")
_IMG_SRC_RE = re.compile(
    r"""<img\b[^>]*?\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE
)
_SPACES_RE = re.compile(r"[ \t\r\f\v]+")


def html_to_text(value: str) -> str:
    """Convert a small HTML fragment to plain text, keeping line breaks."""
    value = _SOUND_RE.sub("", value)
    value = _BR_RE.sub("\n", value)
    value = _BLOCK_END_RE.sub("\n", value)
    value = _TAG_RE.sub("", value)
    value = html.unescape(value).replace("\xa0", " ")
    lines = [_SPACES_RE.sub(" ", line).strip() for line in value.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def image_sources(value: str) -> list[str]:
    """All `<img src>` values of an HTML fragment, unescaped, in order."""
    return [
        html.unescape(next(g for g in m.groups() if g is not None))
        for m in _IMG_SRC_RE.finditer(value)
    ]


# --- Normalization ------------------------------------------------------------------------------


def _dedup_text(value: str) -> str:
    value = re.sub(r"[^\w\s]", " ", normalize_text(value))
    return " ".join(value.split())


def dedup_key(text: str, options: tuple[str, ...] | list[str]) -> str:
    """Identify the same question across sources (accents, punctuation and option order ignored)."""
    parts = [_dedup_text(text), *sorted(_dedup_text(o) for o in options)]
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()[:20]


def strip_number_prefix(value: str) -> str:
    """Remove a leading enumeration such as `12. `, `A) ` or `b.- `."""
    return re.sub(r"^\s*(?:\d+|[A-Da-d])\s*[.)\-:]+\s+", "", value, count=1).strip()


def safe_member_name(name: str) -> bool:
    """A media file name must be a single path component (prevents path traversal)."""
    if not name or name in {".", ".."} or "\x00" in name:
        return False
    return "/" not in name and "\\" not in name and PurePosixPath(name).name == name
