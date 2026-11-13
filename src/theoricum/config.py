"""Filesystem locations: the question folders and the personal data folder (Linux, macOS, Windows).

Question folders, in order (an earlier one wins when both hold the same relative path):

1. `questions/` in the current directory (the **local** folder);
2. `Questions/` in the home directory (the **global** folder): `~/Questions` on Linux and macOS,
   `%USERPROFILE%\\Questions` on Windows. Until it exists, the old default
   `<data dir>/questions` is used instead if it has files, so existing installs keep working.

Both names match in any case («qUestions» is fine). `--no-local` / `--no-global` ignore one of
them; `--questions-dir` or `$THEORICUM_QUESTIONS` use one explicit folder and nothing else.
New files (`dgt import`, `dgt fetch`) go to the first folder: the local one if it exists,
otherwise the global one (created on demand).

Keys of packs without an `id` are their path *inside* whichever folder holds them, so moving a
pack between folders never changes its keys.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "theoricum"
DB_FILENAME = "theoricum.db"
LOCAL_NAME = "questions"
GLOBAL_NAME = "Questions"
LEGACY_NAME = "questions"  # inside the data folder: the default before ~/Questions

KIND_LABELS = {
    "local": "carpeta del directorio actual",
    "global": "carpeta global",
    "legacy": "carpeta global antigua",
    "explicit": "indicada con --questions-dir o THEORICUM_QUESTIONS",
}


class NoQuestionsFolder(Exception):
    """Both default folders were ignored and no explicit one was given (Spanish message)."""


def default_data_dir() -> Path:
    """Per-user data folder: ~/.local/share/theoricum (Linux, honours $XDG_DATA_HOME),
    %LOCALAPPDATA%\\theoricum (Windows), ~/Library/Application Support/theoricum (macOS)."""
    return Path(user_data_dir(APP_NAME, appauthor=False))


def find_folder(parent: Path, name: str) -> Path | None:
    """The subfolder of `parent` called `name` in any case, with its real spelling on disk.

    If several match (only possible on case-sensitive file systems), the exact spelling wins,
    then the first in alphabetical order."""
    try:
        with os.scandir(parent) as entries:
            matches = sorted(
                e.name
                for e in entries
                if e.name.casefold() == name.casefold() and e.is_dir(follow_symlinks=True)
            )
    except OSError:
        return None
    if not matches:
        return None
    return parent / (name if name in matches else matches[0])


def _has_files(folder: Path) -> bool:
    try:
        return folder.is_dir() and any(not p.name.startswith(".") for p in folder.iterdir())
    except OSError:
        return False


@dataclass(frozen=True, slots=True)
class QuestionsFolder:
    path: Path
    kind: str  # local | global | legacy | explicit

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)


@dataclass(frozen=True, slots=True)
class Paths:
    """`questions_dir` receives new files; `folders` are read in order (default: just that one)."""

    questions_dir: Path
    data_dir: Path
    folders: tuple[QuestionsFolder, ...] = field(default=())

    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_FILENAME

    @property
    def question_dirs(self) -> tuple[Path, ...]:
        """The folders whose questions are used, the one that wins on equal paths first."""
        return tuple(f.path for f in self.folders) or (self.questions_dir,)

    def legacy_folder(self) -> QuestionsFolder | None:
        return next((f for f in self.folders if f.kind == "legacy"), None)

    def home_of(self, rel: str) -> Path | None:
        """The folder whose copy of a relative path is used (None if no folder has it)."""
        for folder in self.question_dirs:
            if (folder / rel).exists():
                return folder
        return None


def _same(a: Path, b: Path) -> bool:
    try:
        return a == b or os.path.samefile(a, b)
    except OSError:
        return False


def resolve_paths(
    questions_dir: str | os.PathLike[str] | None = None,
    data_dir: str | os.PathLike[str] | None = None,
    *,
    use_local: bool = True,
    use_global: bool = True,
    cwd: Path | None = None,
    home: Path | None = None,
) -> Paths:
    """Resolve the folders: explicit flag > $THEORICUM_QUESTIONS > local + global (see above)."""
    if data_dir is None:
        data_dir = os.environ.get("THEORICUM_DATA") or default_data_dir()
    data = Path(data_dir).expanduser().resolve()

    if questions_dir is None:
        questions_dir = os.environ.get("THEORICUM_QUESTIONS") or None
    if questions_dir is not None:
        explicit = Path(questions_dir).expanduser().resolve()
        return Paths(explicit, data, (QuestionsFolder(explicit, "explicit"),))

    if not (use_local or use_global):
        raise NoQuestionsFolder(
            "has ignorado las dos carpetas de preguntas (--no-local y --no-global): "
            "indica una con --questions-dir"
        )
    cwd = (cwd or Path.cwd()).resolve()
    home = (home or Path.home()).resolve()
    folders: list[QuestionsFolder] = []
    glob = None
    if use_global:
        if found := find_folder(home, GLOBAL_NAME):
            glob = QuestionsFolder(found.resolve(), "global")
        elif _has_files(legacy := data / LEGACY_NAME):
            glob = QuestionsFolder(legacy, "legacy")
        else:
            glob = QuestionsFolder(home / GLOBAL_NAME, "global")  # created by import/fetch
    local = find_folder(cwd, LOCAL_NAME) if use_local else None
    # Run from the home folder, ./questions *is* the global folder: list it once, as global.
    if local is not None and (glob is None or not _same(local, glob.path)):
        folders.append(QuestionsFolder(local.resolve(), "local"))
    if glob is not None:
        folders.append(glob)
    if not folders:  # --no-global and no local folder yet: it will be created here
        folders.append(QuestionsFolder(cwd / LOCAL_NAME, "local"))
    return Paths(folders[0].path, data, tuple(folders))
