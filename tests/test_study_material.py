"""Study material: the DGT manual (split by topics, opened in the system viewer), the traffic law
from the BOE (version in force, search) and the sheet of changes. Never the network."""

import json
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest

from theoricum import manual as manual_mod
from theoricum.cli import main
from theoricum.fetchers import laws as laws_fetcher
from theoricum.fetchers import manual as manual_fetcher
from theoricum.laws import load_laws
from theoricum.manual import TOPIC_CHAPTERS, load_manual, viewer_command
from theoricum.topics import SpanishTopicName, load_topics
from theoricum.validity import load_changes, novelties

from pdf_builder import build_text_pdf

MANUAL_PAGES = [
    ["Manual del Permiso B en Lectura Fácil", "Índice general"],
    ["Tema 1. Definiciones", "Vehículo: aparato preparado para circular."],
    ["Más definiciones"],
    ["Tema 8. Señales de circulación", "Las señales de los agentes."],
    ["Tema 10. Velocidad y distancias"],
    ["Anexo puntos. El permiso de conducir por puntos"],
]
BOOKMARKS = [("Índice", 0), ("Tema 01", 1), ("Tema 08", 3), ("Tema 10", 4), ("Anexo Puntos", 5)]


class FakeHttp:
    def __init__(self, files: dict[str, bytes] | None = None, texts=None) -> None:
        self.files = files or {}
        self.texts = texts or {}
        self.requests: list[str] = []

    def download(self, url, target: Path, *, delay=None, progress=None) -> bool:
        self.requests.append(url)
        if url not in self.files:
            return False
        target.write_bytes(self.files[url])
        return True

    def get_text(self, url: str, *, headers=None) -> str | None:
        self.requests.append(url)
        assert headers == {"Accept": "application/xml"}  # the BOE answers 400 without it
        return self.texts.get(url)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "data"
    folder.mkdir()
    return folder


def fetch_fake_manual(data_dir: Path) -> FakeHttp:
    http = FakeHttp({manual_fetcher.URL: build_text_pdf(MANUAL_PAGES, BOOKMARKS)})
    manual_fetcher.fetch_manual(data_dir, http=http, log=lambda _: None)  # type: ignore[arg-type]
    return http


# --- the manual ---------------------------------------------------------------------------------


def test_the_manual_is_split_by_its_bookmarks(data_dir: Path):
    http = fetch_fake_manual(data_dir)
    manual = load_manual(data_dir)
    assert manual is not None and manual.full.is_file()
    assert [(c.number, c.title, c.first_page, c.pages) for c in manual.chapters] == [
        (1, "Definiciones", 2, 2),
        (8, "Señales de circulación", 4, 1),
        (10, "Velocidad y distancias", 5, 1),
        (18, "El permiso de conducir por puntos", 6, 1),
    ]
    assert all(manual.path(c).is_file() for c in manual.chapters)
    assert manual.path(manual.chapters[1]).name == "08-senales-de-circulacion.pdf"

    again = manual_fetcher.fetch_manual(data_dir, http=http, log=lambda _: None)  # type: ignore[arg-type]
    assert again.already and http.requests == [manual_fetcher.URL]  # downloaded once


def test_finding_a_topic_of_the_manual(data_dir: Path):
    fetch_fake_manual(data_dir)
    manual = load_manual(data_dir)
    assert manual is not None
    assert manual.find("8").number == 8  # type: ignore[union-attr]
    assert manual.find("signals").number == 8  # type: ignore[union-attr]  # theoricum topic
    assert manual.find("Speed").number == 10  # type: ignore[union-attr]
    assert manual.find("distances").number == 10  # type: ignore[union-attr]
    assert manual.find("points").number == 18  # type: ignore[union-attr]
    assert manual.find("nothing-like-this") is None
    # The command line is English only: Spanish names point to the English ones.
    for spanish, english in (("señales", "signals"), ("velocidad", "speed"), ("puntos", "points")):
        with pytest.raises(SpanishTopicName) as exc:
            manual.find(spanish)
        assert exc.value.cli == english
    assert manual.for_topic("distancias").number == 10  # type: ignore[union-attr]
    assert manual.for_topic("otros") is None


