"""The DGT manual for permit B (`dgt fetch manual`).

«Manual del Permiso B en Lectura Fácil» (DGT, December 2023): the 17 topics of the permit B
syllabus plus the points annex, with links to the DGT's videos. It is downloaded to
`<data dir>/manual/` (personal use, never to the repo nor to a questions folder) and split into
one PDF per topic using the document's bookmarks, so any PDF viewer on any system can open a
topic directly. `index.json` lists the topics.
"""

import json
import logging
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from theoricum.fetchers.http import HttpClient
from theoricum.topics import slugify

URL = (
    "https://www.dgt.es/export/sites/web-DGT/.galleries/downloads/nuestros_servicios/"
    "permisos-de-conducir/Accesibilidad/TeoricaAbreviada_LecturaFacil_2023-12_Interactivo.pdf"
)
TITLE = "Manual del Permiso B en Lectura Fácil (DGT)"
DATE = "2023-12"  # the content; norms after it are in data/changes.toml
FOLDER = "manual"
FULL_NAME = "manual-permiso-b.pdf"
INDEX = "index.json"
FORMAT = "theoricum-manual/1"
ANNEX = 18  # the points annex, after the 17 topics

Log = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class Chapter:
    number: int  # 1-17, ANNEX for the points annex
    title: str
    file: str  # inside the manual folder
    first_page: int  # 1-based, in the full manual
    pages: int


@dataclass(slots=True)
class ManualReport:
    folder: Path
    chapters: list[Chapter] = field(default_factory=list)
    already: bool = False


_TOPIC_RE = re.compile(r"Tema\s+0?(\d{1,2})\s*\.\s*([^\n]+)")
_ANNEX_RE = re.compile(r"Anexo\s+puntos\s*\.\s*([^\n]+)", re.IGNORECASE)


def _title(page_text: str, bookmark: str) -> tuple[int, str] | None:
    """(number, title) of a topic from its first page («Tema 8. Señales de circulación»)."""
    if m := _TOPIC_RE.search(page_text):
        return int(m.group(1)), " ".join(m.group(2).split())
    if m := _ANNEX_RE.search(page_text):
        return ANNEX, " ".join(m.group(1).split())
    if m := re.match(r"Tema\s+0?(\d{1,2})", bookmark):
        return int(m.group(1)), bookmark
    if bookmark.lower().startswith("anexo"):
        return ANNEX, bookmark
    return None


def split_manual(pdf: Path, folder: Path) -> list[Chapter]:
    """One PDF per topic, from the top-level bookmarks «Tema NN» and «Anexo puntos»."""
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(pdf)
    marks = [
        (str(item.title), reader.get_destination_page_number(item))
        for item in reader.outline
        if not isinstance(item, list) and str(item.title).lower().startswith(("tema", "anexo"))
    ]
    chapters: list[Chapter] = []
    for k, (bookmark, start) in enumerate(marks):
        end = marks[k + 1][1] if k + 1 < len(marks) else len(reader.pages)
        found = _title(reader.pages[start].extract_text() or "", bookmark)
        if found is None or end <= start:
            continue
        number, title = found
        name = f"{number:02d}-{slugify(title)[:60]}.pdf"
        writer = PdfWriter()
        for index in range(start, end):
            writer.add_page(reader.pages[index])
        writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
        tmp = folder / (name + ".part")
        with tmp.open("wb") as fh:
            writer.write(fh)
        tmp.replace(folder / name)
        chapters.append(Chapter(number, title, name, start + 1, end - start))
    return chapters


def fetch_manual(
    data_dir: Path, *, refresh: bool = False, http: HttpClient | None = None, log: Log = print
) -> ManualReport:
    folder = data_dir / FOLDER
    report = ManualReport(folder=folder)
    index = folder / INDEX
    if index.is_file() and (folder / FULL_NAME).is_file() and not refresh:
        report.already = True
        report.chapters = [Chapter(**c) for c in json.loads(index.read_text("utf-8"))["chapters"]]
        return report
    folder.mkdir(parents=True, exist_ok=True)
    log(f"Descargando el «{TITLE}» (unos 17 MB)…")
    full = folder / FULL_NAME
    if not (http or HttpClient()).download(URL, full):
        raise ConnectionError(f"no se pudo descargar el manual de la DGT: {URL}")
    log("Separándolo por temas…")
    report.chapters = split_manual(full, folder)
    if not report.chapters:
        raise ValueError("el PDF del manual no tiene los marcadores de los temas")
    kept = {c.file for c in report.chapters} | {FULL_NAME, INDEX}
    for old in folder.glob("*.pdf"):
        if old.name not in kept:
            old.unlink()
    document = {
        "format": FORMAT,
        "title": TITLE,
        "date": DATE,
        "url": URL,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "full": FULL_NAME,
        "chapters": [asdict(c) for c in report.chapters],
    }
    index.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
