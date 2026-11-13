import json
import zipfile
from io import BytesIO
from pathlib import Path

from bs4 import BeautifulSoup

from theoricum.fetchers import anki, dgt_web, revista_dgt
from theoricum.importers import ImportContext
from theoricum.importers.apkg import ApkgImporter
from theoricum.importers.native import NativeImporter
from theoricum.library.scan import scan


def article(n: int, answer: str | None, explanation: str = "") -> str:
    answer_html = (
        f'<strong>Respuesta correcta</strong> <span class="opcion">{answer}</span>'
        if answer
        else ""
    )
    extra = f"<p><strong>CON MÁS DETALLE</strong></p><p>{explanation}</p>" if explanation else ""
    return f"""
    <article class="test">
      <figure><img src="/Galerias/test/201403/Preg-{n:02d}-160x146.jpg" alt="Señal"></figure>
      <section class="content_test">
        <h4 class="tit_not">{n}. ¿Pregunta  número {n}?</h4>
        <ul>
          <li><span class="opcion">A.</span> Opción uno.</li>
          <li><span class="opcion">B.</span> Opción dos.</li>
          <li><span class="opcion">C.</span> Opción tres.</li>
        </ul>
        <div class="content_respuesta" data-id="preg{n}"><p>{answer_html}</p>{extra}</div>
      </section>
    </article>"""


def page(label: str, *articles: str) -> str:
    return f"<html><head><title>{label}</title></head><body><h1>{label}</h1>{''.join(articles)}</body></html>"


INDEX = """<html><body><section id="enlaces_relacionados">
<a href="/es/test/Test-num-225.shtml">225</a><a href="/es/test/Test-num-224.shtml">224</a>
</section></body></html>"""


def test_parse_test_page_and_dates():
    test = revista_dgt.parse_test_page(
        page("Marzo-abril 2014", article(1, "b", "Más detalle aquí."), article(2, None)), 224
    )
    assert test.date == "2014-03"
    (q,) = test.questions
    assert q.text == "¿Pregunta número 1?"
    assert q.options == ["Opción uno.", "Opción dos.", "Opción tres."]
    assert q.answer == 1 and q.explanation == "Más detalle aquí."
    assert q.image_url == "https://revista.dgt.es/Galerias/test/201403/Preg-01-160x146.jpg"
    assert "pregunta 2" in test.warnings[0]
    assert (
        revista_dgt.parse_date("Test revista número 254", ["/Galerias/test/201507/x.jpg"])
        == "2015-07"
    )
    assert revista_dgt.parse_date("Marzo de 2026", []) == "2026-03"


class FakeHttp:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.requests: list[str] = []

    def get_text(self, url: str) -> str | None:
        self.requests.append(url)
        return self.pages.get(url)

    def exists(self, url: str) -> bool:  # discovery probes are not page downloads
        return url in self.pages

    def download(self, url: str, target: Path, *, delay: float | None = None) -> bool:
        self.requests.append(url)
        target.write_bytes(b"jpeg")
        return True


def test_fetch_revista_writes_importable_pack_incrementally(qdir: Path):
    pages = {
        revista_dgt.INDEX_URL: INDEX,
        revista_dgt.test_url(224): page("Febrero 2014", article(1, "A")),
        revista_dgt.test_url(226): page("Junio 2014", article(1, "C"), article(2, "B")),
    }
    http = FakeHttp(pages)
    report = revista_dgt.fetch_revista(qdir, http=http, log=lambda _: None)
    assert report.tests_fetched == [226, 224] and report.tests_missing == [225]  # newest first
    assert report.total_questions == 3
    pack = qdir / "revista-dgt" / "pack.json"
    data = json.loads(pack.read_text(encoding="utf-8"))
    assert [q["id"] for q in data["questions"]] == ["t224-q01", "t226-q01", "t226-q02"]
    assert data["questions"][0]["image"] == "img/t224-q01.jpg"

    result = NativeImporter().load(ImportContext(questions_dir=qdir, path=pack))
    assert len(result.questions) == 3 and result.meta.origin == "revista-dgt"
    assert result.questions[1].answer == 2 and result.questions[1].date == "2014-06"

    http.requests.clear()
    again = revista_dgt.fetch_revista(qdir, http=http, log=lambda _: None)
    assert again.tests_fetched == [] and again.total_questions == 3
    assert revista_dgt.test_url(224) not in http.requests


