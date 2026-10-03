import json
from pathlib import Path

import pytest

from theoricum.db.store import Store
from theoricum.models import Question


@pytest.fixture
def qdir(tmp_path: Path) -> Path:
    path = tmp_path / "questions"
    path.mkdir()
    return path


@pytest.fixture
def store():
    s = Store.open(":memory:")
    yield s
    s.close()


def write_pack(path: Path, questions: list[dict], pack: dict | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"format": "theoricum/1", "pack": pack or {}, "questions": questions}
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def make_questions(n: int, prefix: str = "q", topic: str | None = None) -> list[dict]:
    return [
        {
            "id": f"{prefix}{i}",
            "text": f"Pregunta número {i} de {prefix}",
            "options": [f"Uno {i}", f"Dos {i}", f"Tres {i}"],
            "answer": "ABC"[i % 3],
            **({"topic": topic} if topic else {}),
        }
        for i in range(n)
    ]


def question(
    key: str, answer: int = 0, topic: str = "otros", dedup: str | None = None, **kw
) -> Question:
    return Question(
        key=key,
        text=f"¿{key}?",
        options=("A", "B", "C"),
        answer=answer,
        topic=topic,
        origin="otro",
        dedup=dedup or key,
        **kw,
    )
