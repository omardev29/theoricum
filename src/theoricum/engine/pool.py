"""Choose one question per duplicate group (`dedup`) when several sources have it.

If every copy agrees on the right answer, the source with the highest priority wins (official DGT >
magazine > Anki > AI). If they disagree:

- when the statement refers to its picture («¿Qué indica esta señal?», «este vehículo…»), they
  are different questions that only share the wording: all of them are kept;
- otherwise the rules probably changed in between, so the most recent copy wins and carries a
  note about the other answer.
"""

import dataclasses
import re
from collections.abc import Iterable

from theoricum.models import Notice, Question, date_label
from theoricum.topics import normalize_text


def _answer_text(question: Question) -> str:
    value = re.sub(r"[^\w\s]", " ", normalize_text(question.options[question.answer]))
    return " ".join(value.split())


def _conflict_notice(others: list[Question]) -> Notice:
    parts = []
    for other in others:
        where = other.source_label
        if when := date_label(other.date):
            where += f", {when}"
        parts.append(f"{where}: «{other.options[other.answer]}»")
    return Notice(
        "info",
        "Otras fuentes dan otra respuesta ("
        + "; ".join(parts)
        + "). Se usa la de fecha más reciente, porque la norma ha podido cambiar.",
        "conflict",
    )


# «esta señal», «este vehículo», «la imagen»…: the answer depends on the picture.
_PICTURE_RE = re.compile(
    r"\b(?:est[ae]s?|la imagen|la fotograf[ií]a|la figura|el dibujo|la ilustraci[oó]n)\b",
    re.IGNORECASE,
)


def refers_to_picture(question: Question) -> bool:
    return question.image_ref is not None and bool(_PICTURE_RE.search(question.text))


def pick_copies(copies: list[Question]) -> list[Question]:
    """The copies of one duplicate group that are asked (usually one)."""
    copies = sorted(copies, key=lambda q: q.key)
    by_answer: dict[str, list[Question]] = {}
    for question in copies:
        by_answer.setdefault(_answer_text(question), []).append(question)
    if len(by_answer) == 1:
        return [min(copies, key=lambda q: -q.priority)]
    if all(refers_to_picture(q) for q in copies):
        return [min(same, key=lambda q: -q.priority) for same in by_answer.values()]
    winner = max(copies, key=lambda q: (q.date or "", q.priority))
    disagree = [q for q in copies if _answer_text(q) != _answer_text(winner)]
    return [dataclasses.replace(winner, notices=(*winner.notices, _conflict_notice(disagree)))]


def resolve_duplicates(questions: Iterable[Question]) -> list[Question]:
    """The questions to ask, one per duplicate group (see `pick_copies`), sorted by key."""
    groups: dict[str, list[Question]] = {}
    for question in questions:
        groups.setdefault(question.dedup, []).append(question)
    picked = [q for copies in groups.values() for q in pick_copies(copies)]
    return sorted(picked, key=lambda q: q.key)
