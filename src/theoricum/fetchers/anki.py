"""The community Anki deck «Carnet B» (`dgt fetch anki`).

Downloads `Carnet.B.apkg` from the latest release of donmerendolo/anki-carnet-conducir
(GPL-3.0) into `anki/` of a questions folder, with a sidecar `.toml` (metadata and cleanup).
Its author says the questions were taken from a driving school website: private study only.
theoricum never bundles the deck; this only automates the download from the public release.

The release that was downloaded is remembered in a hidden file (ignored by the library scan and
by `dgt export`), so later runs only download a new release. A deck that is already there but
was not downloaded by theoricum is never replaced without `--refresh`.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from theoricum.fetchers.http import HttpClient

REPO = "donmerendolo/anki-carnet-conducir"
REPO_URL = f"https://github.com/{REPO}"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET = "Carnet.B.apkg"
PACK_DIR = "anki"
STATE = ".carnet-b.json"
SIDECAR_MARK = "# Generado por `dgt fetch anki`"

Log = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class Release:
    tag: str
    url: str
    size: int
    updated_at: str  # ISO 8601, from GitHub

    @property
    def month(self) -> str:
        return self.updated_at[:7]


@dataclass(slots=True)
class AnkiReport:
    path: Path
    release: Release | None = None
    downloaded: bool = False
    up_to_date: bool = False
    differs: bool = False  # a deck not downloaded by theoricum is there and is not this release
    sidecar_written: bool = False


def latest_release(http: HttpClient) -> Release:
    body = http.get_text(LATEST_URL)
    if body is None:
        raise ConnectionError(f"no encuentro las versiones publicadas de {REPO_URL}")
    data = json.loads(body)
    for asset in data.get("assets", []):
        if asset.get("name") == ASSET:
            return Release(
                tag=str(data.get("tag_name", "")),
                url=str(asset["browser_download_url"]),
                size=int(asset["size"]),
                updated_at=str(asset.get("updated_at") or data.get("published_at") or ""),
            )
    raise ConnectionError(f"la última versión de {REPO_URL} no trae {ASSET}")


def sidecar_text(release: Release) -> str:
    return f"""{SIDECAR_MARK}: se reescribe al actualizar el mazo. Si lo editas, borra esta línea.
# Mazo «Carnet B» ({REPO}, GPL-3.0), versión {release.tag} del {release.updated_at[:10]}.
# Solo para uso privado: el autor indica que las preguntas se sacaron de la web de una autoescuela.
source = "{REPO_URL}"

[pack]
id = "anki-carnet-b"
name = "Anki · Carnet B"
origin = "anki"
date = "{release.month}"
priority = 50
# exclude_topics = ["senales"]   # descomenta para no usar sus preguntas de señales

[clean]
strip_suffix = ["¿Crees que la respuesta es incorrecta?"]
"""


def _write_sidecar(deck: Path, release: Release) -> bool:
    """Create the sidecar, or refresh one we generated; never touch one written by hand."""
    sidecar = deck.with_name(deck.name + ".toml")
    if sidecar.exists():
        with sidecar.open(encoding="utf-8") as fh:
            if not fh.readline().startswith(SIDECAR_MARK):
                return False
    text = sidecar_text(release)
    if sidecar.exists() and sidecar.read_text(encoding="utf-8") == text:
        return False
    sidecar.write_text(text, encoding="utf-8")
    return True


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}


def fetch_anki(
    questions_dir: Path,
    *,
    refresh: bool = False,
    http: HttpClient | None = None,
    log: Log = print,
) -> AnkiReport:
    http = http or HttpClient()
    folder = questions_dir / PACK_DIR
    deck = folder / ASSET
    state_path = folder / STATE
    report = AnkiReport(path=deck)

    log(f"Buscando la última versión de {REPO_URL}…")
    release = latest_release(http)
    report.release = release
    state = _load_state(state_path)
    folder.mkdir(parents=True, exist_ok=True)

    if deck.is_file() and not refresh:
        known = state.get("tag") == release.tag and state.get("size") == release.size
        if known or (not state and deck.stat().st_size == release.size):
            report.up_to_date = True
        elif not state:
            report.differs = True  # someone else's copy: keep it
            return report

    if not report.up_to_date:
        log(f"Descargando {ASSET} (versión {release.tag}, {release.size / 1e6:.0f} MB)…")
        shown = -1

        def progress(done: int, total: int | None) -> None:
            nonlocal shown
            step = int(10 * done / total) if total else -1
            if step > shown:
                shown = step
                log(f"  {10 * step} %")

        if not http.download(release.url, deck, delay=0, progress=progress):
            raise ConnectionError(f"no se pudo descargar {release.url}")
        report.downloaded = True

    state_path.write_text(
        json.dumps(
            {"tag": release.tag, "size": release.size, "updated_at": release.updated_at},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    report.sidecar_written = _write_sidecar(deck, release)
    return report