def test_fetch_revista_goes_newest_first_and_last_limits_it(qdir: Path):
    pages = {
        revista_dgt.INDEX_URL: INDEX,
        revista_dgt.test_url(224): page("Febrero 2014", article(1, "A")),
        revista_dgt.test_url(226): page("Junio 2014", article(1, "C")),
        revista_dgt.test_url(227): page("Octubre 2014", article(1, "B")),
    }
    http = FakeHttp(pages)
    report = revista_dgt.fetch_revista(qdir, last=2, http=http, log=lambda _: None)
    # 225 does not exist and does not count: the two most recent published tests are 227 and 226.
    assert report.tests_fetched == [227, 226] and report.tests_missing == []
    tests = [url for url in http.requests if "Test-num-" in url]
    assert tests.index(revista_dgt.test_url(227)) < tests.index(revista_dgt.test_url(226))
    assert revista_dgt.test_url(224) not in tests

    http.requests.clear()
    again = revista_dgt.fetch_revista(qdir, last=2, http=http, log=lambda _: None)
    assert again.tests_fetched == [] and again.total_questions == 2  # nothing new to download

    full = revista_dgt.fetch_revista(qdir, http=http, log=lambda _: None)
    assert full.tests_fetched == [224] and full.tests_missing == [225]
    data = json.loads((qdir / "revista-dgt" / "pack.json").read_text(encoding="utf-8"))
    assert [q["id"] for q in data["questions"]] == ["t224-q01", "t226-q01", "t227-q01"]


CORRECTION = """
<html><body><form id="outer"><input name="org.apache.myfaces.tobago.webapp.Secret" value="s">
<form id="inner"><input type="hidden" name="javax.faces.ViewState" value="v">
<table><tr><td class="pregunta_txt"><span id="textoPreguntaElem">¿Es  obligatorio?</span></td></tr></table>
<div class="foto_test"><img src="/EXAM/WEB_AUTO9/IMAGENES/20_VEHICULOS/ESPEJOS/MT1.jpg "></div>
<table id="tablaRespuestas">
 <tr><td><button id="p:j_id_v:0:rbr"><img src="radiobutton_test_1.gif"></button></td><td class="respuesta"><a>Sí.</a></td></tr>
 <tr><td><button id="p:j_id_v:1:rbrok"><img src="boton_correcta.gif"></button></td><td class="respuesta"><a>No.</a></td></tr>
 <tr><td><button id="p:j_id_v:2:rbr"><img src="radiobutton_test_3.gif"></button></td><td class="respuesta"><a>A veces.</a></td></tr>
</table>
<button id="p:form1:botones:preguntaSiguiente"></button>
</form></form></body></html>"""


def test_dgt_web_parse_correction_and_matchers():
    soup = BeautifulSoup(CORRECTION, "html.parser")
    q = dgt_web.parse_correction(soup)
    assert q is not None
    assert (
        q.text == "¿Es obligatorio?" and q.options == ["Sí.", "No.", "A veces."] and q.answer == 1
    )
    assert (
        q.image_url
        == "https://sedeweb.dgt.gob.es/EXAM/WEB_AUTO9/IMAGENES/20_VEHICULOS/ESPEJOS/MT1.jpg"
    )
    assert q.image_folder == "20_VEHICULOS/ESPEJOS" and q.id.startswith("mt1-")
    assert any(dgt_web.NEXT_QUESTION(b) for b in soup.find_all("button"))

    permits = BeautifulSoup(
        '<table><tr><td><div><span>Permiso B</span><button id="x:data2:0:linkConsulta_"></button></div>'
        '<div><span>AM</span><button id="x:data2:1:linkConsulta_"></button></div></td></tr></table>',
        "html.parser",
    )
    matches = [b["id"] for b in permits.find_all("button") if dgt_web.permit_b(b)]
    assert matches[0] == "x:data2:0:linkConsulta_"


