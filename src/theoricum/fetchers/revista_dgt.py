"""Download the tests published by the DGT magazine «Tráfico y Seguridad Vial» (revista.dgt.es).

The magazine allows reproducing its texts if it is cited as the source; its images may only be
used for personal, private study. Everything is written to questions/revista-dgt/ (never
committed) as a native `theoricum/1` pack.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from theoricum.fetchers.http import HttpClient
from theoricum.models import FORMAT_ID, LETTERS

BASE_URL = "https://revista.dgt.es"
INDEX_URL = f"{BASE_URL}/es/test/"
FIRST_TEST = 224  # Older test pages do not exist (checked on 2026-10-03).
PACK_DIR = "revista-dgt"
ATTRIBUTION = "Revista «Tráfico y Seguridad Vial» (DGT) — https://revista.dgt.es/es/test/"

MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}  # fmt: skip

Log = Callable[[str], None]


def test_url(number: int) -> str:
    return f"{BASE_URL}/es/test/Test-num-{number}.shtml"


@dataclass(slots=True)
class ParsedQuestion:
    position: int
    text: str
    options: list[str]
    answer: int
    explanation: str | None
    image_url: str | None


@dataclass(slots=True)
class ParsedTest:
    number: int
    label: str
    date: str | None
    questions: list[ParsedQuestion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FetchReport:
    tests_fetched: list[int] = field(default_factory=list)
    tests_missing: list[int] = field(default_factory=list)
    questions_added: int = 0
    images_failed: int = 0
    warnings: list[str] = field(default_factory=list)
    pack_path: Path | None = None
    total_questions: int = 0


def url_suffix(url: str, default: str = ".jpg") -> str:
    """File extension of a URL (URLs are POSIX paths on every platform)."""
    return PurePosixPath(urlparse(url).path).suffix.lower() or default


def clean_text(text: str) -> str:
    """Collapse whitespace; inline tags joined with spaces leave gaps before punctuation."""
    text = " ".join(text.split())
    text = re.sub(r"([¿¡(«]) ", r"\1", text)
    return re.sub(r" ([,.;:!?)»])", r"\1", text)


def parse_date(label: str, image_urls: list[str]) -> str | None:
    """Turn labels such as «Junio 2026», «Julio-2015» or «Marzo-abril 2014» into YYYY-MM."""
    lowered = label.lower()
    year = re.search(r"(19|20)\d{2}", lowered)
    month = next((MONTHS[m] for m in re.findall(r"[a-záéíóú]+", lowered) if m in MONTHS), None)
    if year and month:
        return f"{year.group(0)}-{month:02d}"
    for url in image_urls:  # Old image folders are named YYYYMM.
        if m := re.search(r"/((?:19|20)\d{2})(0[1-9]|1[0-2])/", url):
            return f"{m.group(1)}-{m.group(2)}"
    return year.group(0) if year else None


def _parse_article(article: Tag, position: int) -> ParsedQuestion:
    title = article.select_one("h4.tit_not")
    if title is None:
        raise ValueError("sin enunciado")
    text = re.sub(r"^\s*\d+\s*[.)-]\s*", "", clean_text(title.get_text(" ")))

    options = []
    for li in article.select("section.content_test > ul > li"):
        span = li.select_one("span.opcion")
        if span is not None:
            span.extract()
        option = clean_text(li.get_text(" "))
        if option:
            options.append(option)
    if not 2 <= len(options) <= len(LETTERS):
        raise ValueError(f"{len(options)} opciones")

    answer_box = article.select_one("div.content_respuesta")
    letter_tag = answer_box.select_one("span.opcion") if answer_box else None
    letter = clean_text(letter_tag.get_text()).rstrip(".").upper() if letter_tag else ""
    if len(letter) != 1 or LETTERS.find(letter) >= len(options) or LETTERS.find(letter) < 0:
        raise ValueError(f"respuesta «{letter}» no reconocida")

    explanation_parts = []
    assert answer_box is not None
    for p in answer_box.find_all("p")[1:]:
        part = clean_text(p.get_text(" "))
        if part and part.upper().rstrip(":") not in {"CON MÁS DETALLE", "CON MAS DETALLE"}:
            explanation_parts.append(part)

    img = article.select_one("figure img[src]")
    image_url = urljoin(BASE_URL, str(img["src"])) if img else None
    return ParsedQuestion(
        position=position,
        text=text,
        options=options,
        answer=LETTERS.find(letter),
        explanation="\n".join(explanation_parts) or None,
        image_url=image_url,
    )


def parse_test_page(html: str, number: int) -> ParsedTest:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    label = clean_text(h1.get_text(" ")) if h1 else ""
    if not label and soup.title:
        label = clean_text(soup.title.get_text())
    articles = soup.select("article.test")
    image_urls = [str(img["src"]) for img in soup.select("article.test figure img[src]")]
    test = ParsedTest(number=number, label=label, date=parse_date(label, image_urls))
    for position, article in enumerate(articles, start=1):
        try:
            test.questions.append(_parse_article(article, position))
        except ValueError as exc:
            test.warnings.append(f"test {number}, pregunta {position}: {exc}; se omite")
    return test


def related_tests(html: str) -> list[int]:
    soup = BeautifulSoup(html, "html.parser")
    numbers = []
    for a in soup.select("section#enlaces_relacionados a[href]"):
        if m := re.search(r"Test-num-(\d+)\.shtml", str(a["href"])):
            numbers.append(int(m.group(1)))
    return numbers


def discover_latest(http: HttpClient) -> int:
    """The index shows the current test and links to the previous ones; probe forward from there."""
    index = http.get_text(INDEX_URL)
    known = related_tests(index or "")
    latest = max(known, default=FIRST_TEST)
    misses = 0
    candidate = latest + 1
    while misses < 2:
        if http.exists(test_url(candidate)):
            latest, misses = candidate, 0
        else:
            misses += 1
        candidate += 1
    return latest


def _load_existing(pack_path: Path) -> dict:
    if pack_path.is_file():
        with pack_path.open(encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def fetch_revista(
    questions_dir: Path,
    *,
    refresh: bool = False,
    http: HttpClient | None = None,
    log: Log = print,
) -> FetchReport:
    http = http or HttpClient()
    report = FetchReport()
    pack_dir = questions_dir / PACK_DIR
    img_dir = pack_dir / "img"
    img_dir.mkdir(parents=True, exist_ok=True)
    pack_path = pack_dir / "pack.json"
    existing = {} if refresh else _load_existing(pack_path)
    questions: list[dict] = list(existing.get("questions", []))
    done_tests = set() if refresh else set(existing.get("fetched", {}).get("tests", []))

    log("Buscando el último test publicado…")
    latest = discover_latest(http)
    pending = [n for n in range(FIRST_TEST, latest + 1) if n not in done_tests]
    log(f"Último test: {latest}. Tests por descargar: {len(pending)}.")

    for i, number in enumerate(pending, start=1):
        html = http.get_text(test_url(number))
        if html is None:
            report.tests_missing.append(number)
            log(f"[{i}/{len(pending)}] test {number}: no existe")
            continue
        test = parse_test_page(html, number)
        report.warnings.extend(test.warnings)
        questions = [q for q in questions if f"revista-{number}" not in q.get("tags", [])]
        for q in test.questions:
            qid = f"t{number}-q{q.position:02d}"
            entry = {
                "id": qid,
                "text": q.text,
                "options": q.options,
                "answer": LETTERS[q.answer],
                "date": test.date,
                "tags": [f"revista-{number}"],
                "source": test_url(number),
            }
            if q.explanation:
                entry["explanation"] = q.explanation
            if q.image_url:
                image_name = f"{qid}{url_suffix(q.image_url)}"
                target = img_dir / image_name
                if target.is_file() or http.download(q.image_url, target, delay=0.5):
                    entry["image"] = f"img/{image_name}"
                else:
                    report.images_failed += 1
            questions.append(entry)
            report.questions_added += 1
        done_tests.add(number)
        report.tests_fetched.append(number)
        log(
            f"[{i}/{len(pending)}] test {number} ({test.label or '¿?'}): {len(test.questions)} preguntas"
        )
        _write_pack(pack_path, questions, done_tests)  # Save progress after every test.

    _write_pack(pack_path, questions, done_tests)
    report.pack_path = pack_path
    report.total_questions = len(questions)
    return report


def _sort_key(entry: dict) -> tuple[int, str]:
    m = re.match(r"t(\d+)-q(\d+)", entry["id"])
    return (int(m.group(1)), m.group(2)) if m else (0, entry["id"])


def _write_pack(pack_path: Path, questions: list[dict], done_tests: set[int]) -> None:
    document = {
        "format": FORMAT_ID,
        "pack": {
            "id": "revista-dgt",
            "name": "Revista DGT · Tests",
            "origin": "revista-dgt",
            "priority": 90,
        },
        "attribution": ATTRIBUTION,
        "fetched": {
            "tests": sorted(done_tests),
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "questions": sorted(questions, key=_sort_key),
    }
    tmp = pack_path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(document, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    tmp.replace(pack_path)
