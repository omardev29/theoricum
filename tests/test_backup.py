import json
import zipfile
from pathlib import Path

import pytest

from theoricum.backup import BackupError, export_zip, import_zip
from theoricum.db.store import Store
from theoricum.library import sync

from conftest import make_questions, write_pack


def _play(store: Store) -> None:
    sid = store.start_session(mode="exam", keys=["a:q0", "a:q1"], time_limit_s=1800)
    store.record_answer(sid, 0, 0, True)
    store.finish_session(
        sid,
        n_correct=1,
        n_wrong=0,
        n_blank=1,
        passed=True,
        elapsed_s=12.5,
        blanks_count_as_wrong=True,
    )
    store.set_flag("a:q1", disabled=True)
    store.set_saved("a:q0", True)


def test_export_import_roundtrip_merges_without_duplicates(tmp_path: Path, qdir: Path, store):
    write_pack(qdir / "a" / "pack.json", make_questions(2), {"id": "a"})
    (qdir / "a" / "img.png").write_bytes(b"\x89PNG data")
    (qdir / ".cache").mkdir()
    (qdir / ".cache" / "x").write_text("hidden", encoding="utf-8")
    sync(store, qdir)
    _play(store)

    out = export_zip(store, qdir, tmp_path / "backup.zip")
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert {
            "manifest.json",
            "history.json",
            "questions/a/pack.json",
            "questions/a/img.png",
        } == names
        assert zf.getinfo("questions/a/img.png").compress_type == zipfile.ZIP_STORED
        assert json.loads(zf.read("manifest.json"))["history"] == {
            "sessions": 1,
            "flags": 1,
            "saved": 1,
        }

    # Restore into a fresh place.
    new_q = tmp_path / "new_questions"
    other = Store.open(":memory:")
    summary = import_zip(other, new_q, out)
    assert (
        summary.files_added == 2 and summary.history.sessions == 1 and summary.history.answers == 2
    )
    sync(other, new_q)
    assert len(other.load_questions()) == 1  # a:q1 was disabled, and that flag came along
    assert [e.key for e in other.answer_events()] == [e.key for e in store.answer_events()]
    assert other.flags()["a:q1"].disabled
    assert set(other.saved()) == {"a:q0"}

    # Importing again is idempotent.
    again = import_zip(other, new_q, out)
    assert again.files_identical == 2 and again.files_added == 0 and again.history.sessions == 0
    assert len(other.exam_records()) == 1


def test_import_conflicts_and_overwrite(tmp_path: Path, qdir: Path, store):
    write_pack(qdir / "p.json", make_questions(1), {"id": "p"})
    out = export_zip(store, qdir, tmp_path / "b.zip", history=False)
    write_pack(qdir / "p.json", make_questions(3), {"id": "p"})
    summary = import_zip(store, qdir, out)
    assert summary.conflicts == ["p.json"] and summary.history is None
    summary = import_zip(store, qdir, out, overwrite=True)
    assert summary.files_overwritten == 1
    assert len(json.loads((qdir / "p.json").read_text(encoding="utf-8"))["questions"]) == 1


def test_import_rejects_zip_slip_and_foreign_zips(tmp_path: Path, qdir: Path, store):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format": "theoricum-export/1"}))
        zf.writestr("questions/../../fuera.txt", "x")
    with pytest.raises(BackupError, match="ruta peligrosa"):
        import_zip(store, qdir, evil)
    assert not (tmp_path / "fuera.txt").exists()

    foreign = tmp_path / "foreign.zip"
    with zipfile.ZipFile(foreign, "w") as zf:
        zf.writestr("hola.txt", "x")
    with pytest.raises(BackupError, match="manifest"):
        import_zip(store, qdir, foreign)


def test_export_refuses_output_inside_questions(qdir: Path, store):
    with pytest.raises(BackupError):
        export_zip(store, qdir, qdir / "x.zip")
