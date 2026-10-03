"""An in-progress test: answers, navigation, timer and submission."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from theoricum.engine.grading import Grade, grade
from theoricum.engine.rules import ExamRules, Mode
from theoricum.models import Question

Clock = Callable[[], float]


class SlotState(StrEnum):
    BLANK = "blank"  # not answered yet
    ANSWERED = "answered"  # answered, correctness hidden (exam in progress)
    CORRECT = "correct"
    WRONG = "wrong"
    MISSED = "missed"  # left blank in a corrected test


@dataclass(frozen=True, slots=True)
class Result:
    mode: Mode
    n_questions: int
    grade: Grade
    elapsed_s: float
    timed_out: bool

    @property
    def passed(self) -> bool | None:
        return self.grade.passed


class TestSession:
    __test__ = False  # not a pytest test class

    def __init__(
        self,
        questions: list[Question],
        rules: ExamRules,
        mode: Mode,
        *,
        clock: Clock = time.monotonic,
        topic: str | None = None,
    ) -> None:
        if not questions:
            raise ValueError("a test needs at least one question")
        self.questions = questions
        self.rules = rules
        self.mode = mode
        self.topic = topic
        self.answers: list[int | None] = [None] * len(questions)
        self.current = 0
        self._clock = clock
        self._started = clock()
        self._ended: float | None = None
        self.result: Result | None = None

    # --- navigation -------------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self.questions)

    @property
    def question(self) -> Question:
        return self.questions[self.current]

    def goto(self, index: int) -> bool:
        if 0 <= index < len(self.questions) and index != self.current:
            self.current = index
            return True
        return False

    def next(self) -> bool:
        return self.goto(self.current + 1)

    def prev(self) -> bool:
        return self.goto(self.current - 1)

    def next_unanswered(self) -> int | None:
        """First blank question after the current one (wrapping around)."""
        n = len(self.questions)
        for step in range(1, n + 1):
            index = (self.current + step) % n
            if self.answers[index] is None:
                return index
        return None

    # --- answering --------------------------------------------------------------------------

    @property
    def finished(self) -> bool:
        return self.result is not None

    def is_locked(self, index: int | None = None) -> bool:
        index = self.current if index is None else index
        if self.finished:
            return True
        return self.rules.immediate_feedback and self.answers[index] is not None

    def answer(self, choice: int, index: int | None = None) -> bool:
        """Record an answer. In exam mode it can be changed until submitting."""
        index = self.current if index is None else index
        if self.is_locked(index) or not 0 <= choice < len(self.questions[index].options):
            return False
        self.answers[index] = choice
        return True

    def is_correct(self, index: int) -> bool | None:
        chosen = self.answers[index]
        return None if chosen is None else chosen == self.questions[index].answer

    def reveals(self, index: int | None = None) -> bool:
        """Whether the correct answer can be shown for a question."""
        index = self.current if index is None else index
        return self.finished or (self.rules.immediate_feedback and self.answers[index] is not None)

    def state(self, index: int) -> SlotState:
        chosen = self.answers[index]
        if not self.reveals(index):
            return SlotState.BLANK if chosen is None else SlotState.ANSWERED
        if chosen is None:
            return SlotState.MISSED
        return SlotState.CORRECT if chosen == self.questions[index].answer else SlotState.WRONG

    @property
    def n_answered(self) -> int:
        return sum(1 for a in self.answers if a is not None)

    @property
    def n_unanswered(self) -> int:
        return len(self.answers) - self.n_answered

    @property
    def all_answered(self) -> bool:
        return self.n_unanswered == 0

    # --- time -------------------------------------------------------------------------------

    def elapsed(self) -> float:
        end = self._ended if self._ended is not None else self._clock()
        return max(0.0, end - self._started)

    def remaining(self) -> float | None:
        if self.rules.time_limit_s is None:
            return None
        return max(0.0, self.rules.time_limit_s - self.elapsed())

    def is_expired(self) -> bool:
        remaining = self.remaining()
        return remaining is not None and remaining <= 0

    # --- submission -------------------------------------------------------------------------

    def submit(self, *, timed_out: bool = False) -> Result:
        if self.result is not None:
            return self.result
        self._ended = self._clock()
        if self.rules.time_limit_s is not None:
            self._ended = min(self._ended, self._started + self.rules.time_limit_s)
        self.result = Result(
            mode=self.mode,
            n_questions=len(self.questions),
            grade=grade(self.questions, self.answers, self.rules),
            elapsed_s=self.elapsed(),
            timed_out=timed_out,
        )
        return self.result