def test_every_topic_has_a_chapter_of_the_manual():
    slugs = {t.slug for t in load_topics()} - {"otros"}
    assert slugs == set(TOPIC_CHAPTERS)
    assert all(1 <= n <= 17 for n in TOPIC_CHAPTERS.values())


def test_an_incomplete_manual_is_not_used(data_dir: Path):
    fetch_fake_manual(data_dir)
    next((data_dir / "manual").glob("08-*.pdf")).unlink()
    assert load_manual(data_dir) is None


def test_documents_open_in_the_system_viewer(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "tema.pdf"
    assert viewer_command(pdf, "linux") == ["xdg-open", str(pdf)]
    assert viewer_command(pdf, "darwin") == ["open", str(pdf)]
    assert viewer_command(pdf, "win32") is None  # os.startfile
    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))

    monkeypatch.setattr(manual_mod, "viewer_command", lambda path: ["xdg-open", str(path)])
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    manual_mod.open_document(pdf)
    assert calls[0][0] == ["xdg-open", str(pdf)] and calls[0][1]["start_new_session"]

    def missing(command, **kwargs):
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(subprocess, "Popen", missing)
    with pytest.raises(OSError, match="xdg-open"):
        manual_mod.open_document(pdf)


def test_cli_manual_opens_a_topic_and_lists_the_changes(data_dir: Path, monkeypatch, capsys):
    fetch_fake_manual(data_dir)
    opened = []
    monkeypatch.setattr(manual_mod, "open_document", opened.append)
    assert main(["--data-dir", str(data_dir), "manual", "signals"]) == 0
    out = capsys.readouterr().out
    assert opened[-1].name == "08-senales-de-circulacion.pdf"
    assert "Desde entonces ha cambiado" in out and "V-16" in out
    assert main(["--data-dir", str(data_dir), "manual"]) == 0
    assert opened[-1].name == "manual-permiso-b.pdf"
    assert main(["--data-dir", str(data_dir), "manual", "99"]) == 2
    assert main(["--data-dir", str(data_dir), "manual", "señales"]) == 2
    assert "dgt manual signals" in capsys.readouterr().err
    assert main(["--data-dir", str(data_dir), "fetch", "manual", "--into", "x"]) == 2


# --- the sheet of changes -------------------------------------------------------------------------


def test_every_change_has_a_title_a_summary_and_valid_chapters():
    for change in load_changes():
        assert change.title and change.summary, change.id
        assert all(1 <= n <= 18 for n in change.manual), change.id
    after = novelties(after="2023-12")
    assert [c.id for c in after] == sorted(
        (c.id for c in after), key=lambda i: next(x.since for x in after if x.id == i), reverse=True
    )
    assert "v16" in {c.id for c in after} and "urbana-30" not in {c.id for c in after}


# --- the traffic law ------------------------------------------------------------------------------

LAW_XML = """<?xml version="1.0" encoding="utf-8"?>
<response><data><texto>
  <bloque id="tii" tipo="encabezado" titulo="TÍTULO II"><version fecha_vigencia="20040123">
    <p class="titulo_num">TÍTULO II</p><p class="titulo_tit">De la circulación de vehículos</p>
  </version></bloque>
  <bloque id="cii" tipo="encabezado" titulo="CAPÍTULO II"><version fecha_vigencia="20040123">
    <p class="capitulo_num">CAPÍTULO II</p><p class="capitulo_tit">Velocidad</p>
    <blockquote><p class="nota_pie">Nota del encabezado que no debe salir.</p></blockquote>
  </version></bloque>
  <bloque id="a48" tipo="precepto" titulo="Artículo 48">
    <version fecha_vigencia="20040123">
      <p class="articulo">Artículo 48. Velocidades máximas.</p>
      <p class="parrafo">Convencionales: 100 kilómetros por hora.</p>
    </version>
    <version fecha_vigencia="20190129">
      <p class="articulo">Artículo 48. Velocidades máximas.</p>
      <p class="parrafo">Convencionales: 90 kilómetros por hora.</p>
      <table><tr><td>Turismos</td><td>90</td></tr></table>
      <p class="imagen">x</p>
      <blockquote><p class="nota_pie">Se modifica por el Real Decreto 1514/2018.</p></blockquote>
    </version>
    <version fecha_vigencia="20990101">
      <p class="articulo">Artículo 48. Velocidades máximas.</p>
      <p class="parrafo">Convencionales: 70 kilómetros por hora.</p>
    </version>
  </bloque>
  <bloque id="a121" tipo="precepto" titulo="Artículo 121">
    <version fecha_vigencia="20990101">
      <p class="articulo">Artículo 121. Patinetes en la acera.</p>
      <p class="parrafo">No pueden circular por la acera.</p>
    </version>
  </bloque>
  <bloque id="ai" tipo="encabezado" titulo="ANEXO I"><version fecha_vigencia="20040123">
    <p>ANEXO I</p><p>Pruebas deportivas</p>
  </version></bloque>
  <bloque id="ai-1" tipo="precepto" titulo="Artículo 1"><version fecha_vigencia="20040123">
    <p class="articulo">Artículo 1. Ciclistas en una prueba.</p>
    <p class="parrafo">Las bicicletas tienen prioridad.</p>
  </version></bloque>
</texto></data></response>"""


