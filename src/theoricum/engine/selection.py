"""Choose the questions of each test. History is aggregated per duplicate group (`dedup`)."""

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from theoricum.models import AnswerEvent, Question

MASTERED_STREAK = 3  # consecutive correct answers to count a question as mastered (stats)


@dataclass(frozen=True, slots=True)
class QuestionStats:
    attempts: int
    fails: int
    streak: int  # consecutive correct answers since the last failure
    last_seen: str

    @property
    def in_review(self) -> bool:
        """Pending review: the last attempt was a failure. Answering it right clears it."""
        return self.fails > 0 and self.streak == 0

    @property
    def mastered(self) -> bool:
        return self.streak >= MASTERED_STREAK


def question_stats(
    events: Sequence[AnswerEvent], group_of: Mapping[str, str] | None = None
) -> dict[str, QuestionStats]:
    """Aggregate chronological answer events per question group."""
    acc: dict[str, tuple[int, int, int, str]] = {}
    for event in events:
        group = group_of.get(event.key, event.key) if group_of else event.key
        attempts, fails, streak, _ = acc.get(group, (0, 0, 0, ""))
        if event.correct:
            streak += 1
        else:
            fails += 1
            streak = 0
        acc[group] = (attempts + 1, fails, streak, event.at)
    return {group: QuestionStats(*values) for group, values in acc.items()}


def review_weight(stats: QuestionStats) -> float:
    """More weight to the questions failed more often."""
    return float(1 + stats.fails)


def filter_topic(pool: Sequence[Question], topic: str | None) -> list[Question]:
    return list(pool) if topic is None else [q for q in pool if q.topic == topic]


def pick_exam(pool: Sequence[Question], n: int, rng: random.Random) -> list[Question]:
    """Uniform random sample, like the real exam."""
    return rng.sample(list(pool), min(n, len(pool)))


def pick_study(
    pool: Sequence[Question], n: int, rng: random.Random, stats: Mapping[str, QuestionStats]
) -> list[Question]:
    """Never-seen questions first, then the ones seen longest ago."""
    unseen = [q for q in pool if q.dedup not in stats]
    rng.shuffle(unseen)
    if len(unseen) >= n:
        return unseen[:n]
    seen = [q for q in pool if q.dedup in stats]
    rng.shuffle(seen)
    seen.sort(key=lambda q: stats[q.dedup].last_seen)
    picked = unseen + seen[: n - len(unseen)]
    rng.shuffle(picked)
    return picked


def review_pool(pool: Sequence[Question], stats: Mapping[str, QuestionStats]) -> list[Question]:
    return [q for q in pool if (s := stats.get(q.dedup)) is not None and s.in_review]


def pick_review(
    pool: Sequence[Question], n: int, rng: random.Random, stats: Mapping[str, QuestionStats]
) -> list[Question]:
    """Weighted sampling without replacement (Efraimidis–Spirakis)."""
    candidates = review_pool(pool, stats)
    keys = {q.key: rng.random() ** (1 / review_weight(stats[q.dedup])) for q in candidates}
    candidates.sort(key=lambda q: keys[q.key], reverse=True)
    return candidates[:n]
