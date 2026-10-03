"""Field mapping shared by the Anki importers (.apkg packages and CrowdAnki folders).

Anki notes have arbitrary note types, so each note type is mapped to (question, options, answer,
image, explanation) using, in order: the sidecar `[fields]` table, the anki-mc preset
("AllInOne (kprim, mc, sc)": Question, Q_1…Q_n, Answers bitmask) or field-name heuristics.
"""

import re
import tomllib
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from theoricum.importers.base import PackError, html_to_text, image_sources, strip_number_prefix
from theoricum.importers.native import parse_pack_meta
from theoricum.models import LETTERS, MAX_OPTIONS, MIN_OPTIONS, PackMeta, QuestionData
from theoricum.topics import known_topic, normalize_text, slugify

ANSWER_FORMATS = ("bitmask", "letter", "index", "text")


@dataclass(frozen=True, slots=True)
class NoteType:
    id: str
    name: str
    fields: tuple[str, ...]
    is_cloze: bool = False


@dataclass(frozen=True, slots=True)
class Note:
    guid: str
    notetype: NoteType
    values: tuple[str, ...]
    tags: tuple[str, ...] = ()
    deck: str | None = None

    def get(self, field_name: str | None) -> str:
        if field_name is None or field_name not in self.notetype.fields:
            return ""
        index = self.notetype.fields.index(field_name)
        return self.values[index] if index < len(self.values) else ""


@dataclass(frozen=True, slots=True)
class FieldMapping:
    question: str
    options: tuple[str, ...]
    answer: str | None
    answer_format: str | None = None  # None = detect per note
    image: str | None = None
    explanation: str | None = None


@dataclass(slots=True)
class AnkiSettings:
    meta: PackMeta = field(default_factory=lambda: PackMeta(origin="anki"))
    mapping: FieldMapping | None = None
    notetype: str | None = None
    strip_suffix: tuple[str, ...] = ()
    source: str | None = None


def load_sidecar(path: Path, warnings: list[str], where: str) -> AnkiSettings:
    """Read the optional `<file>.toml` next to an Anki source."""
    settings = AnkiSettings()
    if not path.is_file():
        return settings
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise PackError(f"{path.name}: no se puede leer: {exc}") from exc

    pack = dict(data.get("pack", {}))
    pack.setdefault("origin", "anki")
    settings.meta = parse_pack_meta(pack, warnings, f"{where} › pack")
    settings.source = str(data["source"]) if data.get("source") else None

    clean = data.get("clean", {})
    suffixes = clean.get("strip_suffix", [])
    settings.strip_suffix = tuple(str(s) for s in suffixes) if isinstance(suffixes, list) else ()

    fields = data.get("fields")
    if isinstance(fields, dict):
        settings.notetype = str(fields["notetype"]) if fields.get("notetype") else None
        if fields.get("question"):
            answer_format = fields.get("answer_format")
            if answer_format is not None and answer_format not in ANSWER_FORMATS:
                raise PackError(
                    f"{path.name}: answer_format «{answer_format}» no es válido "
                    f"({', '.join(ANSWER_FORMATS)})"
                )
            options = fields.get("options", [])
            settings.mapping = FieldMapping(
                question=str(fields["question"]),
                options=tuple(str(o) for o in options) if isinstance(options, list) else (),
                answer=str(fields["answer"]) if fields.get("answer") else None,
                answer_format=answer_format,
                image=str(fields["image"]) if fields.get("image") else None,
                explanation=str(fields["explanation"]) if fields.get("explanation") else None,
            )
    return settings


# --- mapping detection ---------------------------------------------------------------------------

_QUESTION_NAMES = {
    "pregunta",
    "question",
    "enunciado",
    "front",
    "anverso",
    "frente",
    "texto",
    "text",
}
_ANSWER_NAMES = {
    "respuesta-correcta", "correcta", "solucion", "answer", "answers", "correct", "correct-answer",
    "respuesta", "back", "reverso", "dorso",
}  # fmt: skip
_IMAGE_NAMES = {"imagen", "image", "foto", "picture", "img", "imagenes", "images"}
_EXPLANATION_NAMES = {
    "explicacion", "explanation", "comentario", "comentarios", "nota", "notas", "notes", "extra",
    "extra-1", "sources", "fuente", "fuentes", "justificacion",
}  # fmt: skip
_OPTION_RE = re.compile(r"^(?:opcion|option|respuesta|resp|answer|alternativa|q)?-?([a-d1-4])$")
_ANKI_MC_OPTION_RE = re.compile(r"^Q_(\d+)$")


