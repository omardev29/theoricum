"""Exam rules (permiso B: 30 questions, 30 minutes, at most 3 errors) and per-mode presets."""

from dataclasses import dataclass
from enum import StrEnum


class Mode(StrEnum):
    EXAM = "exam"
    STUDY = "study"
    REVIEW = "review"
    TOPIC = "topic"
    SAVED = "saved"


MODE_LABELS = {
    Mode.EXAM: "Examen",
    Mode.STUDY: "Estudio",
    Mode.REVIEW: "Repaso de fallos",
    Mode.TOPIC: "Por tema",
    Mode.SAVED: "Guardadas",
}


@dataclass(frozen=True, slots=True)
class ExamRules:
    n_questions: int = 30
    time_limit_s: int | None = 30 * 60
    max_errors: int | None = 3  # None: no pass/fail verdict
    immediate_feedback: bool = False
    blanks_count_as_wrong: bool = True


# RD 818/2009, annex VI.B: 30 questions, 1 minute per question, errors <= 10 % (3 of 30).
EXAM_RULES = ExamRules()


def rules_for(mode: Mode, n_questions: int | None = None) -> ExamRules:
    if mode is Mode.EXAM:
        return EXAM_RULES
    return ExamRules(
        n_questions=n_questions or 30,
        time_limit_s=None,
        max_errors=None,
        immediate_feedback=True,
        blanks_count_as_wrong=False,
    )
