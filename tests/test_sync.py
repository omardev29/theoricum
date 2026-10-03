import os
from pathlib import Path

from theoricum.library import sync

from conftest import make_questions, write_pack


def bump(path: Path) -> None:
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))


def test_add_update_remove_without_losing_history(qdir: Path, store):
    pack = write_pack(qdir / "a.json", make_questions(3), {"id": "a"})
    report = sync(store, qdir)
    assert report.added == ["a.json"] and len(store.load_questions()) == 3

    session = store.start_session(mode="exam", keys=["a:q0", "a:q1"])
    store.record_answer(session, 0, 1, False)
    store.finish_session(
        session,
        n_correct=0,
        n_wrong=1,
        n_blank=1,
        passed=False,
        elapsed_s=10,
        blanks_count_as_wrong=True,
    )

    assert not sync(store, qdir).changed  # nothing changed: nothing re-imported

    write_pack(pack, make_questions(5), {"id": "a"})
    bump(pack)
    report = sync(store, qdir)
    assert report.updated == ["a.json"] and len(store.load_questions()) == 5

    pack.unlink()
    report = sync(store, qdir)
    assert report.removed == ["a.json"] and store.load_questions() == []
    # History is untouched by the sync.
    assert [e.key for e in store.answer_events()] == ["a:q0", "a:q1"]


def test_errors_ignored_files_and_hidden_entries(qdir: Path, store):
    (qdir / "roto.toml").write_text('format = "theoricum/1"\nquestions = [', encoding="utf-8")
    (qdir / "notas.json").write_text('{"x": 1}', encoding="utf-8")
    (qdir / ".oculto").mkdir()
    write_pack(qdir / ".oculto" / "p.json", make_questions(2))
    (qdir / "foto.png").write_bytes(b"png")
    report = sync(store, qdir)
    assert [path for path, _ in report.errors] == ["roto.toml"]
    assert report.ignored == ["notas.json"]
    (source,) = store.sources()
    assert source.error and "no se puede leer" in source.error


def test_duplicates_across_sources_prefer_priority(qdir: Path, store):
    same = [{"id": "x", "text": "¿Igual?", "options": ["Sí", "No"], "answer": "A"}]
    write_pack(qdir / "ia.json", same, {"id": "ia", "origin": "ia"})
    write_pack(qdir / "rev.json", same, {"id": "rev", "origin": "revista-dgt"})
    sync(store, qdir)
    (q,) = store.load_questions()
    assert q.key == "rev:x" and q.priority == 90


def test_disabled_excluded_topics_and_since(qdir: Path, store):
    qs = make_questions(4)
    qs[0]["topic"] = "senales"
    qs[1]["date"] = "2019-05"
    write_pack(qdir / "p.json", qs, {"id": "p", "exclude_topics": ["Señales"], "date": "2025-01"})
    sync(store, qdir)
    assert {q.key for q in store.load_questions()} == {"p:q1", "p:q2", "p:q3"}
    assert {q.key for q in store.load_questions(since="2020")} == {"p:q2", "p:q3"}
    store.set_flag("p:q2", disabled=True)
    assert {q.key for q in store.load_questions(since="2020")} == {"p:q3"}


def test_disabled_pack(qdir: Path, store):
    write_pack(qdir / "p.json", make_questions(2), {"enabled": False})
    sync(store, qdir)
    assert store.load_questions() == []
    assert not store.sources()[0].enabled


def test_migration_turns_old_dudosa_marks_into_saved_questions(tmp_path: Path):
    import sqlite3

    from theoricum.db.migrations import _migrations
    from theoricum.db.store import Store

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(_migrations()[0] + "\nPRAGMA user_version = 1;")
    conn.execute(
        "INSERT INTO flags VALUES ('k1', 0, 1, NULL, '2026-10-01T10:00:00+00:00'),"
        " ('k2', 1, 0, NULL, '2026-10-01T10:00:00+00:00')"
    )
    conn.commit()
    conn.close()
    store = Store.open(db)
    assert store.saved() == {"k1": "2026-10-01T10:00:00+00:00"}
    assert not store.flags()["k1"].flagged and store.flags()["k2"].disabled
    store.close()


def test_saved_questions_lookup_and_backup_roundtrip(qdir: Path, store):
    write_pack(qdir / "p.json", make_questions(3), {"id": "p"})
    sync(store, qdir)
    store.set_saved("p:q1", True)
    store.set_saved("gone:x", True)  # its source no longer exists
    found = store.questions_by_key(store.saved())
    assert set(found) == {"p:q1"}
    data = store.export_history()
    assert [s["question_key"] for s in data["saved"]] == ["p:q1", "gone:x"]

    from theoricum.db.store import Store

    other = Store.open(":memory:")
    result = other.import_history(data)
    assert result.saved == 2 and set(other.saved()) == {"p:q1", "gone:x"}
    assert other.import_history(data).saved == 0  # idempotent