def detect_mapping(notetype: NoteType) -> FieldMapping | None:
    names = notetype.fields
    # anki-mc preset (used by the popular "Carnet B" deck).
    mc_options = sorted(
        ((int(m.group(1)), name) for name in names if (m := _ANKI_MC_OPTION_RE.match(name))),
    )
    if "Question" in names and "Answers" in names and mc_options:
        explanation = next((n for n in ("Sources", "Extra 1", "Extra") if n in names), None)
        return FieldMapping(
            question="Question",
            options=tuple(name for _, name in mc_options),
            answer="Answers",
            answer_format="bitmask",
            image="Image" if "Image" in names else None,
            explanation=explanation,
        )

    slugs = {slugify(n): n for n in names}
    question = next((slugs[s] for s in slugs if s in _QUESTION_NAMES), None)
    if question is None:
        return None
    options: list[tuple[str, str]] = []
    for slug, name in slugs.items():
        if name == question:
            continue
        if m := _OPTION_RE.match(slug):
            key = m.group(1)
            options.append((key if key.isalpha() else "abcd"[int(key) - 1], name))
    answer = next((slugs[s] for s in slugs if s in _ANSWER_NAMES and slugs[s] != question), None)
    image = next((slugs[s] for s in slugs if s in _IMAGE_NAMES), None)
    explanation = next(
        (slugs[s] for s in slugs if s in _EXPLANATION_NAMES and slugs[s] not in {question, answer}),
        None,
    )
    return FieldMapping(
        question=question,
        options=tuple(name for _, name in sorted(options)),
        answer=answer,
        image=image,
        explanation=explanation,
    )


# --- conversion ----------------------------------------------------------------------------------

_INLINE_OPTION_RE = re.compile(r"^\s*([A-Da-d])\s*[).\-:]\s+(.+)$")


def _split_inline_options(text: str) -> tuple[str, list[str]]:
    """Split "statement + A) … B) … C) …" written in a single field."""
    lines = text.split("\n")
    first = next((i for i, line in enumerate(lines) if _INLINE_OPTION_RE.match(line)), None)
    if first is None:
        return text, []
    options = []
    for line in lines[first:]:
        if m := _INLINE_OPTION_RE.match(line):
            options.append(m.group(2).strip())
        elif options and line.strip():
            options[-1] += " " + line.strip()
    return "\n".join(lines[:first]).strip(), options


def _parse_answer(
    raw: str, options: list[str], answer_format: str | None
) -> tuple[int | None, str]:
    """Return (index of the single correct option or None, detected format).

    For bitmask/letter/index formats the index is a position among the option *fields*; for
    the text format it is an index into `options`.
    """
    value = raw.strip()
    fmt = answer_format
    if fmt is None:
        if re.fullmatch(r"[01](?:[\s,]+[01])+", value):
            fmt = "bitmask"
        elif re.fullmatch(r"[A-Da-d][).]?", value):
            fmt = "letter"
        elif re.fullmatch(r"[1-4]", value):
            fmt = "index"
        else:
            fmt = "text"
    if fmt == "bitmask":
        bits = re.split(r"[\s,]+", value)
        ones = [i for i, b in enumerate(bits) if b == "1"]
        return (ones[0] if len(ones) == 1 else None), fmt
    if fmt == "letter":
        index = LETTERS.find(value[:1].upper())
        return (index if index >= 0 else None), fmt
    if fmt == "index":
        return (int(value) - 1 if value.isdigit() else None), fmt
    target = normalize_text(strip_number_prefix(value))
    matches = [i for i, o in enumerate(options) if normalize_text(o) == target]
    if len(matches) == 1:
        return matches[0], "text"
    letter = re.match(r"^\s*([A-Da-d])\s*[).\-:]", value)
    return (LETTERS.find(letter.group(1).upper()) if letter else None), "letter"


def _strip_suffixes(text: str, suffixes: tuple[str, ...]) -> str:
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if suffix and text.endswith(suffix):
                text = text[: -len(suffix)].rstrip()
                changed = True
    return text


