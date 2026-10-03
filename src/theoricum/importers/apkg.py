"""Anki packages (.apkg / .colpkg), read with the standard library only.

Supported package versions (see Anki's `rslib/src/import_export/package`):
  1 legacy  `collection.anki2`   plain SQLite, JSON media map
  2 legacy  `collection.anki21`  plain SQLite, JSON media map
  3 latest  `collection.anki21b` zstd SQLite (WAL header), zstd protobuf media map, zstd media
Images are not extracted: they are referenced as `apkg:<path>!<member>` and read on demand.
"""

import dataclasses
import json
import sqlite3
import zipfile
from collections.abc import Iterator
from pathlib import Path

from theoricum.importers.anki_common import (
    AnkiSettings,
    Note,
    NoteType,
    convert_notes,
    load_sidecar,
)
from theoricum.importers.base import (
    ImportContext,
    ImportResult,
    PackError,
    safe_member_name,
    sidecar_path,
)

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
_COLLECTIONS = {1: "collection.anki2", 2: "collection.anki21", 3: "collection.anki21b"}


# --- minimal protobuf decoding ---------------------------------------------------------------------


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        if pos >= len(buf):
            raise ValueError("truncated varint")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def protobuf_fields(buf: bytes) -> Iterator[tuple[int, int, int | bytes]]:
    """Yield (field number, wire type, value) for each field of a protobuf message."""
    pos = 0
    while pos < len(buf):
        key, pos = _varint(buf, pos)
        number, wire = key >> 3, key & 7
        value: int | bytes
        if wire == 0:
            value, pos = _varint(buf, pos)
        elif wire == 1:
            value, pos = buf[pos : pos + 8], pos + 8
        elif wire == 2:
            length, pos = _varint(buf, pos)
            value, pos = buf[pos : pos + length], pos + length
        elif wire == 5:
            value, pos = buf[pos : pos + 4], pos + 4
        else:
            raise ValueError(f"unsupported wire type {wire}")
        yield number, wire, value


def zstd_decompress(data: bytes) -> bytes:
    try:
        from compression import zstd
    except ImportError as exc:  # Python built without zstd support.
        raise PackError(
            "tu Python no incluye «compression.zstd» y este mazo usa el formato moderno de Anki; "
            "usa un Python 3.14 completo (por ejemplo, `uv python install 3.14`)"
        ) from exc
    return zstd.decompress(data)


# --- package reading ---------------------------------------------------------------------------------


def package_version(zf: zipfile.ZipFile) -> int:
    names = set(zf.namelist())
    if "meta" in names:
        version = 0
        for number, wire, value in protobuf_fields(zf.read("meta")):
            if number == 1 and wire == 0:
                assert isinstance(value, int)
                version = value
        if version not in _COLLECTIONS:
            raise PackError(
                f"paquete de Anki de una versión que no conozco ({version}); actualiza theoricum"
            )
        return version
    if "collection.anki21" in names:
        return 2
    if "collection.anki2" in names:
        return 1
    raise PackError("no parece un paquete de Anki: falta la colección")


def open_collection(zf: zipfile.ZipFile, version: int) -> sqlite3.Connection:
    try:
        raw = zf.read(_COLLECTIONS[version])
    except KeyError as exc:
        raise PackError(f"al paquete le falta «{_COLLECTIONS[version]}»") from exc
    if raw[:4] == ZSTD_MAGIC:
        raw = zstd_decompress(raw)
    if raw[:16] != b"SQLite format 3\x00":
        raise PackError("la colección del paquete no es una base de datos SQLite")
    data = bytearray(raw)
    data[18] = data[19] = 1  # WAL -> rollback journal, otherwise deserialize() cannot open it
    conn = sqlite3.connect(":memory:")
    conn.deserialize(bytes(data))
    conn.create_collation("unicase", _unicase)
    return conn


def _unicase(a: str, b: str) -> int:
    a, b = a.casefold(), b.casefold()
    return (a > b) - (a < b)


