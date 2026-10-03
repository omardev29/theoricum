import json
import sys
import zipfile
from pathlib import Path

import pytest

from theoricum.backup import BackupError, export_zip, import_zip
from theoricum.db.store import Store
from theoricum.library import sync
from theoricum.media import MediaResolver
from theoricum.practice import Practice

from anki_builder import anki_mc_deck, build_apkg
from conftest import make_questions, write_pack

PNG = b"\x89PNG\r\n\x1a\nfake-image-bytes"


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


def test_history_exported_on_linux_is_restored_on_any_os(tmp_path: Path, qdir: Path, store):
    """A `dgt export` made on Linux, imported here: every key of its history finds its question."""
    linux = tmp_path / "linux"
    # No id: this pack is keyed by its path inside questions/, the part that differs between OSes.
    write_pack(linux / "ia" / "mias.json", make_questions(3), {"origin": "ia"})
    revista = {
        "id": "t224-q01",
        "text": "¿Qué indica?",
        "options": ["Sí", "No"],
        "answer": "A",
        "image": "img/t224-q01.png",
    }
    write_pack(linux / "revista-dgt" / "pack.json", [revista], {"id": "revista-dgt"})
    (linux / "revista-dgt" / "img").mkdir()
    (linux / "revista-dgt" / "img" / "t224-q01.png").write_bytes(PNG)
    notetypes, notes = anki_mc_deck()
    (linux / "anki").mkdir()
    build_apkg(
        linux / "anki" / "carnet.apkg",
        version=3,
        notetypes=notetypes,
        notes=notes,
        media={"señal 1.png": PNG},
        tmp=tmp_path,
    )
    # The history references the keys exactly as Linux computes them.
    failed = ["ia/mias:q0", "revista-dgt:t224-q01", "anki:guid-mc-1"]
    source = Store.open(":memory:")
    sid = source.start_session(mode="study", keys=failed)
    for position, chosen in enumerate([1, 1, 0]):
        source.record_answer(sid, position, chosen, False)
    source.finish_session(
        sid,
        n_correct=0,
        n_wrong=3,
        n_blank=0,
        passed=None,
        elapsed_s=30,
        blanks_count_as_wrong=False,
    )
    source.set_flag("ia/mias:q1", disabled=True)
    source.set_saved("ia/mias:q2", True)
    source.set_saved("anki:guid-mc-2", True)
    backup = export_zip(source, linux, tmp_path / "theoricum-linux.zip")
    source.close()

    import_zip(store, qdir, backup)
    sync(store, qdir)
    practice = Practice(store)
    pool = {q.key: q for q in practice.pool}
    assert {*failed, "ia/mias:q2", "anki:guid-mc-2"} <= set(pool)
    assert "ia/mias:q1" not in pool  # the disabled flag found its question
    assert practice.review_count() == 3  # the three failures are pending review
    assert {q.key for q, _ in practice.saved_questions()} == {"ia/mias:q2", "anki:guid-mc-2"}
    media = MediaResolver(qdir)
    try:
        assert media.read(pool["revista-dgt:t224-q01"].image_ref) == PNG
        assert media.read(pool["anki:guid-mc-1"].image_ref) == PNG
    finally:
        media.close()  # Windows cannot delete files that are still open


def test_import_lists_the_files_it_cannot_write_and_goes_on(tmp_path: Path, qdir: Path, store):
    src = tmp_path / "src"
    write_pack(src / "ok.json", make_questions(1), {"id": "ok"})
    write_pack(src / "sub" / "p.json", make_questions(1), {"id": "p"})
    backup = export_zip(store, src, tmp_path / "b.zip")
    (qdir / "sub").write_text("a file where a folder should be", encoding="utf-8")
    summary = import_zip(store, qdir, backup)
    assert summary.files_added == 1 and (qdir / "ok.json").is_file()
    assert [path for path, _ in summary.failed] == ["sub/p.json"]
    assert summary.history is not None  # the history is restored anyway
    assert "no se han podido guardar (1)" in summary.describe()
    assert not list(qdir.rglob("*.part"))


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows rejects these names")
def test_import_on_windows_skips_names_windows_does_not_allow(tmp_path: Path, qdir: Path, store):
    backup = tmp_path / "linux.zip"
    with zipfile.ZipFile(backup, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format": "theoricum-export/1"}))
        zf.writestr("questions/bien.json", "{}")
        zf.writestr("questions/¿qué?.json", "{}")
    summary = import_zip(store, qdir, backup)
    assert summary.files_added == 1 and [path for path, _ in summary.failed] == ["¿qué?.json"]
    assert not list(qdir.rglob("*.part"))


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
