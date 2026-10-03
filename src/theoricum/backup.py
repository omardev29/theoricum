"""`dgt export` / `dgt import`: a portable zip with the questions folder and the user history.

Layout of the zip:
  manifest.json   format, date, app version and counts
  questions/...   copy of the questions folder (hidden entries skipped)
  history.json    sessions (by uuid), answers and flags, as portable JSON
"""

import hashlib
import json
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath

from theoricum import __version__
from theoricum.db.store import HistoryImport, Store, now_iso

EXPORT_FORMAT = "theoricum-export/1"
# Already-compressed formats are stored as-is; text (JSON/TOML) is deflated.
STORED_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".apkg",
    ".colpkg",
    ".zip",
    ".mp3",
    ".mp4",
}
SKIPPED_SUFFIXES = {".part", ".tmp"}


class BackupError(Exception):
    """Shown to the user (Spanish)."""


@dataclass(slots=True)
class ImportSummary:
    files_added: int = 0
    files_identical: int = 0
    files_overwritten: int = 0
    conflicts: list[str] = field(default_factory=list)
    history: HistoryImport | None = None

    def describe(self) -> str:
        lines = [
            "Importación completada:",
            f"  · archivos de preguntas nuevos: {self.files_added}",
            f"  · ya estaban (idénticos): {self.files_identical}",
        ]
        if self.files_overwritten:
            lines.append(f"  · sobrescritos: {self.files_overwritten}")
        if self.conflicts:
            lines.append(
                f"  · distintos a los tuyos, conservados ({len(self.conflicts)}); usa --overwrite para reemplazarlos:"
            )
            lines.extend(f"      - {c}" for c in self.conflicts[:20])
        if self.history is None:
            lines.append("  · el archivo no incluía historial")
        else:
            lines.append(
                f"  · historial: {self.history.sessions} sesiones y {self.history.answers} respuestas nuevas, "
                f"{self.history.flags} marcas actualizadas"
            )
        return "\n".join(lines)


def default_export_path() -> Path:
    return Path.cwd() / f"theoricum-{date.today().isoformat()}.zip"


def _question_files(questions_dir: Path) -> list[Path]:
    files = []
    for path in sorted(questions_dir.rglob("*")):
        rel = path.relative_to(questions_dir)
        if any(part.startswith(".") for part in rel.parts) or not path.is_file():
            continue
        if path.suffix.lower() in SKIPPED_SUFFIXES:
            continue
        files.append(path)
    return files


def export_zip(
    store: Store, questions_dir: Path, output: Path | None = None, *, history: bool = True
) -> Path:
    output = (output or default_export_path()).resolve()
    if output.is_relative_to(questions_dir.resolve()):
        raise BackupError("el .zip no puede guardarse dentro de la carpeta de preguntas")
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".part")
    files = _question_files(questions_dir) if questions_dir.is_dir() else []
    history_data = store.export_history() if history else None
    with zipfile.ZipFile(tmp, "w") as zf:
        for path in files:
            compress = (
                zipfile.ZIP_STORED
                if path.suffix.lower() in STORED_SUFFIXES
                else zipfile.ZIP_DEFLATED
            )
            arcname = "questions/" + path.relative_to(questions_dir).as_posix()
            zf.write(path, arcname, compress_type=compress)
        if history_data is not None:
            zf.writestr(
                "history.json",
                json.dumps(history_data, ensure_ascii=False, indent=1),
                compress_type=zipfile.ZIP_DEFLATED,
            )
        manifest = {
            "format": EXPORT_FORMAT,
            "created_at": now_iso(),
            "app_version": __version__,
            "question_files": len(files),
            "question_bytes": sum(p.stat().st_size for p in files),
            "history": None
            if history_data is None
            else {"sessions": len(history_data["sessions"]), "flags": len(history_data["flags"])},
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    tmp.replace(output)
    return output


def _sha256(stream) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1 << 20), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _safe_target(questions_dir: Path, name: str) -> Path:
    rel = PurePosixPath(name)
    if (
        "\\" in name
        or rel.is_absolute()
        or not rel.parts
        or any(p in ("", ".", "..") for p in rel.parts)
    ):
        raise BackupError(f"ruta peligrosa dentro del zip: {name!r}")
    target = questions_dir.joinpath(*rel.parts)
    if not target.resolve().is_relative_to(questions_dir.resolve()):
        raise BackupError(f"ruta peligrosa dentro del zip: {name!r}")
    return target


def import_zip(
    store: Store, questions_dir: Path, path: Path, *, overwrite: bool = False
) -> ImportSummary:
    if not path.is_file() or not zipfile.is_zipfile(path):
        raise BackupError(f"«{path}» no es un archivo .zip válido")
    summary = ImportSummary()
    with zipfile.ZipFile(path) as zf:
        try:
            manifest = json.loads(zf.read("manifest.json"))
        except KeyError as exc:
            raise BackupError("falta manifest.json: no parece un export de theoricum") from exc
        if manifest.get("format") != EXPORT_FORMAT:
            raise BackupError(f"formato de export no soportado: {manifest.get('format')!r}")

        members = [
            i for i in zf.infolist() if i.filename.startswith("questions/") and not i.is_dir()
        ]
        targets = [
            (info, _safe_target(questions_dir, info.filename[len("questions/") :]))
            for info in members
        ]
        questions_dir.mkdir(parents=True, exist_ok=True)
        for info, target in targets:
            if target.exists():
                if target.stat().st_size == info.file_size:
                    with target.open("rb") as mine, zf.open(info) as theirs:
                        if _sha256(mine) == _sha256(theirs):
                            summary.files_identical += 1
                            continue
                if not overwrite:
                    summary.conflicts.append(info.filename[len("questions/") :])
                    continue
                summary.files_overwritten += 1
            else:
                summary.files_added += 1
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".part")
            with zf.open(info) as src, tmp.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            tmp.replace(target)

        if "history.json" in zf.namelist():
            try:
                summary.history = store.import_history(json.loads(zf.read("history.json")))
            except (ValueError, KeyError) as exc:
                raise BackupError(f"el historial del zip no es válido: {exc}") from exc
    return summary