def media_map(zf: zipfile.ZipFile, version: int) -> dict[str, str]:
    """Map media file names (as used in note fields) to zip member names."""
    if "media" not in zf.namelist():
        return {}
    raw = zf.read("media")
    mapping: dict[str, str] = {}
    if version == 3 or raw[:4] == ZSTD_MAGIC:
        entries = zstd_decompress(raw) if raw[:4] == ZSTD_MAGIC else raw
        index = 0
        for number, wire, entry in protobuf_fields(entries):
            if number != 1 or wire != 2:
                continue
            assert isinstance(entry, bytes)
            name, member = None, str(index)
            for f_number, f_wire, f_value in protobuf_fields(entry):
                if f_number == 1 and f_wire == 2:
                    assert isinstance(f_value, bytes)
                    name = f_value.decode("utf-8")
                elif f_number == 255 and f_wire == 0:
                    member = str(f_value)
            if name:
                mapping[name] = member
            index += 1
        return mapping
    for member, name in json.loads(raw.decode("utf-8")).items():
        mapping[str(name)] = str(member)
    return mapping


def read_notes(conn: sqlite3.Connection) -> list[Note]:
    (schema,) = conn.execute("SELECT ver FROM col").fetchone()
    notetypes: dict[int, NoteType] = {}
    decks: dict[int, str] = {}
    if schema >= 15:
        fields: dict[int, list[tuple[int, str]]] = {}
        for ntid, ord_, name in conn.execute("SELECT ntid, ord, name FROM fields"):
            fields.setdefault(ntid, []).append((ord_, name))
        for ntid, name, config in conn.execute("SELECT id, name, config FROM notetypes"):
            kind = 0
            for number, wire, value in protobuf_fields(config or b""):
                if number == 1 and wire == 0:
                    assert isinstance(value, int)
                    kind = value
            ordered = tuple(n for _, n in sorted(fields.get(ntid, [])))
            notetypes[ntid] = NoteType(str(ntid), name, ordered, is_cloze=kind == 1)
        for did, name in conn.execute("SELECT id, name FROM decks"):
            decks[did] = name.replace("\x1f", "::")
    else:
        models_json, decks_json = conn.execute("SELECT models, decks FROM col").fetchone()
        for mid, model in json.loads(models_json).items():
            ordered = tuple(f["name"] for f in sorted(model["flds"], key=lambda f: f["ord"]))
            notetypes[int(mid)] = NoteType(
                mid, model["name"], ordered, is_cloze=model.get("type") == 1
            )
        for did, deck in json.loads(decks_json).items():
            decks[int(did)] = deck["name"]

    note_decks: dict[int, int] = {}
    for nid, did in conn.execute(
        "SELECT nid, CASE WHEN odid != 0 THEN odid ELSE did END FROM cards ORDER BY ord"
    ):
        note_decks.setdefault(nid, did)

    notes = []
    for nid, guid, mid, tags, flds in conn.execute(
        "SELECT id, guid, mid, tags, flds FROM notes ORDER BY id"
    ):
        notetype = notetypes.get(mid)
        if notetype is None:
            continue
        notes.append(
            Note(
                guid=guid,
                notetype=notetype,
                values=tuple(flds.split("\x1f")),
                tags=tuple(tags.replace("　", " ").split()),
                deck=decks.get(note_decks.get(nid, -1)),
            )
        )
    return notes


class ApkgImporter:
    kind = "apkg"

    def detect(self, path: Path) -> bool:
        return path.suffix.lower() in {".apkg", ".colpkg"} and zipfile.is_zipfile(path)

    def related_files(self, path: Path) -> list[Path]:
        return [sidecar_path(path)]

    def load(self, ctx: ImportContext) -> ImportResult:
        warnings: list[str] = []
        settings: AnkiSettings = load_sidecar(sidecar_path(ctx.path), warnings, ctx.rel_path)
        try:
            with zipfile.ZipFile(ctx.path) as zf:
                version = package_version(zf)
                conn = open_collection(zf, version)
                try:
                    notes = read_notes(conn)
                finally:
                    conn.close()
                media = media_map(zf, version)
                members = set(zf.namelist())
        except (zipfile.BadZipFile, sqlite3.DatabaseError, ValueError, KeyError) as exc:
            raise PackError(f"paquete de Anki dañado o no soportado: {exc}") from exc

        missing: set[str] = set()

        def image_ref(name: str) -> str | None:
            member = media.get(name)
            if member is None or not safe_member_name(name) or member not in members:
                missing.add(name)
                return None
            return f"apkg:{ctx.rel_path}!{member}"

        meta = settings.meta
        if meta.name is None:
            meta = dataclasses.replace(meta, name=ctx.path.stem)
        questions = convert_notes(notes, settings, image_ref, warnings, ctx.rel_path)
        if missing:
            warnings.append(
                f"{ctx.rel_path}: {len(missing)} imágenes referenciadas no están en el paquete"
            )
        return ImportResult(meta=meta, questions=questions, warnings=warnings)
