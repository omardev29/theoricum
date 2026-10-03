import random

import pytest

from theoricum.engine.grading import grade
from theoricum.engine.rules import EXAM_RULES, Mode, rules_for
from theoricum.engine.selection import (
    MASTERED_STREAK,
    pick_exam,
    pick_review,
    pick_study,
    question_stats,
    review_pool,
    review_weight,
)
from theoricum.engine.session import SlotState, TestSession
from theoricum.engine.stats import overview, pass_probability
from theoricum.models import AnswerEvent, ExamRecord

from conftest import question


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def exam_with(n_wrong: int, n_blank: int = 0) -> TestSession:
    qs = [question(f"k{i}", answer=0) for i in range(30)]
    s = TestSession(qs, EXAM_RULES, Mode.EXAM, clock=FakeClock())
    for i in range(30):
        if i < n_wrong:
            s.answer(1, i)
        elif i < n_wrong + n_blank:
            continue
        else:
            s.answer(0, i)
    return s


@pytest.mark.parametrize(
    ("wrong", "blank", "passed"),
    [(0, 0, True), (3, 0, True), (4, 0, False), (2, 1, True), (2, 2, False)],
)
def test_exam_pass_rule_counts_blanks_as_errors(wrong, blank, passed):
    result = exam_with(wrong, blank).submit()
    assert result.passed is passed
    assert result.grade.n_blank == blank
    assert result.grade.errors == wrong + blank


def test_study_rules_have_no_verdict_and_ignore_blanks():
    rules = rules_for(Mode.STUDY, 5)
    qs = [question(f"k{i}") for i in range(5)]
    g = grade(qs, [0, 1, None, None, 0], rules)
    assert (g.n_correct, g.n_wrong, g.n_blank, g.errors, g.passed) == (2, 1, 2, 1, None)


def test_exam_answers_can_change_until_submit_and_hide_correctness():
    s = exam_with(0)
    assert s.answer(2, 0)
    assert s.answer(0, 0)
    assert s.state(0) is SlotState.ANSWERED
    assert not s.reveals(0)
    s.submit()
    assert not s.answer(1, 0)
    assert s.state(0) is SlotState.CORRECT


def test_study_locks_answer_and_reveals_immediately():
    qs = [question("a", answer=1), question("b", answer=0)]
    s = TestSession(qs, rules_for(Mode.STUDY, 2), Mode.STUDY)
    assert s.answer(0)
    assert s.is_locked()
    assert not s.answer(1)
    assert s.state(0) is SlotState.WRONG
    assert s.state(1) is SlotState.BLANK
    s.submit()
    assert s.state(1) is SlotState.MISSED


def test_navigation_and_next_unanswered():
    s = exam_with(0, 30)  # all blank
    assert s.current == 0
    assert not s.prev()
    assert s.next() and s.current == 1
    assert s.goto(29) and not s.next()
    s.answer(0, 0)
    assert s.next_unanswered() == 1


def test_timer_counts_down_and_clamps_elapsed_on_timeout():
    clock = FakeClock()
    s = TestSession([question("a")], EXAM_RULES, Mode.EXAM, clock=clock)
    assert s.remaining() == 30 * 60
    clock.now += 600
    assert s.remaining() == 1200
    clock.now += 2000
    assert s.is_expired()
    result = s.submit(timed_out=True)
    assert result.timed_out and result.elapsed_s == 30 * 60
    clock.now += 50
    assert s.elapsed() == 30 * 60  # frozen after submit


def test_invalid_choice_rejected():
    s = TestSession([question("a")], EXAM_RULES, Mode.EXAM)
    assert not s.answer(3)
    assert not s.answer(-1)


def events(*items: tuple[str, bool]) -> list[AnswerEvent]:
    return [AnswerEvent(k, c, f"2026-01-01T00:00:{i:02d}") for i, (k, c) in enumerate(items)]


def test_question_stats_streaks_and_groups():
    ev = events(("a", False), ("a2", True), ("a", True), ("b", True))
    stats = question_stats(ev, {"a": "A", "a2": "A", "b": "B"})
    assert stats["A"].attempts == 3 and stats["A"].fails == 1 and stats["A"].streak == 2
    assert not stats["A"].in_review  # answered right after failing: cleared from review
    assert not stats["B"].in_review


def test_review_pool_clears_a_question_once_answered_right():
    pool = [question("a"), question("b"), question("c"), question("d")]
    ev = events(
        ("a", False), ("a", False),  # failed twice: pending
        ("b", False), ("b", True),  # failed, then right: cleared
        ("c", True),  # never failed
        ("d", False), ("d", True), ("d", False),  # failed again later: back in review
    )  # fmt: skip
    stats = question_stats(ev)
    assert [q.key for q in review_pool(pool, stats)] == ["a", "d"]
    assert review_weight(stats["a"]) == 3.0
    assert not stats["b"].mastered
    assert question_stats(events(*[("e", True)] * MASTERED_STREAK))["e"].mastered


def test_pick_review_prefers_heavier_weights():
    pool = [question("heavy"), question("light")]
    ev = events(*[("heavy", False)] * 6, ("light", False))
    stats = question_stats(ev)
    firsts = [pick_review(pool, 1, random.Random(seed), stats)[0].key for seed in range(300)]
    assert firsts.count("heavy") > firsts.count("light") * 2  # weights 7 vs 2


def test_pick_study_prefers_unseen_and_exam_is_seeded():
    pool = [question(f"q{i}") for i in range(10)]
    stats = question_stats(events(*[(f"q{i}", True) for i in range(8)]))
    picked = pick_study(pool, 2, random.Random(1), stats)
    assert {q.key for q in picked} == {"q8", "q9"}
    assert pick_exam(pool, 5, random.Random(42)) == pick_exam(pool, 5, random.Random(42))
    assert len(pick_exam(pool, 50, random.Random(1))) == 10


def test_pass_probability():
    assert pass_probability(1.0) == pytest.approx(1.0)
    assert pass_probability(0.0) == pytest.approx(0.0)
    assert pass_probability(0.9) == pytest.approx(0.6474, abs=1e-3)


def test_overview_numbers():
    pool = [question("a", topic="senales"), question("b", topic="velocidad")]
    ev = events(("a", True), ("a", False), ("b", True))
    exams = [
        ExamRecord("2026-01-01", 30, 28, 2, 0, True, 900.0),
        ExamRecord("2026-01-02", 30, 25, 4, 1, False, None),
    ]
    data = overview(
        ev, exams, pool, group_of={"a": "a", "b": "b"}, topic_of={"a": "senales", "b": "velocidad"}
    )
    assert data.exams == 2 and data.pass_rate == 0.5
    assert data.exam_errors == (2, 5)
    assert data.seen == 2 and data.review_pending == 1
    senales = next(t for t in data.topics if t.topic == "senales")
    assert senales.answered == 2 and senales.accuracy == 0.5
    assert data.pass_probability is None  # not enough answers yet
