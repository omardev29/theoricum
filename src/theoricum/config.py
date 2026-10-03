"""Filesystem locations (questions folder and personal data), on Linux, macOS and Windows."""

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "theoricum"
DB_FILENAME = "theoricum.db"


def default_data_dir() -> Path:
    """Per-user data folder: ~/.local/share/theoricum (Linux, honours $XDG_DATA_HOME),
    %LOCALAPPDATA%\\theoricum (Windows), ~/Library/Application Support/theoricum (macOS)."""
    return Path(user_data_dir(APP_NAME, appauthor=False))


@dataclass(frozen=True, slots=True)
class Paths:
    questions_dir: Path
    data_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_FILENAME


def resolve_paths(
    questions_dir: str | os.PathLike[str] | None = None,
    data_dir: str | os.PathLike[str] | None = None,
) -> Paths:
    """Resolve paths: explicit flag > environment variable > ./questions > per-user data folder."""
    if questions_dir is None:
        questions_dir = os.environ.get("THEORICUM_QUESTIONS")
    if questions_dir is None:
        local = Path.cwd() / "questions"
        questions_dir = local if local.is_dir() else default_data_dir() / "questions"
    if data_dir is None:
        data_dir = os.environ.get("THEORICUM_DATA") or default_data_dir()
    return Paths(
        questions_dir=Path(questions_dir).expanduser().resolve(),
        data_dir=Path(data_dir).expanduser().resolve(),
    )
