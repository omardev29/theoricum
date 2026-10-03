from pathlib import Path

import pytest
from PIL import Image
from textual_image.widget import UnicodeImage

from theoricum.config import Paths
from theoricum.engine.session import SlotState
from theoricum.tui.app import StartRequest, TheoricumApp
from theoricum.tui.screens.dialogs import ConfirmScreen
from theoricum.tui.screens.menu import MenuScreen
from theoricum.tui.screens.test import TestScreen
from theoricum.tui.widgets.question import QuestionView

from conftest import make_questions, write_pack

SIZE = (130, 45)


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    qdir = tmp_path / "questions"
    (qdir / "p" / "img").mkdir(parents=True)
    Image.new("RGB", (40, 30), "red").save(qdir / "p" / "img" / "red.png")
    questions = make_questions(40)
    for q in questions[:5]:
        q["image"] = "img/red.png"
    write_pack(qdir / "p" / "pack.json", questions, {"id": "p", "name": "Pack de prueba"})
    return Paths(questions_dir=qdir, data_dir=tmp_path / "data")


def make_app(paths: Paths, command: str = "menu", **kw) -> TheoricumApp:
    return TheoricumApp(
        paths=paths, start=StartRequest(command=command, **kw), image_cls=UnicodeImage, seed=1
    )


async def wait_sync(app: TheoricumApp, pilot) -> None:
    await pilot.pause()
    for _ in range(100):
        if not app.syncing:
            break
        await pilot.pause(0.05)
    await pilot.pause(0.1)


async def test_menu_shows_bank_and_opens_exam(paths: Paths):
    app = make_app(paths)
    async with app.run_test(size=SIZE) as pilot:
        await wait_sync(app, pilot)
        assert isinstance(app.screen, MenuScreen)
        assert len(app.practice.pool) == 40
        await pilot.press("1")
        await pilot.pause()
        assert isinstance(app.screen, TestScreen)
        assert len(app.screen.session) == 30


async def test_exam_answer_navigate_submit_and_review(paths: Paths):
    app = make_app(paths, "exam")
    async with app.run_test(size=SIZE) as pilot:
        await wait_sync(app, pilot)
        screen = app.screen
        assert isinstance(screen, TestScreen)
        session = screen.session
        await pilot.press("b")
        assert session.answers[0] == 1
        await pilot.press("a")  # can change before submitting
        assert session.answers[0] == 0
        assert session.state(0) is SlotState.ANSWERED
        await pilot.press("right", "c")
        assert session.current == 1 and session.answers[1] == 2
        await pilot.press("left")
        assert session.current == 0

        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("enter")  # "Entregar" has the focus
        await pilot.pause()
        assert app.screen is screen and session.finished
        assert session.result.passed is False  # 28 blanks
        assert app.store.exam_records()[-1].n_blank == 28

        await pilot.press("r")  # retry the failed ones in study mode
        await pilot.pause()
        retry = app.screen
        assert isinstance(retry, TestScreen) and retry is not screen
        assert retry.session.mode.value == "study" and len(retry.session) >= 28
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)


async def test_study_mode_feedback_and_finish(paths: Paths):
    app = make_app(paths, "study", n=3)
    async with app.run_test(size=SIZE) as pilot:
        await wait_sync(app, pilot)
        screen = app.screen
        assert isinstance(screen, TestScreen) and len(screen.session) == 3
        for _ in range(3):
            q = screen.session.question
            await pilot.press("abc"[q.answer])
            assert screen.session.state(screen.session.current) is SlotState.CORRECT
            feedback = screen.query_one("#q-feedback")
            assert feedback.display
            await pilot.press("enter")
        await pilot.pause()
        assert screen.session.finished
        assert screen.session.result.grade.n_correct == 3


async def test_exam_times_out(paths: Paths):
    app = make_app(paths, "exam")
    async with app.run_test(size=SIZE) as pilot:
        await wait_sync(app, pilot)
        screen = app.screen
        assert isinstance(screen, TestScreen)
        screen.session._started -= 31 * 60  # pretend 31 minutes went by
        screen._tick()
        await pilot.pause()
        assert screen.session.finished and screen.session.result.timed_out


async def test_question_with_image_mounts_image_widget(paths: Paths):
    app = make_app(paths, "study", n=40)
    async with app.run_test(size=SIZE) as pilot:
        await wait_sync(app, pilot)
        screen = app.screen
        view = screen.query_one(QuestionView)
        with_image = next(i for i, q in enumerate(screen.session.questions) if q.image_ref)
        screen.session.goto(with_image)
        screen.refresh_view()
        await pilot.pause()
        assert not view.has_class("-no-image")
        assert view.query(UnicodeImage)
        without = next(i for i, q in enumerate(screen.session.questions) if not q.image_ref)
        screen.session.goto(without)
        screen.refresh_view()
        await pilot.pause()
        assert view.has_class("-no-image")


async def test_topic_and_stats_and_library_screens(paths: Paths):
    app = make_app(paths)
    async with app.run_test(size=SIZE) as pilot:
        await wait_sync(app, pilot)
        await pilot.press("5")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "StatsScreen"
        await pilot.press("escape")
        await pilot.press("6")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "LibraryScreen"
        await pilot.press("escape")
        await pilot.press("4")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "TopicPicker"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, TestScreen) and app.screen.session.topic is not None


async def test_review_mode_with_no_failures_notifies(paths: Paths):
    app = make_app(paths, "review")
    async with app.run_test(size=SIZE) as pilot:
        await wait_sync(app, pilot)
        assert isinstance(app.screen, MenuScreen)
