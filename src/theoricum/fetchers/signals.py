"""Sign questions built from the official catalogue of traffic signs (RD 465/2025, BOE).

The annex of Real Decreto 465/2025 (BOE-A-2025-12199) is the catalogue: every vertical sign
(P- warning, R- regulatory, S- information) with its code, its official name, its meaning and its
picture. The BOE PDF is downloaded, read with pypdf and turned into «¿Qué indica esta señal?»
questions: the right option is the official name and the two wrong ones are the names of nearby
signs of the same section (usually its siblings, e.g. «…a la derecha» vs «…a la izquierda»).

Legal texts are not subject to copyright in Spain (art. 13 LPI) and the BOE allows reusing its
content citing the source; still, like every pack, the result lives only in questions/signals/.

The PDF is immutable, but its layout is handled defensively. Positioned text chunks tell which
lines start a sign (code column + name column) and where its name ends, and every sign gets the
image drawn in its table row. The wording comes from pypdf's plain text, which has the right
spacing. Signs without an image are skipped and reported.
"""

import hashlib
import json
import logging
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from theoricum.fetchers.http import HttpClient
from theoricum.fetchers.revista_dgt import clean_text
from theoricum.importers.base import dedup_key
from theoricum.models import FORMAT_ID, LETTERS
from theoricum.topics import normalize_text

BOE_URL = "https://www.boe.es/boe/dias/2025/06/17/pdfs/BOE-A-2025-12199.pdf"
BOE_ID = "BOE-A-2025-12199"
PACK_DIR = "signals"
PACK_ID = "signals-rd465"
PACK_DATE = "2025-06-17"  # BOE publication date
QUESTION = "¿Qué indica esta señal?"
# The law itself: above the magazine (90), below the literal exam questions of the official
# simulator (100). Only used to pick a copy when the same question is in several sources.
PACK_META = {
    "id": PACK_ID,
    "name": "Catálogo oficial de señales (RD 465/2025)",
    "origin": "otro",
    "priority": 95,
    "date": PACK_DATE,
}
ATTRIBUTION = (
    "Catálogo oficial de señales de circulación, anexo del Real Decreto 465/2025 "
    f"({BOE_ID}, BOE del 17-6-2025). Fuente: Agencia Estatal Boletín Oficial del Estado."
)

HEADER_Y = 740.0  # the BOE header (title, issue, page number) is above this line
SAME_LINE = 2.5  # points: chunks closer than this vertically belong to the same line
NAME_INDENT = 30.0  # points: the name column starts this far right of the code column
ROW_ABOVE_CODE = 12.0  # points: a table row starts this far above the baseline of its code

Log = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class Chunk:
    x: float
    y: float
    text: str


@dataclass(frozen=True, slots=True)
class ImageBox:
    path: tuple[str, ...]  # XObject names, from the page resources down to the image
    bottom: float
    top: float


@dataclass(slots=True)
class Sign:
    code: str
    name: str
    section: str
    y: float = 0.0
    page: int = 0
    meaning: str = ""
    image: ImageBox | None = None


@dataclass(slots=True)
class Line:
    x: float
    y: float
    text: str
    parts: list[Chunk] = field(default_factory=list)


@dataclass(slots=True)
class SignalsReport:
    signs: int = 0
    questions: int = 0
    skipped: list[str] = field(default_factory=list)
    pack_path: Path | None = None
    already: bool = False
    meta_updated: bool = False  # an existing pack got the current [pack] settings


# --- page structure (positioned chunks) --------------------------------------------------------
#
# Positions tell which lines start a sign (code column + name column), where its name ends and
# which image is in its row. They cannot tell where the spaces go (the BOE justifies its text and
# splits words into chunks), so the final wording comes from pypdf's plain text: see `refine`.


def group_lines(chunks: list[Chunk]) -> list[Line]:
    """Merge positioned text chunks into lines, top to bottom (PDF y grows upwards)."""
    lines: list[list[Chunk]] = []
    for chunk in sorted(chunks, key=lambda c: (-c.y, c.x)):
        if lines and abs(lines[-1][0].y - chunk.y) <= SAME_LINE:
            lines[-1].append(chunk)
        else:
            lines.append([chunk])
    result = []
    for parts in lines:
        parts.sort(key=lambda c: c.x)
        text = clean_text(" ".join(p.text for p in parts))
        result.append(Line(parts[0].x, max(p.y for p in parts), text, parts))
    return result


