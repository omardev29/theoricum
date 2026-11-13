"""Regulatory changes that may leave older questions outdated (data/changes.toml).

A question dated before a change (or without a date) that talks about what the change affects gets
a `Notice`: `warning` marks it as possibly outdated (and keeps it out of exams), `info` adds a note
shown once the answer is revealed.
"""

import dataclasses
import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from importlib import resources

from theoricum.models import Notice, Question
from theoricum.topics import keyword_pattern, normalize_text, resolve_topic

LEVELS = ("warning", "info")
_DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


@dataclass(frozen=True, slots=True)
class Change:
    id: str
    since: str
    level: str
    note: str
    pattern: re.Pattern[str]
    also: re.Pattern[str] | None = None
    topics: frozenset[str] = frozenset()

    def applies_to(self, question: Question, text: str) -> bool:
        """`text` is the normalized statement and right answer (see `notices_for`)."""
        if question.date and question.date >= self.since:
            return False
        if self.topics and question.topic not in self.topics:
            return False
        if not self.pattern.search(text):
            return False
        return self.also is None or bool(self.also.search(text))


def parse_changes(raw: str) -> tuple[Change, ...]:
    changes = []
    for entry in tomllib.loads(raw).get("change", []):
        since, level = str(entry["since"]), str(entry.get("level", "info"))
        pattern = keyword_pattern(entry.get("keywords", []))
        if not _DATE_RE.match(since) or level not in LEVELS or pattern is None:
            raise ValueError(f"changes.toml: «{entry.get('id')}» no es válido")
        changes.append(
            Change(
                id=str(entry["id"]),
                since=since,
                level=level,
                note=" ".join(str(entry["note"]).split()),
                pattern=pattern,
                also=keyword_pattern(entry.get("also", [])),
                topics=frozenset(resolve_topic(t) for t in entry.get("topics", [])),
            )
        )
    return tuple(changes)


@cache
def load_changes() -> tuple[Change, ...]:
    raw = resources.files("theoricum.data").joinpath("changes.toml").read_text(encoding="utf-8")
    return parse_changes(raw)


def notices_for(question: Question, changes: Iterable[Change] | None = None) -> tuple[Notice, ...]:
    # Only the statement and the right answer: a wrong option about an old rule is still wrong.
    text = normalize_text(f"{question.text}\n{question.options[question.answer]}")
    return tuple(
        Notice(change.level, change.note, change.id)
        for change in (load_changes() if changes is None else changes)
        if change.applies_to(question, text)
    )


def annotate(questions: Iterable[Question]) -> list[Question]:
    """The same questions, with the notices of the changes that affect them added."""
    result = []
    for question in questions:
        found = notices_for(question)
        if found:
            question = dataclasses.replace(question, notices=question.notices + found)
        result.append(question)
    return result
