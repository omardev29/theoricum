"""Statistics for the stats screen: pass rate, evolution, weak topics, coverage, pass odds."""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import comb

from theoricum.engine.rules import EXAM_RULES
from theoricum.engine.selection import question_stats, review_pool
from theoricum.models import AnswerEvent, ExamRecord, Question

RECENT_ANSWERS = 300
MIN_ANSWERS_FOR_ODDS = 60
MIN_ANSWERS_PER_TOPIC = 10


@dataclass(frozen=True, slots=True)
class TopicStat:
    topic: str
    pool_size: int
    answered: int
    correct: int

    @property
    def accuracy(self) -> float | None:
        return self.correct / self.answered if self.answered else None


@dataclass(frozen=True, slots=True)
class Overview:
    exams: int
    exams_passed: int
    exam_errors: tuple[int, ...]
    answers: int
    recent_answers: int
    recent_accuracy: float | None
    pass_probability: float | None
    topics: tuple[TopicStat, ...]
    pool_size: int
    seen: int
    review_pending: int
    mastered: int

    @property
    def pass_rate(self) -> float | None:
        return self.exams_passed / self.exams if self.exams else None

    @property
    def weak_topics(self) -> list[TopicStat]:
        ranked = [t for t in self.topics if t.answered >= MIN_ANSWERS_PER_TOPIC]
        return sorted(ranked, key=lambda t: t.accuracy or 0.0)


def pass_probability(
    accuracy: float,
    n_questions: int = EXAM_RULES.n_questions,
    max_errors: int = EXAM_RULES.max_errors or 0,
) -> float:
    """P(errors <= max_errors) if each answer is correct independently with `accuracy`."""
    miss = 1.0 - accuracy
    return sum(
        comb(n_questions, k) * miss**k * accuracy ** (n_questions - k)
        for k in range(max_errors + 1)
    )


def overview(
    events: Sequence[AnswerEvent],
    exams: Sequence[ExamRecord],
    pool: Sequence[Question],
    *,
    group_of: Mapping[str, str],
    topic_of: Mapping[str, str],
) -> Overview:
    stats = question_stats(events, group_of)
    recent = events[-RECENT_ANSWERS:]
    recent_accuracy = sum(e.correct for e in recent) / len(recent) if recent else None
    odds = (
        pass_probability(recent_accuracy)
        if recent_accuracy is not None and len(recent) >= MIN_ANSWERS_FOR_ODDS
        else None
    )

    pool_by_topic = Counter(q.topic for q in pool)
    answered: Counter[str] = Counter()
    correct: Counter[str] = Counter()
    for event in events:
        topic = topic_of.get(event.key, "otros")
        answered[topic] += 1
        correct[topic] += event.correct
    topics = tuple(
        TopicStat(topic, pool_by_topic.get(topic, 0), answered[topic], correct[topic])
        for topic in sorted(set(pool_by_topic) | set(answered))
    )

    groups = {q.dedup for q in pool}
    return Overview(
        exams=len(exams),
        exams_passed=sum(1 for e in exams if e.passed),
        exam_errors=tuple(e.n_wrong + e.n_blank for e in exams),
        answers=len(events),
        recent_answers=len(recent),
        recent_accuracy=recent_accuracy,
        pass_probability=odds,
        topics=topics,
        pool_size=len(pool),
        seen=sum(1 for g in groups if g in stats),
        review_pending=len(review_pool(pool, stats)),
        mastered=sum(1 for g in groups if (s := stats.get(g)) is not None and s.mastered),
    )