def test_the_version_in_force_is_kept_with_its_context():
    articles = laws_fetcher.parse_law(LAW_XML, today="20261113")
    a48, a121, annex = articles
    assert a48.title == "Artículo 48. Velocidades máximas."
    assert "90 kilómetros" in a48.text and "100" not in a48.text and "70" not in a48.text
    assert a48.in_force == "2019-01-29" and not a48.future
    assert "Turismos | 90" in a48.text and "[imagen" in a48.text
    assert a48.notes == "Se modifica por el Real Decreto 1514/2018."
    assert a48.section == "TÍTULO II De la circulación de vehículos · CAPÍTULO II Velocidad"
    assert a121.future and a121.in_force == "2099-01-01"  # not in force yet: shown as such
    assert annex.section == "ANEXO I Pruebas deportivas"  # the annex resets the context


def meta(updated: str) -> str:
    return f"<response><data><metadatos><fecha_actualizacion>{updated}</fecha_actualizacion></metadatos></data></response>"


def test_fetch_laws_and_search_them(data_dir: Path):
    texts = {}
    for law in laws_fetcher.LAWS:
        texts[laws_fetcher.API.format(id=law.boe_id, part="metadatos")] = meta("20261001T072122Z")
        texts[laws_fetcher.API.format(id=law.boe_id, part="texto")] = LAW_XML
    report = laws_fetcher.fetch_laws(data_dir, http=FakeHttp(texts=texts), log=lambda _: None)  # type: ignore[arg-type]
    assert [count for _, count, _ in report.laws] == [3, 3, 3, 3]
    library = load_laws(data_dir)
    assert library is not None
    assert library.laws[0][0] == "Reglamento General de Circulación"
    assert library.laws[0][1] == "2026-10-01"
    found = library.search("VELOCIDADES maximas")  # case and accents do not matter
    assert found and found[0].id == "a48"
    assert {a.id for a in library.search("bicicletas prioridad")} == {"ai-1"}
    assert library.search("palabra-que-no-existe") == []
    assert len(library.search("")) == 12  # an empty search lists everything


def test_a_broken_answer_from_the_boe_is_a_clear_error(data_dir: Path):
    texts = {
        laws_fetcher.API.format(id=law.boe_id, part="texto"): "<html>" for law in laws_fetcher.LAWS
    }
    with pytest.raises(ValueError, match="XML"):
        laws_fetcher.fetch_laws(data_dir, http=FakeHttp(texts=texts), log=lambda _: None)  # type: ignore[arg-type]


def write_laws(data_dir: Path) -> None:
    folder = data_dir / "laws"
    folder.mkdir(parents=True, exist_ok=True)
    document = {
        "format": laws_fetcher.FORMAT,
        "law": {"slug": "rgc", "name": "Reglamento General de Circulación", "url": "u",
                "updated": "2026-10-01"},
        "articles": [asdict(a) for a in laws_fetcher.parse_law(LAW_XML, today="20261113")],
    }  # fmt: skip
    (folder / "rgc.json").write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


# --- in the TUI -----------------------------------------------------------------------------------