def zipped(text: str) -> bytes:
    """A tiny zip standing in for an .apkg (the scan only sees zips)."""
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr(zipfile.ZipInfo("collection.anki2", (2025, 3, 4, 0, 0, 0)), text)
    return out.getvalue()


class FakeGitHub:
    """The GitHub API and the release download of the Anki deck."""

    def __init__(self, tag: str, deck: bytes) -> None:
        self.release(tag, deck)
        self.downloads = 0

    def release(self, tag: str, deck: bytes) -> None:
        self.deck = deck
        self.api = json.dumps(
            {
                "tag_name": tag,
                "published_at": "2025-03-04T11:54:58Z",
                "assets": [
                    {"name": "Carnet.A1.apkg", "size": 1, "browser_download_url": "x"},
                    {
                        "name": anki.ASSET,
                        "size": len(deck),
                        "updated_at": "2025-03-04T11:53:22Z",
                        "browser_download_url": f"https://github.com/dl/{tag}/{anki.ASSET}",
                    },
                ],
            }
        )

    def get_text(self, url: str) -> str | None:
        return self.api if url == anki.LATEST_URL else None

    def download(self, url, target: Path, *, delay=None, progress=None) -> bool:
        self.downloads += 1
        target.write_bytes(self.deck)
        if progress:
            progress(len(self.deck), len(self.deck))
        return True


def test_fetch_anki_downloads_the_deck_once_with_its_settings(qdir: Path):
    hub = FakeGitHub("3.0", zipped("v3"))
    report = anki.fetch_anki(qdir, http=hub, log=lambda _: None)
    deck = qdir / "anki" / anki.ASSET
    assert report.downloaded and deck.read_bytes() == zipped("v3")
    sidecar = deck.with_name(deck.name + ".toml")
    text = sidecar.read_text(encoding="utf-8")
    assert text.startswith(anki.SIDECAR_MARK) and 'date = "2025-03"' in text
    assert (qdir / "anki" / anki.STATE).is_file()

    again = anki.fetch_anki(qdir, http=hub, log=lambda _: None)
    assert again.up_to_date and hub.downloads == 1

    hub.release("4.0", zipped("version 4"))  # a new release: downloaded, settings refreshed
    newer = anki.fetch_anki(qdir, http=hub, log=lambda _: None)
    assert newer.downloaded and deck.read_bytes() == zipped("version 4")
    assert "versión 4.0" in sidecar.read_text(encoding="utf-8")

    # The library only sees the deck: the state file is hidden and the sidecar is claimed.
    found = scan(qdir, [ApkgImporter()])
    assert [s.rel for s in found.sources] == ["anki/Carnet.B.apkg"] and not found.ignored


def test_fetch_anki_respects_a_deck_and_settings_you_put_there(qdir: Path):
    hub = FakeGitHub("3.0", zipped("v3"))
    deck = qdir / "anki" / anki.ASSET
    deck.parent.mkdir(parents=True)
    sidecar = deck.with_name(deck.name + ".toml")
    sidecar.write_text('[pack]\nname = "Mi mazo"\n', encoding="utf-8")

    deck.write_bytes(zipped("v3"))  # downloaded by hand: same size as the release
    report = anki.fetch_anki(qdir, http=hub, log=lambda _: None)
    assert report.up_to_date and hub.downloads == 0
    assert sidecar.read_text(encoding="utf-8") == '[pack]\nname = "Mi mazo"\n'

    (qdir / "anki" / anki.STATE).unlink()
    deck.write_bytes(zipped("another deck of mine"))
    report = anki.fetch_anki(qdir, http=hub, log=lambda _: None)
    assert report.differs and deck.read_bytes() == zipped("another deck of mine")
    report = anki.fetch_anki(qdir, refresh=True, http=hub, log=lambda _: None)
    assert report.downloaded and deck.read_bytes() == zipped("v3")
    assert sidecar.read_text(encoding="utf-8") == '[pack]\nname = "Mi mazo"\n'
