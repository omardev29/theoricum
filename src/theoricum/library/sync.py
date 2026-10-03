"""Incremental synchronization of the questions folder into the SQLite content cache."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from theoricum.db.store import QuestionRow, Store
from theoricum.importers import ImportContext, Importer, PackError, default_importers
from theoricum.importers.base import dedup_key
from theoricum.library.scan import scan
from theoricum.models import PackMeta, QuestionData
from theoricum.topics import classify

ProgressCallback = Callable[[int, int, str], None]


@dataclass(slots=True)
class SyncReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.removed)


def resolve_row(question: QuestionData, meta: PackMeta) -> QuestionRow:
    return QuestionRow(
        key=question.key,
        text=question.text,
        options=question.options,
        answer=question.answer,
        explanation=question.explanation,
        image_ref=question.image_ref,
        topic=question.topic or meta.topic or classify(question.text, question.options),
        date=question.date or meta.date,
        tags=question.tags,
        source=question.source,
        dedup=dedup_key(question.text, question.options),
    )


def sync(
    store: Store,
    questions_dir: Path,
    *,
    force: bool = False,
    importers: list[Importer] | None = None,
    progress: ProgressCallback | None = None,
) -> SyncReport:
    """Bring the content cache in line with the folder. User history is never touched."""
    report = SyncReport()
    scanned = scan(questions_dir, importers or default_importers())
    report.ignored = scanned.ignored

    known = store.source_fingerprints()
    present = {s.rel for s in scanned.sources}
    report.removed = sorted(p for p in known if p not in present)
    if report.removed:
        store.delete_sources(report.removed)

    pending = [s for s in scanned.sources if force or known.get(s.rel) != s.fingerprint]
    report.unchanged = len(scanned.sources) - len(pending)
    for done, src in enumerate(pending):
        if progress:
            progress(done, len(pending), src.rel)
        (report.updated if src.rel in known else report.added).append(src.rel)
        try:
            result = src.importer.load(ImportContext(questions_dir=questions_dir, path=src.path))
        except PackError as exc:
            _store_error(store, src.rel, src.importer.kind, src.fingerprint, str(exc), report)
            continue
        except Exception as exc:  # A broken file must never stop the whole sync.
            _store_error(
                store,
                src.rel,
                src.importer.kind,
                src.fingerprint,
                f"error inesperado: {exc!r}",
                report,
            )
            continue
        rows: dict[str, QuestionRow] = {}
        warnings = list(result.warnings)
        for question in result.questions:
            if question.key in rows:
                warnings.append(f"{src.rel}: la clave «{question.key}» está repetida; se omite")
                continue
            rows[question.key] = resolve_row(question, result.meta)
        store.replace_source(
            path=src.rel,
            kind=src.importer.kind,
            fingerprint=src.fingerprint,
            meta=result.meta,
            rows=list(rows.values()),
            warnings=warnings,
        )
    if progress:
        progress(len(pending), len(pending), "")
    return report


def _store_error(
    store: Store, rel: str, kind: str, fp: str, message: str, report: SyncReport
) -> None:
    report.errors.append((rel, message))
    store.replace_source(
        path=rel, kind=kind, fingerprint=fp, meta=PackMeta(), rows=[], warnings=[], error=message
    )
