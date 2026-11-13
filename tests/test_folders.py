"""Question folders: ./questions + ~/Questions (any case), flags, the old default, and how the
library, the images, the backups and the CLI use several folders. Runs on Linux, macOS and
Windows (HOME and USERPROFILE are both faked)."""

import json
import zipfile
from pathlib import Path

import pytest

from theoricum.backup import export_zip, import_zip
from theoricum.cli import main
from theoricum.config import NoQuestionsFolder, find_folder, resolve_paths
from theoricum.library import sync
from theoricum.media import MediaResolver
from theoricum.practice import Practice

from conftest import make_questions, write_pack

PNG = b"\x89PNG\r\n\x1a\nimage"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("THEORICUM_QUESTIONS", "THEORICUM_DATA"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def places(tmp_path: Path) -> tuple[Path, Path, Path]:
    """(cwd, home, data dir), all empty."""
    cwd, home, data = tmp_path / "proyecto", tmp_path / "home", tmp_path / "data"
    for folder in (cwd, home, data):
        folder.mkdir()
    return cwd, home, data


def case_sensitive_fs(tmp_path: Path) -> bool:
    (tmp_path / "probe").mkdir()
    return not (tmp_path / "PROBE").exists()


def resolve(places, **kw):
    cwd, home, data = places
    return resolve_paths(data_dir=data, cwd=cwd, home=home, **kw)


# --- where the folders are --------------------------------------------------------------------


def test_folder_names_match_in_any_case_and_keep_their_real_spelling(tmp_path: Path):
    (tmp_path / "qUestions").mkdir()
    (tmp_path / "questions.txt").write_text("not a folder", encoding="utf-8")
    found = find_folder(tmp_path, "Questions")
    assert found is not None and found.name == "qUestions"
    assert find_folder(tmp_path, "otra") is None
    assert find_folder(tmp_path / "no-existe", "Questions") is None


def test_the_exact_spelling_wins_when_several_match(tmp_path: Path):
    if not case_sensitive_fs(tmp_path):
        pytest.skip("only case-sensitive file systems can hold both")
    (tmp_path / "QUESTIONS").mkdir()
    (tmp_path / "questions").mkdir()
    assert find_folder(tmp_path, "questions").name == "questions"  # type: ignore[union-attr]
    assert find_folder(tmp_path, "Questions").name == "QUESTIONS"  # type: ignore[union-attr]


def test_local_and_global_are_both_read_and_new_files_go_to_the_local_one(places):
    cwd, home, _ = places
    (cwd / "Questions").mkdir()  # any case
    (home / "questions").mkdir()
    paths = resolve(places)
    assert [f.kind for f in paths.folders] == ["local", "global"]
    assert paths.question_dirs == ((cwd / "Questions").resolve(), (home / "questions").resolve())
    assert paths.questions_dir == (cwd / "Questions").resolve()


def test_without_a_local_folder_the_global_one_is_used_and_created_on_demand(places):
    _, home, _ = places
    paths = resolve(places)
    assert [f.kind for f in paths.folders] == ["global"]
    assert paths.questions_dir == home.resolve() / "Questions"
    assert not paths.questions_dir.exists()  # resolving never creates anything


def test_no_local_and_no_global(places):
    cwd, home, _ = places
    (cwd / "questions").mkdir()
    (home / "Questions").mkdir()
    only_global = resolve(places, use_local=False)
    assert [f.kind for f in only_global.folders] == ["global"]
    assert only_global.questions_dir == (home / "Questions").resolve()
    only_local = resolve(places, use_global=False)
    assert [f.kind for f in only_local.folders] == ["local"]
    with pytest.raises(NoQuestionsFolder):
        resolve(places, use_local=False, use_global=False)
    (cwd / "questions").rmdir()
    fresh = resolve(places, use_global=False)  # will be created in the current directory
    assert fresh.questions_dir == cwd.resolve() / "questions"


def test_an_explicit_folder_is_the_only_one(places, monkeypatch):
    cwd, home, data = places
    (cwd / "questions").mkdir()
    (home / "Questions").mkdir()
    other = data.parent / "otra"
    paths = resolve(places, questions_dir=other)
    assert paths.question_dirs == (other.resolve(),) and paths.folders[0].kind == "explicit"
    monkeypatch.setenv("THEORICUM_QUESTIONS", str(other))
    assert resolve(places).question_dirs == (other.resolve(),)


def test_the_old_default_folder_keeps_working_until_questions_exists(places):
    _, home, data = places
    legacy = data / "questions"
    (legacy / "revista-dgt").mkdir(parents=True)
    write_pack(legacy / "revista-dgt" / "pack.json", make_questions(1), {"id": "r"})
    paths = resolve(places)
    assert [f.kind for f in paths.folders] == ["legacy"]
    assert paths.questions_dir == legacy.resolve() and paths.legacy_folder() is not None
    (home / "Questions").mkdir()
    paths = resolve(places)
    assert [f.kind for f in paths.folders] == ["global"] and paths.legacy_folder() is None


def test_an_empty_old_folder_is_not_used(places):
    _, home, data = places
    (data / "questions").mkdir()
    assert resolve(places).questions_dir == home.resolve() / "Questions"


def test_running_from_the_home_folder_does_not_read_it_twice(places):
    _, home, data = places
    (home / "Questions").mkdir()
    paths = resolve_paths(data_dir=data, cwd=home, home=home)
    assert [f.kind for f in paths.folders] == ["global"]
    only_local = resolve_paths(data_dir=data, cwd=home, home=home, use_global=False)
    assert [f.kind for f in only_local.folders] == ["local"]


# --- several folders in the library, the images and the backups -------------------------------


def two_folders(tmp_path: Path) -> tuple[Path, Path]:
    local, glob = tmp_path / "local", tmp_path / "global"
    write_pack(local / "propio" / "pack.json", make_questions(2, "l"), {"id": "propio"})
    write_pack(local / "revista-dgt" / "pack.json", make_questions(3, "nuevo"), {"id": "r"})
    write_pack(glob / "revista-dgt" / "pack.json", make_questions(1, "viejo"), {"id": "r"})
    write_pack(glob / "ia" / "mias.json", make_questions(2, "ia"), {"origin": "ia"})
    return local, glob


def test_the_first_folder_wins_on_equal_paths_and_keys_do_not_depend_on_the_folder(
    tmp_path: Path, store
):
    local, glob = two_folders(tmp_path)
    report = sync(store, [local, glob])
    assert [rel for rel, _ in report.shadowed] == ["revista-dgt/pack.json"]
    keys = {q.key for q in store.load_questions()}
    assert keys == {"propio:l0", "propio:l1", "r:nuevo0", "r:nuevo1", "r:nuevo2"} | {
        "ia/mias:ia0",
        "ia/mias:ia1",
    }
    # A pack without an id is keyed by its path *inside* its folder: moving it keeps its keys.
    (glob / "ia").rename(local / "ia")
    sync(store, [local, glob])
    assert keys == {q.key for q in store.load_questions()}


def test_images_are_found_in_any_folder_the_first_one_winning(tmp_path: Path):
    local, glob = tmp_path / "local", tmp_path / "global"
    (local / "img").mkdir(parents=True)
    (glob / "img").mkdir(parents=True)
    (glob / "img" / "solo-global.png").write_bytes(PNG)
    (glob / "img" / "las-dos.png").write_bytes(b"global")
    (local / "img" / "las-dos.png").write_bytes(b"local")
    media = MediaResolver([local, glob])
    try:
        assert media.read("file:img/solo-global.png") == PNG
        assert media.read("file:img/las-dos.png") == b"local"
        with pytest.raises(FileNotFoundError):
            media.read("file:img/ninguna.png")
    finally:
        media.close()


def test_history_follows_the_questions_between_folders(tmp_path: Path, store):
    local, glob = two_folders(tmp_path)
    sync(store, [local, glob])
    sid = store.start_session(mode="study", keys=["ia/mias:ia0"])
    store.record_answer(sid, 0, 2, False)
    store.finish_session(
        sid, n_correct=0, n_wrong=1, n_blank=0, passed=None, elapsed_s=1,
        blanks_count_as_wrong=False,
    )  # fmt: skip
    assert Practice(store).review_count() == 1
    (glob / "ia").rename(local / "ia")
    sync(store, [local, glob])
    assert Practice(store).review_count() == 1  # still pending: same key, same history


def test_export_merges_the_folders_like_the_app_sees_them(tmp_path: Path, store):
    local, glob = two_folders(tmp_path)
    sync(store, [local, glob])
    out = export_zip(store, [local, glob], tmp_path / "copia.zip")
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        revista = json.loads(zf.read("questions/revista-dgt/pack.json"))
    assert {"questions/propio/pack.json", "questions/ia/mias.json"} <= names
    assert len(revista["questions"]) == 3  # the local copy, the one in use
    with pytest.raises(Exception, match="carpeta de preguntas"):
        export_zip(store, [local, glob], glob / "dentro.zip")


def test_import_never_duplicates_what_another_folder_already_has(tmp_path: Path, store):
    local, glob = two_folders(tmp_path)
    backup = export_zip(store, [local, glob], tmp_path / "copia.zip", history=False)
    # Same folders: everything is already there, nothing is copied into the local folder.
    summary = import_zip(store, local, backup, search_dirs=[local, glob])
    assert summary.files_identical == 3 and summary.files_added == 0  # revista-dgt once
    assert not (local / "ia").exists()

    # The global copy changed: conflict, unless --overwrite, which rewrites it where it is.
    write_pack(glob / "ia" / "mias.json", make_questions(5, "ia"), {"origin": "ia"})
    summary = import_zip(store, local, backup, search_dirs=[local, glob])
    assert summary.conflicts == ["ia/mias.json"]
    summary = import_zip(store, local, backup, overwrite=True, search_dirs=[local, glob])
    assert summary.files_overwritten == 1 and not (local / "ia").exists()
    restored = json.loads((glob / "ia" / "mias.json").read_text(encoding="utf-8"))
    assert len(restored["questions"]) == 2

    # Something new goes to the folder for new files.
    fresh = tmp_path / "vacia"
    summary = import_zip(store, fresh, backup, search_dirs=[fresh])
    assert summary.files_added == 3 and (fresh / "ia" / "mias.json").is_file()


# --- the CLI, with a fake home and current directory ------------------------------------------


@pytest.fixture
def fake_home(places, monkeypatch) -> tuple[Path, Path, Path]:
    cwd, home, data = places
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Path.home() on Windows
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("THEORICUM_DATA", str(data))
    return places


def test_cli_check_reads_both_folders_and_the_flags_ignore_one(fake_home, capsys):
    cwd, home, _ = fake_home
    write_pack(cwd / "QUESTIONS" / "p.json", make_questions(2), {"id": "p"})
    write_pack(home / "questions" / "g.json", make_questions(3, "g"), {"id": "g"})
    assert main(["check"]) == 0
    out = capsys.readouterr().out
    assert "Banco activo: 5 preguntas" in out
    assert "carpeta del directorio actual" in out and "carpeta global" in out
    assert main(["check", "--no-global"]) == 0
    assert "Banco activo: 2 preguntas" in capsys.readouterr().out
    assert main(["--no-local", "check"]) == 0
    assert "Banco activo: 3 preguntas" in capsys.readouterr().out
    assert main(["check", "--no-local", "--no-global"]) == 2
    assert "--questions-dir" in capsys.readouterr().err


def test_cli_import_goes_to_the_local_folder_or_else_to_the_global_one(
    fake_home, tmp_path: Path, capsys
):
    cwd, home, _ = fake_home
    source = tmp_path / "origen"
    write_pack(source / "p.json", make_questions(2), {"id": "p"})
    backup = tmp_path / "copia.zip"
    assert main(["--questions-dir", str(source), "export", "-o", str(backup)]) == 0

    assert main(["import", str(backup)]) == 0  # no folder yet: ~/Questions is created
    assert (home / "Questions" / "p.json").is_file()
    (cwd / "questions").mkdir()
    (home / "Questions" / "p.json").unlink()
    assert main(["import", str(backup)]) == 0  # now the local folder exists
    assert (cwd / "questions" / "p.json").is_file()
    elsewhere = tmp_path / "otra"
    assert main(["import", str(backup), "--into", str(elsewhere)]) == 0
    assert (elsewhere / "p.json").is_file()
    assert "no es una de tus carpetas" in capsys.readouterr().out


def test_cli_fetch_updates_a_source_in_the_folder_that_has_it(fake_home):
    from theoricum.cli import _fetch_target, _paths, build_parser

    cwd, home, _ = fake_home
    (cwd / "questions").mkdir()
    write_pack(home / "Questions" / "revista-dgt" / "pack.json", make_questions(1), {"id": "r"})
    args = build_parser().parse_args(["fetch", "revista-dgt"])
    paths = _paths(args)
    assert _fetch_target(args, paths) == (home / "Questions").resolve()  # where it already is
    args = build_parser().parse_args(["fetch", "signals"])
    assert _fetch_target(args, paths) == (cwd / "questions").resolve()  # new: the local folder
    args = build_parser().parse_args(["fetch", "anki", "--into", str(home / "x")])
    assert _fetch_target(args, paths) == (home / "x").resolve()
