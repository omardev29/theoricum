"""Traffic law from the BOE consolidated legislation API (`dgt fetch laws`).

Each law comes in one request with every article and **all its historical versions**; the
version in force today is kept (an article whose first version is still to come is kept with its
date, marked as future). Articles remember the title/chapter they belong to. The result goes to
`<data dir>/laws/<slug>.json`, never to a questions folder: it is reference, not questions.
"""

import json
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from theoricum.fetchers.http import HttpClient

API = "https://www.boe.es/datosabiertos/api/legislacion-consolidada/id/{id}/{part}"
ACCEPT_XML = {"Accept": "application/xml"}  # the API answers 400 without it
FOLDER = "laws"
FORMAT = "theoricum-laws/1"

Log = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class Law:
    slug: str
    boe_id: str
    name: str

    @property
    def url(self) -> str:
        return f"https://www.boe.es/buscar/act.php?id={self.boe_id}"


LAWS = (
    Law("rgc", "BOE-A-2003-23514", "Reglamento General de Circulación"),
    Law("lsv", "BOE-A-2015-11722", "Ley sobre Tráfico y Seguridad Vial"),
    Law("rgcond", "BOE-A-2009-9481", "Reglamento General de Conductores"),
    Law("rgv", "BOE-A-1999-1826", "Reglamento General de Vehículos"),
)


@dataclass(slots=True)
class Article:
    id: str
    title: str  # «Artículo 48. Velocidades máximas en vías fuera de poblado.»
    section: str  # the title and chapter it belongs to
    text: str
    in_force: str  # YYYY-MM-DD of the version kept
    future: bool = False  # not in force yet (no earlier version exists)
    notes: str = ""  # the BOE's notes on where the wording comes from («Se modifica por…»)


@dataclass(slots=True)
class LawsReport:
    laws: list[tuple[str, int, str]] = field(default_factory=list)  # (name, articles, updated)
    folder: Path | None = None


def _parse(xml: str) -> ET.Element:
    try:
        return ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError(f"el BOE no ha devuelto un XML válido: {exc}") from exc


def _iso(value: str | None) -> str:
    value = (value or "")[:8]
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}" if len(value) == 8 else ""


def _element_text(element: ET.Element) -> str:
    if element.tag == "table":
        rows = []
        for row in element.iter("tr"):
            cells = [" ".join("".join(c.itertext()).split()) for c in row if c.tag in ("td", "th")]
            rows.append(" | ".join(c for c in cells if c))
        return "\n".join(r for r in rows if r)
    if element.get("class") == "imagen":
        return "[imagen: consúltala en el BOE]"
    return " ".join("".join(element.itertext()).split())


def _pick_version(block: ET.Element, today: str) -> tuple[ET.Element, bool] | None:
    versions = sorted(block.iter("version"), key=lambda v: v.get("fecha_vigencia") or "")
    if not versions:
        return None
    current = [v for v in versions if (v.get("fecha_vigencia") or "") <= today]
    return (current[-1], False) if current else (versions[0], True)


def parse_law(xml: str, today: str | None = None) -> list[Article]:
    """The articles of a consolidated text, each in the version in force on `today` (YYYYMMDD)."""
    today = today or date.today().strftime("%Y%m%d")
    root = _parse(xml)
    articles: list[Article] = []
    headings: list[tuple[int, str]] = []  # the open ANEXO/TÍTULO > CAPÍTULO > SECCIÓN
    for block in root.iter("bloque"):
        picked = _pick_version(block, today)
        if picked is None:
            continue
        version, future = picked
        paragraphs = [t for e in version if e.tag != "blockquote" and (t := _element_text(e))]
        notes = [
            t
            for quote in version.iter("blockquote")
            for e in quote
            if e.get("class") != "imagen" and (t := _element_text(e))
        ]
        if block.get("tipo") == "encabezado":
            level = str(block.get("titulo") or "").split(" ")[0].upper()
            rank = LEVELS.get(level)
            if rank is not None:  # not, e.g., the name of the law itself
                headings = [h for h in headings if h[0] < rank]
                headings.append((rank, " ".join(paragraphs) or str(block.get("titulo"))))
            continue
        if block.get("tipo") != "precepto" or not paragraphs:
            continue
        first = paragraphs[0]
        title = first if first.lower().startswith(("artículo", "disposición", "anexo")) else ""
        body = paragraphs[1:] if title else paragraphs
        articles.append(
            Article(
                id=str(block.get("id")),
                title=title or str(block.get("titulo") or ""),
                section=" · ".join(text for _, text in headings),
                text="\n\n".join(body),
                in_force=_iso(version.get("fecha_vigencia")),
                future=future,
                notes="\n".join(notes),
            )
        )
    return articles


LEVELS = {"ANEXO": 0, "TÍTULO": 0, "CAPÍTULO": 1, "SECCIÓN": 2}


def _updated(xml: str | None) -> str:
    if not xml:
        return ""
    root = _parse(xml)
    found = root.find(".//fecha_actualizacion")
    return _iso(found.text if found is not None else None)


def fetch_laws(data_dir: Path, *, http: HttpClient | None = None, log: Log = print) -> LawsReport:
    http = http or HttpClient(delay=1.0)
    folder = data_dir / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    report = LawsReport(folder=folder)
    for law in LAWS:
        log(f"Descargando {law.name} ({law.boe_id})…")
        meta = http.get_text(API.format(id=law.boe_id, part="metadatos"), headers=ACCEPT_XML)
        text = http.get_text(API.format(id=law.boe_id, part="texto"), headers=ACCEPT_XML)
        if text is None:
            raise ConnectionError(f"el BOE no tiene el texto de {law.boe_id}")
        articles = parse_law(text)
        updated = _updated(meta)
        document = {
            "format": FORMAT,
            "law": {**asdict(law), "url": law.url, "updated": updated},
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "articles": [asdict(a) for a in articles],
        }
        target = folder / f"{law.slug}.json"
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(document, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(target)
        report.laws.append((law.name, len(articles), updated))
    return report
