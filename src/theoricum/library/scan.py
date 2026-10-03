"""Discover question sources inside the questions folder."""

import hashlib
import os
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from theoricum.importers import IMPORTER_VERSION, Importer

CANDIDATE_SUFFIXES = {".json", ".toml", ".apkg", ".colpkg"}


@dataclass(frozen=True, slots=True)
class SourceFile:
    path: Path
    rel: str
    importer: Importer
    fingerprint: str


@dataclass(slots=True)
class ScanResult:
    sources: list[SourceFile] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)


def _cache_salt() -> str:
    topics = resources.files("theoricum.data").joinpath("topics.toml").read_bytes()
    return hashlib.sha1(topics + str(IMPORTER_VERSION).encode()).hexdigest()[:8]


def fingerprint(path: Path, related: list[Path]) -> str:
    parts = [_cache_salt()]
    for p in (path, *related):
        st = p.stat()
        parts.append(f"{p.name}:{st.st_size}:{st.st_mtime_ns}")
    return "|".join(parts)


def scan(questions_dir: Path, importers: list[Importer]) -> ScanResult:
    """Walk the folder (skipping hidden entries) and match each candidate file to an importer."""
    result = ScanResult()
    if not questions_dir.is_dir():
        return result
    candidates: list[Path] = []
    for root, dirs, files in os.walk(questions_dir):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        candidates.extend(
            Path(root) / name
            for name in sorted(files)
            if not name.startswith(".") and Path(name).suffix.lower() in CANDIDATE_SUFFIXES
        )

    claimed: set[Path] = set()
    unmatched: list[Path] = []
    for path in candidates:
        importer = next((imp for imp in importers if _safe_detect(imp, path)), None)
        if importer is None:
            unmatched.append(path)
            continue
        related = [p for p in importer.related_files(path) if p.is_file()]
        claimed.update(related)
        result.sources.append(
            SourceFile(
                path=path,
                rel=path.relative_to(questions_dir).as_posix(),
                importer=importer,
                fingerprint=fingerprint(path, related),
            )
        )
    result.ignored = [
        p.relative_to(questions_dir).as_posix() for p in unmatched if p not in claimed
    ]
    return result


def _safe_detect(importer: Importer, path: Path) -> bool:
    try:
        return importer.detect(path)
    except OSError:
        return False