def split_code(line: Line) -> tuple[str, str] | None:
    """(code, name) if the line is the first row of a sign: the code alone in the code column
    and the name in the name column. A meaning that starts with a code is not one."""
    head = [p for p in line.parts if p.x < line.x + NAME_INDENT]
    tail = [p for p in line.parts if p.x >= line.x + NAME_INDENT]
    code = re.sub(r"\s+", "", "".join(p.text for p in head))
    if tail and re.fullmatch(r"[PRS]-\d+", code) and re.fullmatch(r"[a-z]", tail[0].text):
        code, tail = code + tail[0].text, tail[1:]  # the variant letter («R-308d») is set apart
    if not tail or not re.fullmatch(r"[PRS]-\d+[a-z]?", code):
        return None
    return code, clean_text(" ".join(p.text for p in tail))


def _is_heading(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    return len(letters) >= 4 and all(not ch.islower() for ch in letters)


def parse_lines(lines: list[Line], page: int, section: str) -> list[Sign]:
    """The signs that start on a page, with their name (it may wrap) and section."""
    signs: list[Sign] = []
    current: Sign | None = None
    code_x = None
    for line in lines:
        if _is_heading(line.text):
            section = line.text.strip()
        elif found := split_code(line):
            current = Sign(found[0], found[1], section, line.y, page)
            signs.append(current)
            code_x = line.x
        elif current is not None and code_x is not None:
            if line.x >= code_x + NAME_INDENT and not current.meaning:
                current.name = f"{current.name} {line.text}"  # the name wraps
            else:
                current.meaning = "…"  # the meaning has started; its text comes from `refine`
    return signs


def match_images(signs: list[Sign], boxes: list[ImageBox]) -> None:
    """Give every sign of a page the image drawn in its table row: the row starts just above its
    code and ends at the next code (the picture is centered in the row, whatever its shape)."""
    ordered = sorted(signs, key=lambda s: -s.y)
    for k, sign in enumerate(ordered):
        top = sign.y + ROW_ABOVE_CODE
        bottom = ordered[k + 1].y + ROW_ABOVE_CODE if k + 1 < len(ordered) else 0.0
        inside = [b for b in boxes if bottom <= (b.bottom + b.top) / 2 <= top]
        if inside:  # the biggest one, in case a row also holds a small pictogram
            sign.image = max(inside, key=lambda b: b.top - b.bottom)


# --- wording (pypdf plain text) ----------------------------------------------------------------

_NOISE_RE = re.compile(r"^(BOLET[IÍ]N OFICIAL DEL ESTADO|N[uú]m\. ?\d+|cve: |Verificable en)")


def plain_lines(text: str) -> str:
    """The plain text of a page without the BOE header, the side note and table headings."""
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(ln for ln in lines if ln and not _NOISE_RE.match(ln) and not _is_heading(ln))


def code_regex(code: str) -> re.Pattern[str]:
    """Where a code starts a line of the plain text («R-308» must not match «R-308 d …»)."""
    letter, digits, variant = re.fullmatch(r"([PRS])-(\d+)([a-z]?)", code).groups()  # type: ignore[union-attr]
    tail = rf"\s*{variant}(?![A-Za-z])" if variant else r"(?!\d|\s*[a-z]\s)"
    return re.compile(rf"(?m)^{letter}\s*-\s*{digits}{tail}")


def _squeeze(text: str) -> str:
    return re.sub(r"\s+", "", text)


def refine(signs: list[Sign], text: str, previous: Sign | None) -> None:
    """Take the name and meaning of each sign of a page from its plain text, which has the right
    spacing. The text before the first code continues the meaning of `previous` (the last sign
    of the previous page). If a sign cannot be aligned, its positioned wording is kept."""
    text = plain_lines(text)
    found = []
    pos = 0
    for sign in signs:
        m = code_regex(sign.code).search(text, pos)
        found.append(m)
        if m:
            pos = m.end()
    first = next((m.start() for m in found if m), len(text))
    if previous is not None and text[:first].strip():
        previous.meaning = clean_text(f"{previous.meaning} {' '.join(text[:first].split())}")
    for k, (sign, m) in enumerate(zip(signs, found, strict=True)):
        if m is None:
            sign.meaning = ""
            continue
        end = next((n.start() for n in found[k + 1 :] if n), len(text))
        segment = text[m.end() : end]
        name = _squeeze(sign.name)
        if not _squeeze(segment).startswith(name):
            sign.meaning = ""
            continue
        cut, seen = 0, 0
        while seen < len(name):  # walk the segment until the name (without spaces) is consumed
            seen += not segment[cut].isspace()
            cut += 1
        sign.name = clean_text(" ".join(segment[:cut].split())).rstrip(" .")
        sign.meaning = clean_text(" ".join(segment[cut:].split()))


_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")


def heal_split_words(signs: list[Sign]) -> None:
    """Rejoin the few words the justified PDF text splits in two («po r tanto», «ca rriles»).

    Two neighbouring fragments are joined only if the result is a word used elsewhere in the
    catalogue and both fragments are rare on their own, or one is a single letter and the other
    is rare («d el», «izquierd a»). So «de tener» or «se ve» are left alone."""
    counts: dict[str, int] = {}
    for sign in signs:
        for word in _WORD_RE.findall(f"{sign.name} {sign.meaning}"):
            counts[word.lower()] = counts.get(word.lower(), 0) + 1

    def fix(text: str) -> str:
        words = text.split(" ")
        i = 0
        while i < len(words) - 1:
            a, b = words[i], words[i + 1]
            m = re.match(r"[a-záéíóúüñ]+", b)
            if a.isalpha() and m:
                core = m.group(0)
                rare_a, rare_b = counts.get(a.lower(), 0) <= 2, counts.get(core, 0) <= 2
                letter = len(a) == 1 or len(core) == 1
                plausible = (rare_a and rare_b) or (letter and (rare_a or rare_b))
                if plausible and counts.get((a + core).lower(), 0) >= 1:
                    words[i : i + 2] = [a + b]
                    continue
            i += 1
        return " ".join(words)

    for sign in signs:
        sign.name, sign.meaning = fix(sign.name), fix(sign.meaning)


# --- PDF reading (pypdf) -----------------------------------------------------------------------


def _image_paths(page) -> dict[str, tuple[str, ...]]:
    """Name of every image XObject of a page (also inside form XObjects) -> its path."""
    paths: dict[str, tuple[str, ...]] = {}

    def walk(resources, prefix: tuple[str, ...]) -> None:
        xobjects = resources.get("/XObject") if resources else None
        for name, ref in (xobjects or {}).items():
            obj = ref.get_object()
            subtype = obj.get("/Subtype")
            if subtype == "/Image":
                paths.setdefault(str(name), (*prefix, str(name)))
            elif subtype == "/Form":
                walk(obj.get("/Resources"), (*prefix, str(name)))

    walk(page.get("/Resources"), ())
    return paths


def read_page(page) -> tuple[list[Chunk], list[ImageBox]]:
    chunks: list[Chunk] = []
    boxes: list[ImageBox] = []
    paths = _image_paths(page)

    def on_text(text, cm, tm, font, size) -> None:
        if not text.strip() or tm[0] * cm[0] == 0:  # empty, or rotated (the side «cve» note)
            return
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        if y < HEADER_Y:
            chunks.append(Chunk(x, y, text.strip()))

    def on_operator(operator, operands, cm, tm) -> None:
        if operator == b"Do" and operands and str(operands[0]) in paths:
            bottom, height = cm[5], cm[3]
            if bottom < HEADER_Y:  # not the BOE logos
                boxes.append(ImageBox(paths[str(operands[0])], bottom, bottom + height))

    page.extract_text(visitor_text=on_text, visitor_operand_before=on_operator)
    return chunks, boxes


def parse_catalogue(pdf_path: Path, log: Log) -> tuple[list[Sign], list]:
    """All the signs of the catalogue, with their image; also returns the pypdf pages."""
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # font warnings irrelevant here
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    signs: list[Sign] = []
    section = ""
    started = False
    empty_pages = 0
    for index, page in enumerate(reader.pages):
        chunks, boxes = read_page(page)
        lines = group_lines(chunks)
        page_signs = parse_lines(lines, index, section)
        section = next((ln.text for ln in reversed(lines) if _is_heading(ln.text)), section)
        if page_signs:
            started, empty_pages = True, 0
            refine(page_signs, page.extract_text(), signs[-1] if signs else None)
            match_images(page_signs, boxes)
            signs.extend(page_signs)
        elif started:
            empty_pages += 1
            if empty_pages >= 6:  # the vertical signs are over (road markings follow)
                break
        if index % 20 == 0:
            log(f"  página {index + 1} de {len(reader.pages)}: {len(signs)} señales")
    for sign in signs:
        sign.name = sign.name.rstrip(" .")
    heal_split_words(signs)
    return signs, reader.pages


def image_bytes(pages, sign: Sign) -> tuple[bytes, str]:
    """The original image file of a sign (JPEG as embedded, PNG otherwise) and its extension."""
    assert sign.image is not None
    path = sign.image.path
    found = pages[sign.page].images[list(path) if len(path) > 1 else path[0]]
    suffix = Path(found.name).suffix.lower() or ".png"
    return found.data, ".jpg" if suffix in (".jpg", ".jpeg") else suffix


# --- questions ---------------------------------------------------------------------------------


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", normalize_text(text)).split())


def candidates(signs: list[Sign], index: int) -> list[str]:
    """Names of the other signs of the same section, nearest first (siblings first), all
    different from each other and from the sign's own name."""
    target = signs[index]
    seen = {_norm(target.name)}
    found: list[str] = []
    for distance in range(1, len(signs)):
        for j in (index - distance, index + distance):
            if not 0 <= j < len(signs) or signs[j].section != target.section:
                continue
            if _norm(signs[j].name) not in seen:
                seen.add(_norm(signs[j].name))
                found.append(signs[j].name)
    return found


def distractors(signs: list[Sign], index: int, used: set[str] | None = None) -> list[str]:
    """The two nearest names that make a set of options no other sign has: «¿Qué indica esta
    señal?» with the same three options would count as the same question (see `dedup_key`)."""
    names = candidates(signs, index)
    pairs = sorted(
        ((i, j) for i in range(len(names)) for j in range(i + 1, len(names))),
        key=lambda pair: (pair[0] + pair[1], pair[1]),
    )
    for i, j in pairs:
        if used is None or dedup_key(QUESTION, (signs[index].name, names[i], names[j])) not in used:
            return [names[i], names[j]]
    return names[:2]


def build_question(sign: Sign, wrong: list[str], image: str) -> dict:
    """The options never change between runs: their order depends only on the code."""
    options = [sign.name, *wrong]
    shift = int(hashlib.sha1(sign.code.encode()).hexdigest(), 16) % len(options)
    options = options[shift:] + options[:shift]
    explanation = f"{sign.code} · {sign.name}."
    if sign.meaning:
        explanation += f" {sign.meaning}"
    return {
        "id": sign.code,
        "text": QUESTION,
        "image": image,
        "options": options,
        "answer": LETTERS[options.index(sign.name)],
        "topic": "senales",
        "date": PACK_DATE,
        "explanation": explanation,
        "tags": [sign.code.split("-")[0], sign.section.capitalize()],
        "source": f"Catálogo oficial de señales (RD 465/2025, {BOE_ID})",
    }


def fetch_signals(
    questions_dir: Path,
    *,
    refresh: bool = False,
    http: HttpClient | None = None,
    log: Log = print,
    pdf_path: Path | None = None,
) -> SignalsReport:
    """Build questions/signals/ from the BOE. `pdf_path` uses a local copy instead."""
    report = SignalsReport()
    pack_dir = questions_dir / PACK_DIR
    pack_path = pack_dir / "pack.json"
    report.pack_path = pack_path
    if pack_path.is_file() and not refresh:
        data = json.loads(pack_path.read_text(encoding="utf-8"))
        report.already = True
        report.questions = len(data.get("questions", []))
        if data.get("pack") != PACK_META:  # e.g. a new priority: no need to download it again
            _write_pack(pack_path, data.get("questions", []))
            report.meta_updated = True
        return report

    with tempfile.TemporaryDirectory(prefix="theoricum-boe-") as tmp:
        if pdf_path is None:
            pdf_path = Path(tmp) / f"{BOE_ID}.pdf"
            log("Descargando el BOE del RD 465/2025 (unos 27 MB)…")
            if not (http or HttpClient()).download(BOE_URL, pdf_path):
                raise ConnectionError(f"no se pudo descargar {BOE_URL}")
        log("Leyendo el catálogo de señales…")
        signs, pages = parse_catalogue(pdf_path, log)
        report.signs = len(signs)

        img_dir = pack_dir / "img"
        img_dir.mkdir(parents=True, exist_ok=True)
        questions = []
        used: set[str] = set()
        for index, sign in enumerate(signs):
            wrong = distractors(signs, index, used)
            if sign.image is None:
                report.skipped.append(f"{sign.code} ({sign.name}): sin imagen")
                continue
            if len(wrong) < 2:
                report.skipped.append(f"{sign.code} ({sign.name}): sin opciones para confundir")
                continue
            data, suffix = image_bytes(pages, sign)
            name = f"{sign.code}{suffix}"
            (img_dir / name).write_bytes(data)
            questions.append(build_question(sign, wrong, f"img/{name}"))
            used.add(dedup_key(QUESTION, (sign.name, *wrong)))
    kept = {Path(q["image"]).name for q in questions}
    for stale in img_dir.iterdir():
        if stale.is_file() and stale.name not in kept:
            stale.unlink()
    _write_pack(pack_path, questions)
    report.questions = len(questions)
    return report


def _write_pack(pack_path: Path, questions: list[dict]) -> None:
    document = {
        "format": FORMAT_ID,
        "pack": PACK_META,
        "attribution": ATTRIBUTION,
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "questions": questions,
    }
    tmp = pack_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(pack_path)
