"""Contract tests: the question format, the keys and the backups are what users keep for years.

The fixtures in tests/contract/ are FROZEN. They were written by theoricum 0.1.0 and must keep
importing exactly like this forever. If one of these tests fails, the change broke users' packs,
history or backups: fix the code, never the fixture or the expectations (see CLAUDE.md).
"""

import json
import shutil
import zipfile
from pathlib import Path

from theoricum.backup import EXPORT_FORMAT, export_zip, import_zip
from theoricum.db.store import HISTORY_FORMAT, Store
from theoricum.library import sync
from theoricum.media import MediaResolver
from theoricum.models import FORMAT_ID
from theoricum.practice import Practice

from anki_builder import anki_mc_deck, build_apkg

CONTRACT = Path(__file__).parent / "contract"
PNG = (CONTRACT / "bank" / "propio" / "img" / "cuadrado.png").read_bytes()


def make_bank(target: Path, tmp: Path) -> Path:
    """The frozen packs, plus an Anki deck (built here: .apkg files are git-ignored)."""
    shutil.copytree(CONTRACT / "bank", target)
    notetypes, notes = anki_mc_deck()
    (target / "anki").mkdir()
    build_apkg(
        target / "anki" / "carnet.apkg",
        version=3,
        notetypes=notetypes,
        notes=notes,
        media={"señal 1.png": PNG},
        tmp=tmp,
    )
    return target


def test_format_identifiers_never_change():
    assert FORMAT_ID == "theoricum/1"
    assert EXPORT_FORMAT == "theoricum-export/1"
    assert HISTORY_FORMAT == "theoricum-history/1"


def test_frozen_packs_import_with_the_same_keys_and_content(tmp_path: Path, store):
    qdir = make_bank(tmp_path / "questions", tmp_path)
    report = sync(store, qdir)
    assert not report.errors
    found = {q.key: q for q in store.questions_by_key(_all_keys(store)).values()}
    # Keys: "<pack.id>:<id>", the path inside questions/ (always with /) without a pack id,
    # the position (q2) without a question id, and "anki:<guid>" for Anki notes.
    assert set(found) == {
        "contrato:c-001",
        "contrato:c-002",
        "contrato:c-003",
        "contrato:c-004",
        "sueltas/mias:m-1",
        "sueltas/mias:q2",
        "anki:guid-mc-1",
        "anki:guid-mc-2",
        "anki:guid-basic-1",
    }
    first = found["contrato:c-001"]
    assert first.text == "¿Qué figura aparece en la imagen?"
    assert first.options == ("Un círculo", "Un cuadrado", "Un triángulo")
    assert first.answer == 1 and first.topic == "otros" and first.date == "2026-09"
    assert first.explanation == "Cuatro lados iguales y cuatro ángulos rectos."
    assert first.image_ref == "file:propio/img/cuadrado.png"
    assert first.tags == ("formas", "contrato")
    assert first.source == "Escrita a mano para los tests de contrato"
    assert first.origin == "ia" and first.priority == 15 and first.source_name == "Pack de contrato"
    second = found["contrato:c-002"]
    assert second.answer == 3 and second.topic == "senales" and second.date == "2026-10-01"
    assert found["sueltas/mias:m-1"].answer == 2 and found["sueltas/mias:m-1"].date == "2025-02"
    assert found["anki:guid-mc-1"].image_ref == "apkg:anki/carnet.apkg!0"
    assert found["anki:guid-mc-1"].answer == 1

    pool = {q.key for q in store.load_questions()}
    assert "contrato:c-004" not in pool  # its topic is excluded by the pack
    media = MediaResolver(qdir)
    try:
        assert media.read(first.image_ref) == PNG
        assert media.read(found["anki:guid-mc-1"].image_ref) == PNG
    finally:
        media.close()


def _all_keys(store: Store) -> list[str]:
    return [r[0] for r in store.conn.execute("SELECT key FROM questions")]


def _frozen_export(tmp_path: Path) -> Path:
    """The frozen export-v1 zip: manifest.json, history.json and questions/."""
    bank = make_bank(tmp_path / "bank", tmp_path)
    out = tmp_path / "theoricum-2026-10-05.zip"
    with zipfile.ZipFile(out, "w") as zf:
        for name in ("manifest.json", "history.json"):
            zf.write(CONTRACT / "export-v1" / name, name)
        for path in sorted(bank.rglob("*")):
            if path.is_file():
                zf.write(path, "questions/" + path.relative_to(bank).as_posix())
    return out


def test_frozen_export_v1_restores_questions_and_history(tmp_path: Path, store):
    backup = _frozen_export(tmp_path)
    qdir = tmp_path / "questions"
    summary = import_zip(store, qdir, backup)
    assert summary.files_added == 4 and not summary.failed and not summary.conflicts
    assert summary.history is not None
    assert (summary.history.sessions, summary.history.answers) == (3, 7)
    sync(store, qdir)

    practice = Practice(store)
    pool = {q.key for q in practice.pool}
    assert "contrato:c-002" not in pool  # disabled by the user in the backup
    exams = store.exam_records()
    assert len(exams) == 1 and exams[0].passed and exams[0].n_blank == 1
    # Failed (a blank counts in the exam) and not yet right 3 times in a row:
    review = practice.review_progress(practice.pool)
    assert review == {"anki:guid-mc-1": 0, "contrato:c-003": 0, "sueltas/mias:m-1": 1}
    assert list(store.saved()) == [
        "contrato:c-001",
        "anki:guid-mc-2",
    ]
    assert store.session_count() == 2  # the abandoned one is kept but does not count

    again = import_zip(store, qdir, backup)
    assert again.files_identical == 4 and again.history is not None
    assert again.history.sessions == 0 and len(store.exam_records()) == 1


def _key_layout(history: dict) -> dict[str, set[str]]:
    sessions = history["sessions"]
    return {
        "history": set(history),
        "session": set().union(*(set(s) for s in sessions)),
        "answer": set().union(*(set(a) for s in sessions for a in s["answers"])),
        "flag": set().union(*(set(f) for f in history["flags"])),
        "saved": set().union(*(set(r) for r in history["saved"])),
    }


def test_export_still_writes_every_field_of_the_v1_layout(tmp_path: Path, store):
    """New fields may be added (older versions ignore them); none may be renamed or dropped."""
    backup = _frozen_export(tmp_path)
    qdir = tmp_path / "questions"
    import_zip(store, qdir, backup)
    sync(store, qdir)
    out = export_zip(store, qdir, tmp_path / "again.zip")
    frozen_manifest = json.loads((CONTRACT / "export-v1" / "manifest.json").read_bytes())
    frozen_history = json.loads((CONTRACT / "export-v1" / "history.json").read_bytes())
    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        history = json.loads(zf.read("history.json"))
        names = set(zf.namelist())
    assert manifest["format"] == EXPORT_FORMAT and history["format"] == HISTORY_FORMAT
    assert set(frozen_manifest) <= set(manifest)
    assert set(frozen_manifest["history"]) <= set(manifest["history"])
    for part, keys in _key_layout(frozen_history).items():
        assert keys <= _key_layout(history)[part], part
    assert {
        "questions/propio/pack.toml",
        "questions/propio/img/cuadrado.png",
        "questions/sueltas/mias.json",
        "questions/anki/carnet.apkg",
    } <= names
    sessions = {s["uuid"]: s for s in history["sessions"]}
    for frozen in frozen_history["sessions"]:
        assert sessions[frozen["uuid"]] == frozen  # restored and exported again unchanged
