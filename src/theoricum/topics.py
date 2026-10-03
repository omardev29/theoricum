"""Canonical topics and keyword-based topic classification."""

import re
import tomllib
import unicodedata
from dataclasses import dataclass
from functools import cache
from importlib import resources

FALLBACK_TOPIC = "otros"


def strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_text(value: str) -> str:
    """Lowercase and strip accents (ñ becomes n), for accent-insensitive matching."""
    return strip_accents(value).casefold()


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize_text(value)).strip("-")


@dataclass(frozen=True, slots=True)
class Topic:
    slug: str
    name: str
    aliases: tuple[str, ...]
    pattern: re.Pattern[str] | None


def _keyword_regex(keyword: str) -> str:
    keyword = normalize_text(keyword.strip())
    if keyword.endswith("*"):
        return r"\b" + re.escape(keyword[:-1]) + r"\w*"
    return r"\b" + re.escape(keyword) + r"(?!\w)"


@cache
def load_topics() -> tuple[Topic, ...]:
    raw = resources.files("theoricum.data").joinpath("topics.toml").read_text(encoding="utf-8")
    topics = []
    for entry in tomllib.loads(raw)["topic"]:
        keywords = sorted({normalize_text(k) for k in entry.get("keywords", [])})
        pattern = re.compile("|".join(_keyword_regex(k) for k in keywords)) if keywords else None
        aliases = tuple(slugify(a) for a in entry.get("aliases", []))
        topics.append(Topic(entry["slug"], entry["name"], aliases, pattern))
    return tuple(topics)


@cache
def _lookup() -> dict[str, str]:
    table: dict[str, str] = {}
    for topic in load_topics():
        for alias in (topic.slug, slugify(topic.name), *topic.aliases):
            table.setdefault(alias, topic.slug)
    return table


def known_topic(value: str) -> str | None:
    """Return the canonical slug for a slug, name or alias, or None if it is not a known topic."""
    return _lookup().get(slugify(value))


def resolve_topic(value: str) -> str:
    """Canonical slug for known topics; custom topics are kept as their slug."""
    return known_topic(value) or slugify(value) or FALLBACK_TOPIC


def topic_name(slug: str) -> str:
    for topic in load_topics():
        if topic.slug == slug:
            return topic.name
    return slug.replace("-", " ").capitalize()


def _score(pattern: re.Pattern[str], text: str) -> int:
    # Multi-word phrases are more specific than single words: each word of a match counts.
    return sum(1 + match.count(" ") for match in pattern.findall(text))


def classify(text: str, options: tuple[str, ...] | list[str] = ()) -> str:
    """Guess a topic from keywords; the statement weighs three times more than the options."""
    body = normalize_text(text)
    extra = normalize_text(" \n ".join(options))
    best, best_score = FALLBACK_TOPIC, 0
    for topic in load_topics():
        if topic.pattern is None:
            continue
        score = 3 * _score(topic.pattern, body) + _score(topic.pattern, extra)
        if score > best_score:
            best, best_score = topic.slug, score
    return best
