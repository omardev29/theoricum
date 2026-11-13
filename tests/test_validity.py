import random

from theoricum.engine.pool import resolve_duplicates
from theoricum.engine.rules import Mode
from theoricum.library import sync
from theoricum.models import Question
from theoricum.practice import Practice
from theoricum.validity import load_changes, notices_for, parse_changes

from conftest import make_questions, write_pack


def q(key: str, text: str, options: tuple[str, ...], answer: int = 0, **kw) -> Question:
    defaults = {"topic": "otros", "origin": "otro", "dedup": key, "priority": 0}
    return Question(key=key, text=text, options=options, answer=answer, **{**defaults, **kw})


def test_the_bundled_changes_file_is_valid():
    ids = [change.id for change in load_changes()]
    assert len(ids) == len(set(ids)) and "v16" in ids


CHANGES = parse_changes(
    """
[[change]]
id = "v16"
since = "2026-01"
level = "warning"
keywords = ["triangulos"]
note = "V-16."

[[change]]
id = "urbana"
since = "2021-06"
level = "info"
topics = ["velocidad"]
keywords = ["urban*"]
also = ["50 km/h"]
note = "30 km/h."
"""
)


def test_notices_depend_on_date_topic_keywords_and_the_right_answer():
    old = q("a", "¿Cuántos triángulos debe llevar?", ("Dos", "Uno"), date="2019-12")
    assert [n.kind for n in notices_for(old, CHANGES)] == ["v16"]
    assert notices_for(q("b", old.text, old.options, date="2026-03"), CHANGES) == ()
    undated = q("c", old.text, old.options)
    assert [n.level for n in notices_for(undated, CHANGES)] == ["warning"]
    # A wrong option about an old rule is still wrong today: it does not count.
    wrong_option = q("d", "¿Qué hace si se avería?", ("Luces", "Poner los triángulos"), 0)
    assert notices_for(wrong_option, CHANGES) == ()

    urban = q("e", "En vías urbanas, ¿velocidad máxima?", ("50 km/h", "30"), date="2018-07")
    assert notices_for(urban, CHANGES) == ()  # topic is not «velocidad»
    urban = q("e", urban.text, urban.options, topic="velocidad", date="2018-07")
    assert [n.kind for n in notices_for(urban, CHANGES)] == ["urbana"]
    other = q("f", urban.text, ("40 km/h", "30"), topic="velocidad", date="2018-07")
    assert notices_for(other, CHANGES) == ()  # `also` is missing


def test_duplicates_that_disagree_keep_the_most_recent_with_a_note():
    old = q(
        "revista:t239", "¿Velocidad?", ("100 km/h", "90 km/h"), 0, dedup="g", priority=90,
        origin="revista-dgt", date="2017-02",
    )  # fmt: skip
    new = q("anki:x", "¿Velocidad?", ("90 km/h", "100 km/h"), 0, dedup="g", priority=50,
            origin="anki", date="2025-02", source_name="Anki · Carnet B")  # fmt: skip
    (winner,) = resolve_duplicates([old, new])
    assert winner.key == "anki:x"
    (note,) = winner.notices
    assert note.kind == "conflict" and "100 km/h" in note.text and "feb 2017" in note.text

    # When they agree, the most reliable source wins, as always.
    same = q(
        "anki:y", "¿Velocidad?", ("90 km/h.", "100"), 0, dedup="h", priority=50, date="2025-02"
    )
    official = q("dgt:z", "¿Velocidad?", ("90 km/h", "100"), 0, dedup="h", priority=100)
    (winner,) = resolve_duplicates([same, official])
    assert winner.key == "dgt:z" and winner.notices == ()


def test_outdated_questions_are_marked_and_left_out_of_exams(qdir, store):
    questions = [
        {
            "id": f"t{i}",
            "text": f"¿Pregunta {i} sobre los triángulos de preseñalización?",
            "options": ["Sí", "No"],
            "answer": "A",
            "date": "2020-01",
        }
        for i in range(5)
    ]
    questions += [
        {"id": f"n{i}", "text": f"¿Pregunta normal {i}?", "options": ["Sí", "No"], "answer": "B"}
        for i in range(5)
    ]
    write_pack(qdir / "p.json", questions, {"id": "p"})
    sync(store, qdir)
    practice = Practice(store, seed=1)
    outdated = {x.key for x in practice.pool if x.outdated}
    assert outdated == {f"p:t{i}" for i in range(5)}
    for seed in range(5):
        practice.rng = random.Random(seed)
        exam = practice.build(Mode.EXAM)
        assert exam is not None and not {x.key for x in exam.questions} & outdated
    study = practice.build(Mode.STUDY, n=10)
    assert study is not None and {x.key for x in study.questions} >= outdated  # still studied


def test_copies_that_depend_on_their_picture_are_different_questions():
    """«¿Qué indica esta señal?» with the same options but another answer is another sign."""
    options = ("Ceda el paso", "Stop", "Calzada con prioridad")
    a = q("anki:1", "¿Qué indica esta señal?", options, 0, dedup="g", image_ref="file:a.png")
    b = q("signals:R-2", "¿Qué indica esta señal?", options, 1, dedup="g", image_ref="file:b.png")
    c = q("revista:x", "¿Qué indica esta señal?", options, 0, dedup="g", priority=90,
          image_ref="file:c.png")  # fmt: skip
    kept = resolve_duplicates([a, b, c])
    assert [x.key for x in kept] == ["revista:x", "signals:R-2"]  # one per answer
    assert all(not x.notices for x in kept)


def test_practice_exams_carry_official_questions(qdir, store):
    write_pack(qdir / "otros.json", make_questions(100, "o"), {"id": "o", "origin": "revista-dgt"})
    write_pack(qdir / "dgt.json", make_questions(10, "d"), {"id": "d", "origin": "dgt"})
    sync(store, qdir)
    practice = Practice(store, seed=3)
    exam = practice.build(Mode.EXAM)
    assert exam is not None and sum(q.origin == "dgt" for q in exam.questions) >= 6
