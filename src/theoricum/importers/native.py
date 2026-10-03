"""Native `theoricum/1` packs, written as JSON or TOML (same schema)."""

import datetime as dt
import json
import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

from theoricum.importers.base import ImportContext, ImportResult, PackError
from theoricum.models import (
    FORMAT_ID,
    LETTERS,
    MAX_OPTIONS,
    MIN_OPTIONS,
    ORIGINS,
    PackMeta,
    QuestionData,
)
from theoricum.topics import resolve_topic

_JSON_FORMAT_RE = re.compile(r'"format"\s*:\s*"theoricum/')
_TOML_FORMAT_RE = re.compile(r'^\s*format\s*=\s*["\']theoricum/', re.MULTILINE)
_SNIFF_BYTES = 4096


def _read_head(path: Path) -> str:
    with path.open("rb") as fh:
        return fh.read(_SNIFF_BYTES).decode("utf-8", errors="ignore")


def parse_document(path: Path) -> dict[str, Any]:
    """Parse a JSON or TOML file into a dict, with a Spanish error message on failure."""
    try:
        if path.suffix.lower() == ".toml":
            with path.open("rb") as fh:
                data = tomllib.load(fh)
        else:
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
    except (tomllib.TOMLDecodeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PackError(f"no se puede leer el archivo: {exc}") from exc
    if not isinstance(data, dict):
        raise PackError("el documento debe ser un objeto/tabla en la raíz")
    return data


def _as_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()[:10]
    return str(value).strip() or None


def parse_pack_meta(raw: Any, warn: list[str], where: str) -> PackMeta:
    """Validate a `[pack]` table (also used by Anki sidecars)."""
    if raw is None:
        return PackMeta()
    if not isinstance(raw, dict):
        warn.append(f"{where}: «pack» debe ser una tabla; se ignora")
        return PackMeta()
    origin = str(raw.get("origin", "otro")).strip().lower()
    if origin not in ORIGINS:
        warn.append(
            f"{where}.origin: «{origin}» no es válido ({', '.join(ORIGINS)}); se usa «otro»"
        )
        origin = "otro"
    priority = raw.get("priority")
    if priority is not None and not isinstance(priority, int):
        warn.append(f"{where}.priority: debe ser un número entero; se ignora")
        priority = None
    exclude = raw.get("exclude_topics", [])
    if not isinstance(exclude, list):
        warn.append(f"{where}.exclude_topics: debe ser una lista; se ignora")
        exclude = []
    topic = raw.get("topic")
    return PackMeta(
        id=str(raw["id"]).strip() if raw.get("id") else None,
        name=str(raw["name"]).strip() if raw.get("name") else None,
        origin=origin,
        date=_as_date(raw.get("date")),
        topic=resolve_topic(str(topic)) if topic else None,
        priority=priority,
        enabled=bool(raw.get("enabled", True)),
        exclude_topics=tuple(resolve_topic(str(t)) for t in exclude),
    )


def parse_answer(value: Any, n_options: int) -> int:
    """Answer letter (A–D, case-insensitive) to option index."""
    if not isinstance(value, str) or len(value.strip()) != 1:
        raise ValueError(f"«{value}» debe ser una letra ({LETTERS[:n_options]})")
    index = LETTERS.find(value.strip().upper())
    if index < 0 or index >= n_options:
        raise ValueError(f"«{value}» no existe ({n_options} opciones)")
    return index


class NativeImporter:
    kind = "native"

    def detect(self, path: Path) -> bool:
        suffix = path.suffix.lower()
        if suffix == ".json":
            return bool(_JSON_FORMAT_RE.search(_read_head(path)))
        if suffix == ".toml":
            return bool(_TOML_FORMAT_RE.search(_read_head(path)))
        return False

    def related_files(self, path: Path) -> list[Path]:
        return []

    def load(self, ctx: ImportContext) -> ImportResult:
        data = parse_document(ctx.path)
        fmt = data.get("format")
        if fmt != FORMAT_ID:
            raise PackError(f"formato «{fmt}» no soportado (se esperaba «{FORMAT_ID}»)")

        warnings: list[str] = []
        where = ctx.rel_path
        meta = parse_pack_meta(data.get("pack"), warnings, f"{where} › pack")
        # Without an id, the path inside questions/ is the namespace. It always uses `/`, so keys
        # (and the history that references them) are the same on Linux, macOS and Windows.
        namespace = meta.id or str(PurePosixPath(ctx.rel_path).with_suffix(""))

        raw_questions = data.get("questions")
        if not isinstance(raw_questions, list):
            raise PackError("falta la lista «questions»")
        if not raw_questions:
            warnings.append(f"{where}: el pack no tiene preguntas")

        questions: list[QuestionData] = []
        seen_ids: set[str] = set()
        for i, raw in enumerate(raw_questions):
            loc = f"{where} › questions[{i}]"
            try:
                question = self._parse_question(raw, i, ctx, namespace, warnings, loc)
            except ValueError as exc:
                warnings.append(f"{loc}{exc}; se omite")
                continue
            local_id = question.key.split(":", 1)[1]
            if local_id in seen_ids:
                warnings.append(f"{loc}.id: «{local_id}» está repetido; se omite")
                continue
            seen_ids.add(local_id)
            questions.append(question)
        return ImportResult(meta=meta, questions=questions, warnings=warnings)

    def _parse_question(
        self,
        raw: Any,
        index: int,
        ctx: ImportContext,
        namespace: str,
        warnings: list[str],
        loc: str,
    ) -> QuestionData:
        if not isinstance(raw, dict):
            raise ValueError(": debe ser una tabla/objeto")

        qid = raw.get("id")
        if qid is None or str(qid).strip() == "":
            qid = f"q{index + 1}"
            warnings.append(
                f"{loc}.id: falta; se usa «{qid}» (si reordenas el pack se pierde el historial)"
            )
        qid = str(qid).strip()

        text = raw.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(".text: falta el enunciado")

        options = raw.get("options")
        if not isinstance(options, list) or not all(
            isinstance(o, str) and o.strip() for o in options
        ):
            raise ValueError(".options: debe ser una lista de textos no vacíos")
        if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
            raise ValueError(f".options: debe tener entre {MIN_OPTIONS} y {MAX_OPTIONS} opciones")

        try:
            answer = parse_answer(raw.get("answer"), len(options))
        except ValueError as exc:
            raise ValueError(f".answer: {exc}") from exc

        image_ref = None
        image = raw.get("image")
        if image:
            image_ref = ctx.file_ref(str(image))
            if image_ref is None:
                warnings.append(f"{loc}.image: «{image}» sale de la carpeta questions/; se ignora")
            elif not (ctx.path.parent / str(image)).is_file():
                warnings.append(f"{loc}.image: no existe «{image}»")

        tags = raw.get("tags", [])
        if not isinstance(tags, list):
            warnings.append(f"{loc}.tags: debe ser una lista; se ignora")
            tags = []
        topic = raw.get("topic")
        explanation = raw.get("explanation")
        source = raw.get("source")
        return QuestionData(
            key=f"{namespace}:{qid}",
            text=text.strip(),
            options=tuple(o.strip() for o in options),
            answer=answer,
            explanation=str(explanation).strip() or None if explanation else None,
            image_ref=image_ref,
            topic=resolve_topic(str(topic)) if topic else None,
            date=_as_date(raw.get("date")),
            tags=tuple(str(t) for t in tags),
            source=str(source).strip() or None if source else None,
        )
