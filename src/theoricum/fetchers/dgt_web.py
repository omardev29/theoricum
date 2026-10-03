"""Official practice tests of the DGT online exam simulator (sedeweb.dgt.gob.es).

The simulator is an Apache MyFaces Tobago (JSF) application: every step is a POST of the page
form with `javax.faces.source` set to the id of the clicked button. Buttons are located by
stable classes/suffixes instead of the generated `j_id_*` parts. There are only two or three
questionnaires per permit, so sessions are repeated until no new questions show up.

Each session goes straight to "finalizar examen": the correction view marks the right option
(`…:rbrok`, `boton_correcta.gif`), and «Siguiente» walks through the 30 questions.
"""

import hashlib
import http.cookiejar
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from bs4 import BeautifulSoup, Tag

from theoricum.fetchers.http import HttpClient
from theoricum.fetchers.revista_dgt import clean_text, url_suffix
from theoricum.models import FORMAT_ID, LETTERS
from theoricum.topics import normalize_text

BASE_URL = "https://sedeweb.dgt.gob.es"
START_URL = f"{BASE_URL}/WEB_AUTO-9/examen/Instrucciones.xhtml"
PACK_DIR = "dgt-web"
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) theoricum (practica personal del teórico DGT)"

Log = Callable[[str], None]
ButtonMatcher = Callable[[Tag], bool]


class SimulatorError(Exception):
    """The simulator did not behave as expected (the site probably changed)."""


def _id(tag: Tag) -> str:
    return str(tag.get("id") or "")


def _classes(tag: Tag) -> str:
    value = tag.get("class") or []
    return " ".join(value) if isinstance(value, list) else str(value)


def id_endswith(suffix: str) -> ButtonMatcher:
    return lambda tag: _id(tag).endswith(suffix)


def has_class(fragment: str) -> ButtonMatcher:
    return lambda tag: fragment in _classes(tag)


def permit_b(tag: Tag) -> bool:
    """The «Consultar» button whose own item (smallest container) is labelled «Permiso B»."""
    if "linkConsulta" not in _id(tag):
        return False
    for parent in tag.parents:
        if len(parent.select("button[id*=linkConsulta]")) > 1:
            return False  # Reached a container shared with other permits.
        if re.search(r"\bPermiso B\b", parent.get_text(" ", strip=True)):
            return True
    return False


# Steps from the instructions page to the first question.
SETUP_STEPS: list[tuple[str, ButtonMatcher]] = [
    ("aceptar instrucciones", id_endswith(":btnSumit")),
    ("aceptar aviso", id_endswith(":btnSumit")),
    ("elegir permiso B", permit_b),
    ("entrar", has_class("botonEntrar")),
    ("comenzar", has_class("botoncomenzar")),
    ("no darse de alta en Cl@ve", id_endswith(":btn_comenzar")),
    ("sin lectura fácil", lambda t: "formEntrar" in _id(t)),
]
FINISH = id_endswith(":btnFinExamen")
CONFIRM_FINISH = id_endswith(":finalizarExamenLink")
NEXT_QUESTION = id_endswith(":preguntaSiguiente")


class JsfSession:
    def __init__(self, *, delay: float = 1.0, timeout: float = 30.0) -> None:
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self.opener.addheaders = [("User-Agent", BROWSER_UA)]
        self.delay = delay
        self.timeout = timeout
        self.url = START_URL
        self.soup: BeautifulSoup | None = None
        self._last = 0.0

    def _request(self, url: str, data: dict[str, str] | None = None) -> None:
        pause = self.delay - (time.monotonic() - self._last)
        if pause > 0:
            time.sleep(pause)
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        for attempt in range(3):
            self._last = time.monotonic()
            try:
                with self.opener.open(url, body, timeout=self.timeout) as response:
                    self.url = response.geturl()
                    self.soup = BeautifulSoup(
                        response.read().decode("utf-8", "replace"), "html.parser"
                    )
                    return
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt == 2:
                    raise ConnectionError(
                        f"no se pudo conectar con la sede de la DGT: {exc}"
                    ) from exc
                time.sleep(2**attempt)

    def start(self) -> None:
        self._request(START_URL)

    def click(self, matcher: ButtonMatcher, what: str) -> None:
        assert self.soup is not None
        button = next((b for b in self.soup.find_all("button") if matcher(b)), None)
        # Tobago nests <form> tags; browsers submit the outermost one (it holds the Secret token).
        forms = button.find_parents("form") if button is not None else []
        form = forms[-1] if forms else None
        if button is None or form is None:
            raise SimulatorError(
                f"no encuentro el botón para «{what}»: la web de la DGT ha cambiado"
            )
        data: dict[str, str] = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            if not name or inp.get("disabled") is not None:
                continue
            if inp.get("type") in ("checkbox", "radio") and inp.get("checked") is None:
                continue
            data[str(name)] = str(inp.get("value", ""))
        data["javax.faces.source"] = _id(button)
        action = urllib.parse.urljoin(self.url, str(form.get("action") or self.url))
        self._request(action, data)


@dataclass(slots=True)
class OfficialQuestion:
    id: str
    text: str
    options: list[str]
    answer: int
    image_url: str | None
    image_folder: str | None


