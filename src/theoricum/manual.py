"""The DGT manual downloaded with `dgt fetch manual` (see fetchers/manual.py): which topic of the
manual goes with each theoricum topic, and opening a PDF in the system viewer."""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from theoricum.fetchers.manual import ANNEX, FOLDER, INDEX, Chapter
from theoricum.topics import SpanishTopicName, slugify, topic_from_cli

# theoricum topic (data/topics.toml) -> topic of the DGT manual where it is explained.
TOPIC_CHAPTERS = {
    "senales": 8,
    "velocidad": 10,
    "prioridad": 12,
    "adelantamiento": 11,
    "maniobras": 11,
    "estacionamiento": 11,
    "alumbrado": 7,
    "vias": 9,
    "distancias": 10,
    "documentacion": 2,
    "carga": 13,
    "seguridad": 5,
    "alcohol": 3,
    "riesgos": 14,
    "vulnerables": 4,
    "mecanica": 15,
    "accidentes": 16,
    "medioambiente": 17,
}
POINTS = "points"  # the points annex on the command line


@dataclass(frozen=True, slots=True)
class Manual:
    folder: Path
    title: str
    date: str
    url: str
    full: Path
    chapters: tuple[Chapter, ...]

    def chapter(self, number: int) -> Chapter | None:
        return next((c for c in self.chapters if c.number == number), None)

    def path(self, chapter: Chapter) -> Path:
        return self.folder / chapter.file

    def for_topic(self, topic: str | None) -> Chapter | None:
        number = TOPIC_CHAPTERS.get(topic or "")
        return self.chapter(number) if number else None

    def find(self, value: str) -> Chapter | None:
        """A topic as written on the command line (English): its number (8), a theoricum topic
        (signals, speed…) or `points` for the points annex. Spanish names raise
        `SpanishTopicName` with the English one."""
        value = value.strip()
        if value.isdigit():
            return self.chapter(int(value))
        if slugify(value) == POINTS:
            return self.chapter(ANNEX)
        if slugify(value) in ("puntos", "anexo"):
            raise SpanishTopicName(value, POINTS)
        return self.for_topic(topic_from_cli(value))


def manual_dir(data_dir: Path) -> Path:
    return data_dir / FOLDER


def load_manual(data_dir: Path) -> Manual | None:
    """The downloaded manual, or None if it is not there (or incomplete)."""
    folder = manual_dir(data_dir)
    try:
        document = json.loads((folder / INDEX).read_text(encoding="utf-8"))
        chapters = tuple(Chapter(**c) for c in document["chapters"])
        manual = Manual(
            folder=folder,
            title=document["title"],
            date=document["date"],
            url=document["url"],
            full=folder / document["full"],
            chapters=chapters,
        )
    except OSError, ValueError, KeyError, TypeError:
        return None
    if not manual.full.is_file() or not all(manual.path(c).is_file() for c in chapters):
        return None
    return manual


def viewer_command(path: Path, platform: str = sys.platform) -> list[str] | None:
    """The command that opens a file with the default application (None on Windows, where
    `os.startfile` does it)."""
    if platform.startswith("win"):
        return None
    if platform == "darwin":
        return ["open", str(path)]
    return ["xdg-open", str(path)]  # Linux and the BSDs


def open_document(path: Path) -> None:
    """Open a file with the system's default viewer, without waiting for it. Raises OSError
    (with a Spanish message) if there is no way to open it."""
    command = viewer_command(path)
    if command is None:
        os.startfile(path)  # type: ignore[attr-defined]  # only exists on Windows
        return
    try:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # the viewer must not die with the terminal or the TUI
        )
    except FileNotFoundError as exc:
        raise OSError(f"no encuentro «{command[0]}» para abrir {path}") from exc
