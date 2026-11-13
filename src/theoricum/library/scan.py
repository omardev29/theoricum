"""Discover question sources inside the questions folder."""

import hashlib
import os
from collections.abc import Sequence
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
    root: Path  # the questions folder that holds it (keys and image refs are relative to it)


@dataclass(slots=True)
class ScanResult:
    sources: list[SourceFile] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    shadowed: list[tuple[str, Path]] = field(default_factory=list)  # (rel, hidden copy's folder)


def as_folders(questions_dirs: Path | Sequence[Path]) -> tuple[Path, ...]:
    return (questions_dirs,) if isinstance(questions_dirs, Path) else tuple(questions_dirs)


def _cache_salt() -> str:
    topics = resources.files("theoricum.data").joinpath("topics.toml").read_bytes()
    return hashlib.sha1(topics + str(IMPORTER_VERSION).encode()).hexdigest()[:8]


def fingerprint(path: Path, related: list[Path]) -> str:
    parts = [_cache_salt()]
    for p in (path, *related):
        st = p.stat()
        parts.append(f"{p.name}:{st.st_size}:{st.st_mtime_ns}")
    return "|".join(parts)


def _candidates(questions_dir: Path) -> list[Path]:
    found: list[Path] = []
    for root, dirs, files in os.walk(questions_dir):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        found.extend(
            Path(root) / name
            for name in sorted(files)
            if not name.startswith(".") and Path(name).suffix.lower() in CANDIDATE_SUFFIXES
        )
    return found


def scan(questions_dirs: Path | Sequence[Path], importers: list[Importer]) -> ScanResult:
    """Walk the folders (skipping hidden entries) and match each candidate file to an importer.

    With several folders, a relative path always means the file of the first folder that has
    it: the copies in later folders are listed in `shadowed` and ignored."""
    result = ScanResult()
    seen: set[str] = set()  # relative paths already provided by an earlier folder
    for questions_dir in as_folders(questions_dirs):
        if not questions_dir.is_dir():
            continue
        here: set[str] = set()
        claimed: set[Path] = set()
        unmatched: list[Path] = []
        for path in _candidates(questions_dir):
            rel = path.relative_to(questions_dir).as_posix()
            if rel in seen:
                result.shadowed.append((rel, questions_dir))
                continue
            here.add(rel)
            importer = next((imp for imp in importers if _safe_detect(imp, path)), None)
            if importer is None:
                unmatched.append(path)
                continue
            related = [p for p in importer.related_files(path) if p.is_file()]
            claimed.update(related)
            here.update(p.relative_to(questions_dir).as_posix() for p in related)
            result.sources.append(
                SourceFile(
                    path=path,
                    rel=rel,
                    importer=importer,
                    fingerprint=fingerprint(path, related),
                    root=questions_dir,
                )
            )
        result.ignored.extend(
            p.relative_to(questions_dir).as_posix() for p in unmatched if p not in claimed
        )
        seen |= here
    return result


def _safe_detect(importer: Importer, path: Path) -> bool:
    try:
        return importer.detect(path)
    except OSError:
        return False