def parse_correction(soup: BeautifulSoup) -> OfficialQuestion | None:
    """Parse the question shown in the correction view (the right option is marked)."""
    text_tag = soup.select_one("#textoPreguntaElem")
    rows = soup.select("#tablaRespuestas tr")
    if text_tag is None or not rows:
        return None
    text = clean_text(text_tag.get_text(" "))
    options: list[str] = []
    answer = None
    for index, row in enumerate(rows):
        cell = row.select_one("td.respuesta")
        if cell is None:
            continue
        options.append(clean_text(cell.get_text(" ")))
        button = row.select_one("button")
        img = row.select_one("img")
        if (button is not None and _id(button).endswith("rbrok")) or (
            img is not None
            and "correcta" in str(img.get("src", ""))
            and "incorrecta" not in str(img.get("src", ""))
        ):
            answer = index
    if answer is None or not 2 <= len(options) <= len(LETTERS):
        return None
    image = soup.select_one("div.foto_test img[src]")
    image_url = urllib.parse.urljoin(BASE_URL, str(image["src"]).strip()) if image else None
    # Stable id: the image code plus a hash of the text that ignores spacing and punctuation.
    digest = hashlib.sha1(re.sub(r"\W+", "", normalize_text(text)).encode()).hexdigest()
    folder = None
    stem = digest[:8]
    if image_url:
        path = urllib.parse.urlparse(image_url).path
        if m := re.search(r"/IMAGENES/(.+)/([^/]+)$", path):
            folder = m.group(1)
            stem = f"{PurePosixPath(m.group(2)).stem.lower()}-{digest[:6]}"
    return OfficialQuestion(stem, text, options, answer, image_url, folder)


def run_session(log: Log, *, delay: float = 1.0) -> list[OfficialQuestion]:
    session = JsfSession(delay=delay)
    session.start()
    for what, matcher in SETUP_STEPS:
        session.click(matcher, what)
    session.click(FINISH, "finalizar examen")
    session.click(CONFIRM_FINISH, "confirmar finalización")
    questions: list[OfficialQuestion] = []
    seen: set[str] = set()
    for _ in range(60):
        assert session.soup is not None
        question = parse_correction(session.soup)
        if question is None or question.id in seen:
            break
        seen.add(question.id)
        questions.append(question)
        if not any(NEXT_QUESTION(b) for b in session.soup.find_all("button")):
            break
        session.click(NEXT_QUESTION, "siguiente pregunta")
    if not questions:
        raise SimulatorError("no he podido leer ninguna pregunta: la web de la DGT ha cambiado")
    return questions


@dataclass(slots=True)
class DgtWebReport:
    sessions: int = 0
    new_questions: int = 0
    total_questions: int = 0
    images_failed: int = 0
    pack_path: Path | None = None
    warnings: list[str] = field(default_factory=list)


def fetch_dgt_web(
    questions_dir: Path,
    *,
    refresh: bool = False,
    max_sessions: int = 12,
    patience: int = 5,  # questionnaires are assigned at random: keep trying a few times
    log: Log = print,
    http: HttpClient | None = None,
) -> DgtWebReport:
    http = http or HttpClient(delay=0.5)
    report = DgtWebReport()
    pack_dir = questions_dir / PACK_DIR
    img_dir = pack_dir / "img"
    img_dir.mkdir(parents=True, exist_ok=True)
    pack_path = pack_dir / "pack.json"
    existing: dict = {}
    if pack_path.is_file() and not refresh:
        existing = json.loads(pack_path.read_text(encoding="utf-8"))
    entries = {q["id"]: q for q in existing.get("questions", [])}

    quiet = 0
    for number in range(1, max_sessions + 1):
        log(f"Sesión {number}: recorriendo un cuestionario oficial…")
        questions = run_session(log)
        report.sessions += 1
        new = [q for q in questions if q.id not in entries]
        log(f"  {len(questions)} preguntas, {len(new)} nuevas")
        for q in new:
            entry: dict = {
                "id": q.id,
                "text": q.text,
                "options": q.options,
                "answer": LETTERS[q.answer],
                "date": datetime.now(UTC).strftime("%Y-%m"),
                "tags": ["dgt-oficial"] + ([f"dgt:{q.image_folder}"] if q.image_folder else []),
                "source": "Simulador oficial de examen de la DGT (sedeweb.dgt.gob.es)",
            }
            if q.image_url:
                name = f"{q.id}{url_suffix(q.image_url)}"
                target = img_dir / name
                if target.is_file() or http.download(q.image_url, target):
                    entry["image"] = f"img/{name}"
                else:
                    report.images_failed += 1
            entries[q.id] = entry
            report.new_questions += 1
        _write_pack(pack_path, list(entries.values()))
        quiet = 0 if new else quiet + 1
        if quiet >= patience:
            break
    _remove_orphan_images(img_dir, entries.values())
    report.total_questions = len(entries)
    report.pack_path = pack_path
    return report


def _remove_orphan_images(img_dir: Path, entries) -> None:
    """Drop images no longer referenced by the pack (e.g. after --refresh)."""
    used = {Path(e["image"]).name for e in entries if e.get("image")}
    for path in img_dir.iterdir():
        if path.is_file() and path.name not in used:
            path.unlink()


def _write_pack(pack_path: Path, questions: list[dict]) -> None:
    document = {
        "format": FORMAT_ID,
        "pack": {
            "id": "dgt-web",
            "name": "DGT · Tests oficiales (sede)",
            "origin": "dgt",
            "priority": 100,
        },
        "attribution": "Dirección General de Tráfico — https://sedeweb.dgt.gob.es (uso personal y privado)",
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "questions": sorted(questions, key=lambda q: q["id"]),
    }
    tmp = pack_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(pack_path)
