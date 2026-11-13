"""Choose the questions of each test. History is aggregated per duplicate group (`dedup`)."""

import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from theoricum.models import AnswerEvent, Question

MASTERED_STREAK = 3  # consecutive correct answers needed to leave the review pool
# Real exam questions (from the official DGT simulator): every exam and study session includes up
# to OFFICIAL_QUOTA of them that are not mastered yet, so they keep coming back until they are.
OFFICIAL_ORIGINS = frozenset({"dgt"})
OFFICIAL_QUOTA = 6


@dataclass(frozen=True, slots=True)
class QuestionStats:
    attempts: int
    fails: int
    streak: int  # consecutive correct answers since the last failure
    last_seen: str

    @property
    def in_review(self) -> bool:
        """Failed at some point and not yet answered right MASTERED_STREAK times in a row."""
        return self.fails > 0 and self.streak < MASTERED_STREAK

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


def review_weight(stats: QuestionStats | None) -> float:
    """More weight to questions failed often and not yet re-learned (1 if never seen)."""
    if stats is None:
        return 1.0
    return (1 + stats.fails) / (1 + stats.streak) ** 2


def weighted_sample(
    candidates: Sequence[Question], k: int, rng: random.Random, weight: Callable[[Question], float]
) -> list[Question]:
    """`k` questions without replacement, each with probability ∝ weight (Efraimidis–Spirakis)."""
    keys = {q.key: rng.random() ** (1 / weight(q)) for q in candidates}
    return sorted(candidates, key=lambda q: keys[q.key], reverse=True)[: max(0, k)]


def pick_official(
    pool: Sequence[Question], quota: int, rng: random.Random, stats: Mapping[str, QuestionStats]
) -> list[Question]:
    """Up to `quota` official questions not mastered yet: never seen ones and those failed most
    are the most likely."""
    candidates = [
        q
        for q in pool
        if q.origin in OFFICIAL_ORIGINS and not ((s := stats.get(q.dedup)) and s.mastered)
    ]
    return weighted_sample(candidates, quota, rng, lambda q: review_weight(stats.get(q.dedup)))


def filter_topic(pool: Sequence[Question], topic: str | None) -> list[Question]:
    return list(pool) if topic is None else [q for q in pool if q.topic == topic]


def _with_official(
    pool: Sequence[Question],
    n: int,
    rng: random.Random,
    stats: Mapping[str, QuestionStats] | None,
    quota: int,
) -> tuple[list[Question], list[Question]]:
    """(official questions picked for the quota, the rest of the pool)."""
    first = pick_official(pool, min(quota, n), rng, stats) if stats is not None and quota else []
    taken = {q.key for q in first}
    return first, [q for q in pool if q.key not in taken]


def pick_exam(
    pool: Sequence[Question],
    n: int,
    rng: random.Random,
    stats: Mapping[str, QuestionStats] | None = None,
    quota: int = 0,
) -> list[Question]:
    """Uniform random sample, like the real exam, plus up to `quota` official questions that are
    not mastered yet (see `pick_official`). Asked in random order."""
    first, rest = _with_official(pool, n, rng, stats, quota)
    picked = first + rng.sample(rest, min(n - len(first), len(rest)))
    rng.shuffle(picked)
    return picked


def pick_study(
    pool: Sequence[Question],
    n: int,
    rng: random.Random,
    stats: Mapping[str, QuestionStats],
    quota: int = 0,
) -> list[Question]:
    """Up to `quota` official questions not mastered yet; then never-seen questions, the most
    recent ones before the rest (they are the closest to the current exam); then the ones seen
    longest ago. The picked ones are asked in random order."""
    first, pool = _with_official(pool, n, rng, stats, quota)
    n -= len(first)
    unseen = [q for q in pool if q.dedup not in stats]
    rng.shuffle(unseen)  # random among questions of the same date
    unseen.sort(key=lambda q: q.date or "", reverse=True)  # undated ones last
    if len(unseen) >= n:
        picked = unseen[:n]
    else:
        seen = [q for q in pool if q.dedup in stats]
        rng.shuffle(seen)
        seen.sort(key=lambda q: stats[q.dedup].last_seen)
        picked = unseen + seen[: n - len(unseen)]
    picked = first + picked
    rng.shuffle(picked)
    return picked


def review_pool(pool: Sequence[Question], stats: Mapping[str, QuestionStats]) -> list[Question]:
    return [q for q in pool if (s := stats.get(q.dedup)) is not None and s.in_review]


def pick_review(
    pool: Sequence[Question], n: int, rng: random.Random, stats: Mapping[str, QuestionStats]
) -> list[Question]:
    """The pending ones, more likely the more they are failed (see `review_weight`)."""
    candidates = review_pool(pool, stats)
    return weighted_sample(candidates, n, rng, lambda q: review_weight(stats[q.dedup]))
