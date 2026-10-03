"""Filesystem locations (questions folder and personal data)."""

import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "theoricum"
DB_FILENAME = "theoricum.db"


def xdg_data_home() -> Path:
    value = os.environ.get("XDG_DATA_HOME")
    return Path(value) if value else Path.home() / ".local" / "share"


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
    """Resolve paths: explicit flag > environment variable > ./questions > XDG."""
    if questions_dir is None:
        questions_dir = os.environ.get("THEORICUM_QUESTIONS")
    if questions_dir is None:
        local = Path.cwd() / "questions"
        questions_dir = local if local.is_dir() else xdg_data_home() / APP_NAME / "questions"
    if data_dir is None:
        data_dir = os.environ.get("THEORICUM_DATA") or xdg_data_home() / APP_NAME
    return Paths(
        questions_dir=Path(questions_dir).expanduser().resolve(),
        data_dir=Path(data_dir).expanduser().resolve(),
    )
