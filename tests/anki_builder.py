"""Build tiny Anki packages (legacy and latest formats) for the importer tests."""

import hashlib
import json
import sqlite3
import zipfile
from compression import zstd
from dataclasses import dataclass, field
from pathlib import Path

ANKI_MC_FIELDS = [
    "Question",
    "Image",
    "QType (0=kprim,1=mc,2=sc)",
    "Q_1",
    "Q_2",
    "Q_3",
    "Answers",
    "Sources",
]


@dataclass
class FakeNote:
    guid: str
    notetype: str
    fields: list[str]
    tags: list[str] = field(default_factory=list)
    deck: str = "Default"


@dataclass
class FakeNotetype:
    id: int
    name: str
    fields: list[str]
    cloze: bool = False


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def pb_varint(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def pb_bytes(number: int, value: bytes) -> bytes:
    return _varint(number << 3 | 2) + _varint(len(value)) + value


def _unicase(a: str, b: str) -> int:
    a, b = a.casefold(), b.casefold()
    return (a > b) - (a < b)


def build_collection(
    path: Path, notetypes: list[FakeNotetype], notes: list[FakeNote], schema: int, wal: bool = False
) -> bytes:
    """Create a minimal Anki collection SQLite file and return its bytes."""
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.create_collation("unicase", _unicase)
    decks = sorted({n.deck for n in notes} | {"Default"})
    deck_ids = {name: i + 1 for i, name in enumerate(decks)}
    nt_by_name = {nt.name: nt for nt in notetypes}
    conn.execute("CREATE TABLE col (id INTEGER PRIMARY KEY, ver INTEGER, models TEXT, decks TEXT)")
    if schema >= 15:
        conn.execute(
            "CREATE TABLE notetypes (id INTEGER PRIMARY KEY, name TEXT COLLATE unicase, config BLOB)"
        )
        conn.execute(
            "CREATE TABLE fields (ntid INTEGER, ord INTEGER, name TEXT COLLATE unicase, config BLOB)"
        )
        conn.execute("CREATE INDEX idx_fields_name ON fields (name, ntid)")
        conn.execute("CREATE TABLE decks (id INTEGER PRIMARY KEY, name TEXT COLLATE unicase)")
        conn.execute("INSERT INTO col VALUES (1, ?, '', '')", (schema,))
        for nt in notetypes:
            config = pb_varint(1, 1 if nt.cloze else 0)
            conn.execute("INSERT INTO notetypes VALUES (?, ?, ?)", (nt.id, nt.name, config))
            for ord_, name in enumerate(nt.fields):
                conn.execute("INSERT INTO fields VALUES (?, ?, ?, ?)", (nt.id, ord_, name, b""))
        for name, did in deck_ids.items():
            conn.execute("INSERT INTO decks VALUES (?, ?)", (did, name.replace("::", "\x1f")))
    else:
        models = {
            str(nt.id): {
                "name": nt.name,
                "type": 1 if nt.cloze else 0,
                "flds": [{"name": n, "ord": i} for i, n in enumerate(nt.fields)],
            }
            for nt in notetypes
        }
        deck_json = {str(did): {"name": name} for name, did in deck_ids.items()}
        conn.execute(
            "INSERT INTO col VALUES (1, ?, ?, ?)",
            (schema, json.dumps(models), json.dumps(deck_json)),
        )
    conn.execute(
        "CREATE TABLE notes (id INTEGER PRIMARY KEY, guid TEXT, mid INTEGER, tags TEXT, flds TEXT)"
    )
    conn.execute(
        "CREATE TABLE cards (id INTEGER PRIMARY KEY, nid INTEGER, did INTEGER, odid INTEGER, ord INTEGER)"
    )
    for i, note in enumerate(notes, start=1):
        nt = nt_by_name[note.notetype]
        tags = f" {' '.join(note.tags)} " if note.tags else ""
        conn.execute(
            "INSERT INTO notes VALUES (?, ?, ?, ?, ?)",
            (i, note.guid, nt.id, tags, "\x1f".join(note.fields)),
        )
        conn.execute("INSERT INTO cards VALUES (?, ?, ?, 0, 0)", (i, i, deck_ids[note.deck]))
    conn.commit()
    if wal:
        conn.execute("PRAGMA journal_mode = WAL")
    conn.close()
    data = path.read_bytes()
    path.unlink()
    for suffix in ("-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    return data


def build_apkg(
    out: Path,
    *,
    version: int,
    notetypes: list[FakeNotetype],
    notes: list[FakeNote],
    media: dict[str, bytes] | None = None,
    tmp: Path,
) -> Path:
    """Write an .apkg of the given package version (1, 2 or 3)."""
    media = media or {}
    names = list(media)
    with zipfile.ZipFile(out, "w") as zf:
        if version == 1:
            zf.writestr("collection.anki2", build_collection(tmp / "c.db", notetypes, notes, 11))
        else:
            dummy = FakeNotetype(1, "Basic", ["Front", "Back"])
            zf.writestr(
                "collection.anki2",
                build_collection(
                    tmp / "d.db",
                    [dummy],
                    [FakeNote("dummy", "Basic", ["Please update to the latest Anki version", ""])],
                    11,
                ),
            )
        if version == 2:
            zf.writestr("collection.anki21", build_collection(tmp / "c.db", notetypes, notes, 11))
            zf.writestr("meta", pb_varint(1, 2))
        if version == 3:
            collection = build_collection(tmp / "c.db", notetypes, notes, 18, wal=True)
            assert collection[18] == 2  # really a WAL-mode database
            zf.writestr("collection.anki21b", zstd.compress(collection))
            zf.writestr("meta", pb_varint(1, 3))
            entries = b"".join(
                pb_bytes(
                    1,
                    pb_bytes(1, name.encode())
                    + pb_varint(2, len(media[name]))
                    + pb_bytes(3, hashlib.sha1(media[name]).digest()),
                )
                for name in names
            )
            zf.writestr("media", zstd.compress(entries))
            for i, name in enumerate(names):
                zf.writestr(str(i), zstd.compress(media[name]))
        else:
            zf.writestr("media", json.dumps({str(i): name for i, name in enumerate(names)}))
            for i, name in enumerate(names):
                zf.writestr(str(i), media[name])
    return out


def anki_mc_deck() -> tuple[list[FakeNotetype], list[FakeNote]]:
    """A few notes covering the anki-mc preset, a basic inline note and a cloze note."""
    mc = FakeNotetype(1001, "Carnet B", ANKI_MC_FIELDS)
    basic = FakeNotetype(1002, "Basic", ["Front", "Back"])
    cloze = FakeNotetype(1003, "Cloze", ["Text", "Back Extra"], cloze=True)
    notes = [
        FakeNote(
            "guid-mc-1",
            "Carnet B",
            [
                "¿Qué indica esta señal?",
                '<img src="señal 1.png">',
                "2",
                "Prohibido adelantar",
                "Fin de prohibición",
                "Calzada con prioridad",
                "0 1 0",
                "Porque sí. ¿Crees que la respuesta es incorrecta?",
            ],
            tags=["senales"],
        ),
        FakeNote(
            "guid-mc-2",
            "Carnet B",
            ["¿Velocidad máxima en autopista?", "", "2", "100 km/h", "120 km/h", "", "0 1 0", ""],
        ),
        FakeNote(  # two correct answers: must be skipped
            "guid-mc-3",
            "Carnet B",
            ["¿Pregunta múltiple?", "", "1", "Uno", "Dos", "Tres", "1 1 0", ""],
        ),
        FakeNote(
            "guid-basic-1",
            "Basic",
            [
                "¿Qué hacer ante un accidente?<br>A) Huir<br>B) Proteger, avisar y socorrer<br>C) Nada",
                "B",
            ],
            deck="DGT::Accidentes",
        ),
        FakeNote("guid-cloze-1", "Cloze", ["{{c1::Esto}} es cloze", ""]),
    ]
    return [mc, basic, cloze], notes
