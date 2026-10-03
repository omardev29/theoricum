"""Grading: blanks count as errors in the exam; pass if errors <= max_errors."""

from collections.abc import Sequence
from dataclasses import dataclass

from theoricum.engine.rules import ExamRules
from theoricum.models import Question


@dataclass(frozen=True, slots=True)
class Grade:
    n_correct: int
    n_wrong: int
    n_blank: int
    errors: int
    passed: bool | None


def grade(questions: Sequence[Question], answers: Sequence[int | None], rules: ExamRules) -> Grade:
    n_correct = sum(
        1 for q, a in zip(questions, answers, strict=True) if a is not None and a == q.answer
    )
    n_blank = sum(1 for a in answers if a is None)
    n_wrong = len(answers) - n_correct - n_blank
    errors = n_wrong + (n_blank if rules.blanks_count_as_wrong else 0)
    passed = None if rules.max_errors is None else errors <= rules.max_errors
    return Grade(n_correct, n_wrong, n_blank, errors, passed)