def make_app(tmp_path: Path, data_dir: Path, command: str = "menu", **kw):
    from textual_image.widget import UnicodeImage

    from theoricum.config import Paths
    from theoricum.tui.app import StartRequest, TheoricumApp

    from conftest import make_questions, write_pack

    qdir = tmp_path / "questions"
    write_pack(qdir / "p.json", make_questions(10, topic="velocidad"), {"id": "p"})
    paths = Paths(questions_dir=qdir, data_dir=data_dir)
    return TheoricumApp(
        paths=paths, start=StartRequest(command=command, **kw), image_cls=UnicodeImage, seed=1
    )


async def settle(app, pilot) -> None:
    await pilot.pause()
    for _ in range(100):
        if not app.syncing:
            break
        await pilot.pause(0.05)
    await pilot.pause(0.1)


async def test_manual_screen_opens_topics_and_shows_the_changes(tmp_path, data_dir, monkeypatch):
    from theoricum.tui.screens.manual import ManualScreen

    app = make_app(tmp_path, data_dir)
    async with app.run_test(size=(130, 40)) as pilot:
        await settle(app, pilot)
        await pilot.press("8")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ManualScreen)
        assert "Aún no tienes el manual" in str(screen.query_one("#manual-missing").content)
        assert "V-16" in str(screen.query_one("#novelties-text").content)
        await pilot.press("escape")

        fetch_fake_manual(data_dir)
        opened = []
        monkeypatch.setattr(manual_mod, "open_document", opened.append)
        await pilot.press("8")
        await pilot.pause()
        await pilot.press("down", "enter")  # «Manual completo», then topic 1
        await pilot.pause()
        assert opened and opened[-1].name == "01-definiciones.pdf"


async def test_laws_screen_searches_the_version_in_force(tmp_path, data_dir):
    from textual.widgets import Input

    from theoricum.tui.screens.laws import LawsScreen

    write_laws(data_dir)
    app = make_app(tmp_path, data_dir, "laws", query="velocidades")
    async with app.run_test(size=(130, 40)) as pilot:
        await settle(app, pilot)
        screen = app.screen
        assert isinstance(screen, LawsScreen)
        assert [a.id for a in screen.results] == ["a48"]
        shown = str(screen.query_one("#laws-text").content)
        assert "90 kilómetros" in shown and "Se modifica" in shown
        screen.query_one("#laws-search", Input).value = "bicicletas"
        await pilot.pause()
        assert [a.id for a in screen.results] == ["ai-1"]


async def test_manual_and_laws_keys_wait_for_the_correction_in_an_exam(
    tmp_path, data_dir, monkeypatch
):
    from theoricum.tui.screens.laws import LawsScreen
    from theoricum.tui.screens.test import TestScreen

    write_laws(data_dir)
    app = make_app(tmp_path, data_dir, "exam")
    async with app.run_test(size=(130, 40)) as pilot:
        await settle(app, pilot)
        screen = app.screen
        assert isinstance(screen, TestScreen)
        await pilot.press("n")  # it would be a crib sheet
        await pilot.pause()
        assert app.screen is screen
        screen.finish()
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        laws = app.screen
        assert isinstance(laws, LawsScreen) and laws.initial_query == "velocidad"


async def test_laws_can_be_downloaded_with_f5_while_typing(tmp_path, data_dir, monkeypatch):
    from textual.widgets import Input

    from theoricum.tui.screens.laws import LawsScreen

    calls = []

    def fake_fetch(folder, **kwargs):
        calls.append(folder)
        write_laws(folder)

    monkeypatch.setattr(laws_fetcher, "fetch_laws", fake_fetch)
    app = make_app(tmp_path, data_dir, "laws")
    async with app.run_test(size=(130, 40)) as pilot:
        await settle(app, pilot)
        screen = app.screen
        assert isinstance(screen, LawsScreen) and screen.library is None
        assert "F5" in str(screen.query_one("#laws-status").content)
        assert screen.query_one("#laws-search", Input).has_focus
        await pilot.press("f5")
        for _ in range(50):
            await pilot.pause(0.05)
            if screen.library is not None:
                break
        assert calls == [data_dir] and screen.library is not None and screen.results
