"""Shared data classes used across importers, the library, the engine and the TUI."""

from dataclasses import dataclass

FORMAT_ID = "theoricum/1"

ORIGINS = ("dgt", "revista-dgt", "anki", "ia", "otro")
DEFAULT_PRIORITY = {"dgt": 100, "revista-dgt": 90, "anki": 50, "ia": 10, "otro": 0}
ORIGIN_LABELS = {
    "dgt": "DGT (oficial)",
    "revista-dgt": "Revista Tráfico y Seguridad Vial",
    "anki": "Anki",
    "ia": "Generada con IA",
    "otro": "Otra fuente",
}

LETTERS = "ABCD"
MIN_OPTIONS = 2
MAX_OPTIONS = len(LETTERS)


@dataclass(frozen=True, slots=True)
class PackMeta:
    """Pack-level metadata, shared by every question of a source."""

    id: str | None = None
    name: str | None = None
    origin: str = "otro"
    date: str | None = None
    topic: str | None = None
    priority: int | None = None
    enabled: bool = True
    exclude_topics: tuple[str, ...] = ()

    @property
    def effective_priority(self) -> int:
        if self.priority is not None:
            return self.priority
        return DEFAULT_PRIORITY.get(self.origin, 0)


@dataclass(frozen=True, slots=True)
class QuestionData:
    """A normalized question as produced by an importer."""

    key: str
    text: str
    options: tuple[str, ...]
    answer: int
    explanation: str | None = None
    image_ref: str | None = None
    topic: str | None = None
    date: str | None = None
    tags: tuple[str, ...] = ()
    source: str | None = None


@dataclass(frozen=True, slots=True)
class Question:
    """A question ready to be asked, as loaded from the database."""

    key: str
    text: str
    options: tuple[str, ...]
    answer: int
    topic: str
    origin: str
    dedup: str
    priority: int = 0
    explanation: str | None = None
    image_ref: str | None = None
    date: str | None = None
    source: str | None = None
    source_name: str | None = None
    tags: tuple[str, ...] = ()

    @property
    def answer_letter(self) -> str:
        return LETTERS[self.answer]


@dataclass(frozen=True, slots=True)
class AnswerEvent:
    """One graded attempt at a question, in chronological order."""

    key: str
    correct: bool
    at: str


@dataclass(frozen=True, slots=True)
class ExamRecord:
    """A finished exam-mode session."""

    started_at: str
    n_questions: int
    n_correct: int
    n_wrong: int
    n_blank: int
    passed: bool
    elapsed_s: float | None


@dataclass(frozen=True, slots=True)
class Flag:
    disabled: bool = False
    flagged: bool = False
    note: str | None = None
    updated_at: str | None = None
