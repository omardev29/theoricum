"""The traffic law downloaded with `dgt fetch laws` (see fetchers/laws.py): loading and search."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from theoricum.topics import normalize_text

FOLDER = "laws"
ORDER = ("rgc", "lsv", "rgcond", "rgv")  # the traffic regulation first
# What to search first when the law is opened from a question of each topic.
TOPIC_QUERIES = {
    "senales": "señales",
    "velocidad": "velocidad",
    "prioridad": "prioridad de paso",
    "adelantamiento": "adelantamiento",
    "maniobras": "maniobra",
    "estacionamiento": "estacionamiento",
    "alumbrado": "alumbrado",
    "vias": "calzada",
    "distancias": "distancia",
    "documentacion": "permiso de conducción",
    "carga": "carga",
    "seguridad": "cinturón",
    "alcohol": "alcohol",
    "riesgos": "conducción",
    "vulnerables": "ciclistas",
    "mecanica": "neumáticos",
    "accidentes": "accidente",
    "medioambiente": "contaminación",
}


@dataclass(frozen=True, slots=True)
class LawArticle:
    law: str  # short name of the law
    law_url: str
    id: str
    title: str
    section: str
    text: str
    in_force: str
    future: bool
    notes: str


@dataclass
class LawLibrary:
    laws: list[tuple[str, str, int]]  # (name, updated YYYY-MM-DD, articles)
    articles: list[LawArticle]
    _haystacks: list[tuple[str, str]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._haystacks = [(normalize_text(a.title), normalize_text(a.text)) for a in self.articles]

    def search(self, query: str, limit: int = 300) -> list[LawArticle]:
        """Articles containing every word of the query (accents and case ignored); those with
        the words in their title first. An empty query lists everything in order."""
        words = normalize_text(query).split()
        if not words:
            return self.articles[:limit]
        scored = []
        for index, (article, (title, text)) in enumerate(
            zip(self.articles, self._haystacks, strict=True)
        ):
            if all(w in title or w in text for w in words):
                score = sum(5 * title.count(w) + text.count(w) for w in words)
                scored.append((-score, index, article))
        scored.sort(key=lambda item: item[:2])
        return [article for _, _, article in scored[:limit]]


def laws_dir(data_dir: Path) -> Path:
    return data_dir / FOLDER


def load_laws(data_dir: Path) -> LawLibrary | None:
    """The downloaded laws, or None if there are none yet."""
    folder = laws_dir(data_dir)
    files = sorted(
        folder.glob("*.json") if folder.is_dir() else [],
        key=lambda p: (ORDER.index(p.stem) if p.stem in ORDER else len(ORDER), p.stem),
    )
    laws: list[tuple[str, str, int]] = []
    articles: list[LawArticle] = []
    for path in files:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            law = document["law"]
            items = document["articles"]
        except OSError, ValueError, KeyError, TypeError:
            continue
        laws.append((law["name"], law.get("updated", ""), len(items)))
        articles.extend(
            LawArticle(
                law=law["name"],
                law_url=law.get("url", ""),
                id=a["id"],
                title=a["title"],
                section=a.get("section", ""),
                text=a.get("text", ""),
                in_force=a.get("in_force", ""),
                future=bool(a.get("future")),
                notes=a.get("notes", ""),
            )
            for a in items
        )
    return LawLibrary(laws, articles) if articles else None