def _topic_from(note: Note) -> str | None:
    candidates = [part for tag in note.tags for part in tag.split("::")]
    if note.deck:
        candidates.extend(reversed(note.deck.split("::")))
    for candidate in candidates:
        if topic := known_topic(candidate.replace("_", " ")):
            return topic
    return None


@dataclass(slots=True)
class ConversionStats:
    skipped: Counter[str] = field(default_factory=Counter)

    def warnings(self, where: str) -> list[str]:
        return [
            f"{where}: {count} notas omitidas ({reason})" for reason, count in self.skipped.items()
        ]


def convert_notes(
    notes: list[Note],
    settings: AnkiSettings,
    image_ref: Callable[[str], str | None],
    warnings: list[str],
    where: str,
) -> list[QuestionData]:
    """Map Anki notes to questions. `image_ref` turns a media file name into an image ref."""
    stats = ConversionStats()
    mappings: dict[str, FieldMapping | None] = {}
    questions: list[QuestionData] = []
    for note in notes:
        nt = note.notetype
        if settings.notetype and nt.name != settings.notetype:
            stats.skipped[f"tipo de nota «{nt.name}» distinto de «{settings.notetype}»"] += 1
            continue
        if nt.is_cloze:
            stats.skipped[f"tipo cloze «{nt.name}», no es tipo test"] += 1
            continue
        if nt.id not in mappings:
            mappings[nt.id] = settings.mapping or detect_mapping(nt)
            if mappings[nt.id] is None:
                warnings.append(
                    f"{where}: no sé leer el tipo de nota «{nt.name}» (campos: {', '.join(nt.fields)}); "
                    f"indica el mapeo en un sidecar .toml"
                )
        mapping = mappings[nt.id]
        if mapping is None:
            stats.skipped[f"tipo de nota «{nt.name}» sin mapeo"] += 1
            continue
        question = _convert(note, mapping, settings, image_ref, stats)
        if question is not None:
            questions.append(question)
    warnings.extend(stats.warnings(where))
    return questions


def _convert(
    note: Note,
    mapping: FieldMapping,
    settings: AnkiSettings,
    image_ref: Callable[[str], str | None],
    stats: ConversionStats,
) -> QuestionData | None:
    raw_question = note.get(mapping.question)
    text = html_to_text(raw_question)
    if mapping.options:
        pairs = [(i, html_to_text(note.get(name))) for i, name in enumerate(mapping.options)]
    else:
        text, inline = _split_inline_options(text)
        pairs = list(enumerate(inline))
    present = [(i, strip_number_prefix(o) or o) for i, o in pairs if o]
    options = [o for _, o in present]
    if not text:
        stats.skipped["sin enunciado"] += 1
        return None
    if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        stats.skipped[f"número de opciones fuera de {MIN_OPTIONS}–{MAX_OPTIONS}"] += 1
        return None

    raw_answer = html_to_text(note.get(mapping.answer)) if mapping.answer else ""
    answer, fmt = _parse_answer(raw_answer, options, mapping.answer_format)
    if answer is not None and fmt != "text":
        # Positional answers refer to the option fields (or inline letters), some may be empty.
        positions = [i for i, _ in present]
        answer = positions.index(answer) if answer in positions else None
    if answer is None or not 0 <= answer < len(options):
        stats.skipped["sin una única respuesta correcta reconocible"] += 1
        return None

    image = None
    image_html = note.get(mapping.image) if mapping.image else ""
    for name in image_sources(image_html) or image_sources(raw_question):
        image = image_ref(name)
        if image:
            break

    explanation = None
    if mapping.explanation:
        explanation = _strip_suffixes(
            html_to_text(note.get(mapping.explanation)), settings.strip_suffix
        )
    return QuestionData(
        key=f"anki:{note.guid}",
        text=text,
        options=tuple(options),
        answer=answer,
        explanation=explanation or None,
        image_ref=image,
        topic=_topic_from(note),
        date=settings.meta.date,
        tags=note.tags,
        source=settings.source,
    )


def note_to_dict(note: Note) -> dict[str, Any]:
    """Debug helper: a note as {field name: value}."""
    return dict(zip(note.notetype.fields, note.values, strict=False))
