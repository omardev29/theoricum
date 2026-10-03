"""Glue between the store and the engine: builds tests and records them. Used by the TUI."""

import random
from collections.abc import Iterable
from dataclasses import dataclass

from theoricum.db.store import Store
from theoricum.engine.rules import Mode, rules_for
from theoricum.engine.selection import (
    filter_topic,
    pick_exam,
    pick_review,
    pick_study,
    question_stats,
    review_pool,
)
from theoricum.engine.session import TestSession
from theoricum.engine.stats import Overview, overview
from theoricum.models import Question
from theoricum.topics import topic_name


@dataclass(frozen=True, slots=True)
class TopicSummary:
    slug: str
    name: str
    count: int
    answered: int
    accuracy: float | None


class Practice:
    def __init__(self, store: Store, *, since: str | None = None, seed: int | None = None) -> None:
        self.store = store
        self.since = since
        self.rng = random.Random(seed)
        self._pool: list[Question] | None = None

    def invalidate(self) -> None:
        self._pool = None

    @property
    def pool(self) -> list[Question]:
        if self._pool is None:
            self._pool = self.store.load_questions(since=self.since)
        return self._pool

    def _stats(self):
        group_of, _ = self.store.question_index()
        return question_stats(self.store.answer_events(), group_of)

    def review_count(self) -> int:
        return len(review_pool(self.pool, self._stats()))

    def review_progress(self, questions: Iterable[Question]) -> dict[str, int]:
        """Right answers in a row of the given questions that are pending review (by key)."""
        stats = self._stats()
        progress: dict[str, int] = {}
        for question in questions:
            entry = stats.get(question.dedup)
            if entry is not None and entry.in_review:
                progress[question.key] = entry.streak
        return progress

    def overview(self) -> Overview:
        group_of, topic_of = self.store.question_index()
        return overview(
            self.store.answer_events(),
            self.store.exam_records(),
            self.pool,
            group_of=group_of,
            topic_of=topic_of,
        )

    def topics(self) -> list[TopicSummary]:
        data = self.overview()
        rows = [
            TopicSummary(t.topic, topic_name(t.topic), t.pool_size, t.answered, t.accuracy)
            for t in data.topics
            if t.pool_size
        ]
        return sorted(rows, key=lambda t: t.name)

    def build(
        self, mode: Mode, *, topic: str | None = None, n: int | None = None
    ) -> TestSession | None:
        """Pick the questions for a new test, or None if there are none to ask."""
        rules = rules_for(mode, n)
        pool = filter_topic(self.pool, topic)
        if mode is Mode.EXAM:
            questions = pick_exam(pool, rules.n_questions, self.rng)
        elif mode is Mode.REVIEW:
            questions = pick_review(pool, rules.n_questions, self.rng, self._stats())
        else:
            questions = pick_study(pool, rules.n_questions, self.rng, self._stats())
        if not questions:
            return None
        return TestSession(questions, rules, mode, topic=topic)

    # --- persistence ------------------------------------------------------------------------

    def start(self, session: TestSession) -> int:
        return self.store.start_session(
            mode=session.mode.value,
            keys=[q.key for q in session.questions],
            topic=session.topic,
            time_limit_s=session.rules.time_limit_s,
        )

    def record(self, session_id: int, session: TestSession, index: int) -> None:
        self.store.record_answer(
            session_id, index, session.answers[index], session.is_correct(index)
        )

    def finish(self, session_id: int, session: TestSession) -> None:
        result = session.result or session.submit()
        self.store.finish_session(
            session_id,
            n_correct=result.grade.n_correct,
            n_wrong=result.grade.n_wrong,
            n_blank=result.grade.n_blank,
            passed=result.passed,
            elapsed_s=result.elapsed_s,
            blanks_count_as_wrong=session.rules.blanks_count_as_wrong,
        )

    def abandon(self, session_id: int, session: TestSession) -> None:
        self.store.abandon_session(session_id, session.elapsed())

    def set_disabled(self, key: str, disabled: bool) -> None:
        self.store.set_flag(key, disabled=disabled)
        self.invalidate()

    def flags(self):
        return self.store.flags()

    # --- saved questions («Preguntas guardadas») ---------------------------------------------

    def saved_keys(self) -> dict[str, str]:
        return self.store.saved()

    def is_saved(self, key: str) -> bool:
        return key in self.store.saved()

    def toggle_saved(self, key: str) -> bool:
        """Save or unsave a question; returns whether it is saved now."""
        saved = not self.is_saved(key)
        self.store.set_saved(key, saved)
        return saved

    def saved_questions(self) -> list[tuple[Question, str]]:
        """Saved questions (most recent first) with their save date; missing sources are skipped."""
        saved = self.store.saved()
        found = self.store.questions_by_key(saved)
        return [(found[key], when) for key, when in saved.items() if key in found]
