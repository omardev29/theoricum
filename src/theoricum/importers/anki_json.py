"""CrowdAnki decks: a folder with `deck.json` and a `media/` subfolder."""

import dataclasses
import json
import re
from pathlib import Path
from typing import Any

from theoricum.importers.anki_common import Note, NoteType, convert_notes, load_sidecar
from theoricum.importers.base import (
    ImportContext,
    ImportResult,
    PackError,
    safe_member_name,
    sidecar_path,
)

_DECK_RE = re.compile(r'"__type__"\s*:\s*"Deck"')


class CrowdAnkiImporter:
    kind = "crowdanki"

    def detect(self, path: Path) -> bool:
        if path.suffix.lower() != ".json":
            return False
        with path.open("rb") as fh:
            head = fh.read(4096).decode("utf-8", errors="ignore")
        return bool(_DECK_RE.search(head))

    def related_files(self, path: Path) -> list[Path]:
        return [sidecar_path(path)]

    def load(self, ctx: ImportContext) -> ImportResult:
        warnings: list[str] = []
        settings = load_sidecar(sidecar_path(ctx.path), warnings, ctx.rel_path)
        try:
            with ctx.path.open(encoding="utf-8") as fh:
                deck = json.load(fh)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PackError(f"no se puede leer el deck.json: {exc}") from exc
        if not isinstance(deck, dict) or deck.get("__type__") != "Deck":
            raise PackError("no es un deck.json de CrowdAnki")

        notetypes = {}
        for model in deck.get("note_models", []):
            ordered = tuple(
                f["name"] for f in sorted(model.get("flds", []), key=lambda f: f["ord"])
            )
            notetypes[model["crowdanki_uuid"]] = NoteType(
                model["crowdanki_uuid"],
                model.get("name", "?"),
                ordered,
                is_cloze=model.get("type") == 1,
            )

        notes: list[Note] = []
        unknown_models = 0
        for deck_name, raw in _walk(deck, None):
            notetype = notetypes.get(raw.get("note_model_uuid"))
            if notetype is None:
                unknown_models += 1
                continue
            notes.append(
                Note(
                    guid=raw["guid"],
                    notetype=notetype,
                    values=tuple(raw.get("fields", [])),
                    tags=tuple(raw.get("tags", [])),
                    deck=deck_name,
                )
            )
        if unknown_models:
            warnings.append(
                f"{ctx.rel_path}: {unknown_models} notas con un tipo de nota desconocido"
            )

        media_dir = ctx.path.parent / "media"

        def image_ref(name: str) -> str | None:
            if not safe_member_name(name) or not (media_dir / name).is_file():
                return None
            return ctx.file_ref(f"media/{name}")

        meta = settings.meta
        if meta.name is None:
            meta = dataclasses.replace(meta, name=deck.get("name") or ctx.path.parent.name)
        questions = convert_notes(notes, settings, image_ref, warnings, ctx.rel_path)
        return ImportResult(meta=meta, questions=questions, warnings=warnings)


def _walk(deck: dict[str, Any], parent: str | None):
    """Yield (full deck name, note) for a deck and its children, joining names with `::`."""
    name = deck.get("name") or ""
    full = f"{parent}::{name}" if parent else name
    for note in deck.get("notes", []):
        yield full, note
    for child in deck.get("children", []):
        yield from _walk(child, full)
