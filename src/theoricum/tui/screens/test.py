"""The test screen (exam, study, review, topic) and its correction/review state."""

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Static

from theoricum.engine.rules import MODE_LABELS, Mode
from theoricum.engine.selection import MASTERED_STREAK
from theoricum.engine.session import SlotState, TestSession
from theoricum.topics import topic_name
from theoricum.tui.screens.dialogs import ConfirmScreen, HelpScreen
from theoricum.tui.widgets.clock import Clock, format_seconds
from theoricum.tui.widgets.grid import QuestionGrid
from theoricum.tui.widgets.question import OptionRow, QuestionView

TEST_HELP = """\
[b]a / b / c / d[/]   responder (también con el ratón)
[b]← / →[/]           pregunta anterior / siguiente (o clic en la rejilla)
[b]Enter[/]           examen: entregar · estudio: siguiente pregunta
[b]g[/]               guardar la pregunta en «Preguntas guardadas» (o quitarla)
[b]x[/]               desactivar la pregunta (cuando ya ves la respuesta)

«↻ repaso 1/3»: la fallaste antes; sale del repaso con 3 aciertos seguidos.
[b]r[/]               al corregir: repasar ahora las falladas
[b]Esc[/]             salir
"""


class TestScreen(Screen[None]):
    __test__ = False  # not a pytest test class

    BINDINGS = [
        Binding("a", "answer(0)", "Responder", key_display="a/b/c", priority=True),
        Binding("b", "answer(1)", "B", show=False, priority=True),
        Binding("c", "answer(2)", "C", show=False, priority=True),
        Binding("d", "answer(3)", "D", show=False, priority=True),
        Binding("left", "move(-1)", "Anterior", key_display="←", priority=True),
        Binding("right", "move(1)", "Siguiente", key_display="→", priority=True),
        Binding("enter", "submit", "Entregar", priority=True),
        Binding("enter", "advance", "Continuar", priority=True),
        Binding("enter", "close", "Volver al menú", priority=True),
        Binding("r", "retry_failed", "Repasar falladas"),
        Binding("g", "toggle_saved", "Guardar"),
        Binding("x", "toggle_disabled", "Desactivar"),
        Binding("escape", "leave", "Salir"),
        Binding("question_mark", "help", "Ayuda", key_display="?"),
    ]

    def __init__(self, session: TestSession, session_id: int) -> None:
        super().__init__()
        self.session = session
        self.session_id = session_id

    @property
    def is_exam(self) -> bool:
        return self.session.mode is Mode.EXAM

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield QuestionGrid(self._states(), self.session.current, id="grid")
            with Vertical(id="clock-box"):
                yield Static(self._mode_label(), id="mode-label")
                yield Clock("00:00", id="clock")
        yield Static("", id="summary")
        yield QuestionView(self.app.image_cls, self.app.images, id="question")
        yield Footer()

    def on_mount(self) -> None:
        # Review progress when the test starts, to tell when a question has just left the review.
        self._review_start = self.app.practice.review_progress(self.session.questions)
        self.query_one("#summary", Static).display = False
        self._tick()
        self.set_interval(1, self._tick)
        self.refresh_view()

    # --- rendering --------------------------------------------------------------------------

    def _mode_label(self) -> str:
        label = MODE_LABELS[self.session.mode]
        if self.session.topic:
            label += f": {topic_name(self.session.topic)}"
        return label

    def _states(self) -> list[SlotState]:
        return [self.session.state(i) for i in range(len(self.session))]

    def refresh_view(self) -> None:
        self.query_one(QuestionGrid).set_states(self._states(), self.session.current)
        key = self.session.question.key
        flag = self.app.practice.flags().get(key)
        self.query_one(QuestionView).show_session(
            self.session,
            saved=self.app.practice.is_saved(key),
            disabled=bool(flag and flag.disabled),
            review=self._review_label(),
        )
        self.refresh_bindings()

    def _review_label(self) -> str | None:
        """«↻ repaso 1/3» while a question is pending review; «✓ sale del repaso» when it leaves."""
        if self.is_exam and not self.session.finished:
            return None  # it would give away whether the answer was right
        question = self.session.question
        streak = self.app.practice.review_progress([question]).get(question.key)
        if streak is not None:
            return f"↻ repaso {streak}/{MASTERED_STREAK}"
        if question.key in self._review_start:
            return "✓ sale del repaso"
        return None

    def _tick(self) -> None:
        session = self.session
        self.query_one(Clock).show(remaining=session.remaining(), elapsed=session.elapsed())
        if not session.finished and session.is_expired():
            self.notify(
                "Se acabó el tiempo: el examen se entrega automáticamente.", severity="warning"
            )
            self.finish(timed_out=True)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        finished = self.session.finished
        if action in ("answer", "move"):
            return True if action == "move" else not finished
        if action == "submit":
            return self.is_exam and not finished
        if action == "advance":
            return not self.is_exam and not finished
        if action == "close":
            return finished
        if action == "retry_failed":
            return finished and any(
                s in (SlotState.WRONG, SlotState.MISSED) for s in self._states()
            )
        if action == "toggle_disabled":
            return self.session.reveals()
        return True

    # --- actions ----------------------------------------------------------------------------

    def action_answer(self, choice: int) -> None:
        session = self.session
        if session.is_locked():
            if session.rules.immediate_feedback and not session.finished:
                self.notify("Ya has respondido esta pregunta. Pulsa Enter para seguir.", timeout=2)
            return
        if not session.answer(choice):
            return
        self.app.practice.record(self.session_id, session, session.current)
        self.refresh_view()

    def action_move(self, delta: int) -> None:
        if self.session.goto(self.session.current + delta):
            self.refresh_view()

    def on_question_grid_selected(self, message: QuestionGrid.Selected) -> None:
        if self.session.goto(message.index):
            self.refresh_view()

    def on_option_row_chosen(self, message: OptionRow.Chosen) -> None:
        self.action_answer(message.index)

    def action_submit(self) -> None:
        blanks = self.session.n_unanswered
        message = "Se corregirá ahora y no podrás cambiar las respuestas."
        if blanks:
            message = f"Te quedan {blanks} sin responder, que cuentan como fallo. " + message

        def done(choice: str | None) -> None:
            if choice == "yes":
                self.finish()

        self.app.push_screen(
            ConfirmScreen(
                "¿Entregar el examen?",
                message,
                [("yes", "Entregar", "primary"), ("no", "Seguir", "default")],
            ),
            done,
        )

    def action_advance(self) -> None:
        session = self.session
        if session.answers[session.current] is None:
            self.notify("Responde con a, b o c (o pulsa → para saltarla).", timeout=2)
            return
        following = session.next_unanswered()
        if following is None:
            self.finish()
            return
        session.goto(following)
        self.refresh_view()

    def finish(self, *, timed_out: bool = False) -> None:
        session = self.session
        if session.finished:
            return
        session.submit(timed_out=timed_out)
        self.app.practice.finish(self.session_id, session)
        wrong = [
            i for i, s in enumerate(self._states()) if s in (SlotState.WRONG, SlotState.MISSED)
        ]
        session.goto(wrong[0] if wrong else 0)
        summary = self.query_one("#summary", Static)
        summary.update(self._summary_text())
        summary.display = True
        summary.set_class(session.result is not None and session.result.passed is True, "-pass")
        summary.set_class(session.result is not None and session.result.passed is False, "-fail")
        self.refresh_view()

    def _summary_text(self) -> Text:
        result = self.session.result
        assert result is not None
        grade = result.grade
        text = Text()
        elapsed = format_seconds(result.elapsed_s)
        if result.passed is not None:
            text.append("APTO ✓" if result.passed else "NO APTO ✗", style="bold")
            text.append(f"   {grade.errors} fallos (máximo {self.session.rules.max_errors})")
            text.append(f" · {grade.n_correct}/{result.n_questions} correctas")
            if grade.n_blank:
                text.append(f" · {grade.n_blank} sin responder")
        else:
            answered = grade.n_correct + grade.n_wrong
            pct = round(100 * grade.n_correct / answered) if answered else 0
            text.append(f"{grade.n_correct} de {answered} correctas ({pct} %)", style="bold")
            text.append(f" · {grade.n_wrong} falladas")
            if grade.n_blank:
                text.append(f" · {grade.n_blank} sin responder")
        text.append(f" · tiempo {elapsed}")
        if result.timed_out:
            text.append(" · tiempo agotado")
        text.append(
            "\nRevisa con ← → o la rejilla · r repasa las falladas · Enter vuelve al menú",
            style="dim",
        )
        return text

    def action_close(self) -> None:
        self.app.pop_screen()

    def action_leave(self) -> None:
        session = self.session
        if session.finished:
            self.app.pop_screen()
            return
        if not self.is_exam and session.n_answered == 0:
            # Nothing answered: leave without asking and without counting it as a session.
            self.app.practice.abandon(self.session_id, session)
            self.app.pop_screen()
            return
        if self.is_exam:
            title, message = (
                "¿Abandonar el examen?",
                "No contará como examen hecho, pero se guardan tus respuestas.",
            )
            buttons = [("abandon", "Abandonar", "error"), ("no", "Seguir", "default")]
        else:
            title, message = (
                "¿Terminar ahora?",
                "Se corrige lo que has respondido; lo demás no cuenta.",
            )
            buttons = [("finish", "Terminar", "primary"), ("no", "Seguir", "default")]

        def done(choice: str | None) -> None:
            if choice == "abandon":
                self.app.practice.abandon(self.session_id, session)
                self.app.pop_screen()
            elif choice == "finish":
                self.finish()

        self.app.push_screen(ConfirmScreen(title, message, buttons), done)

    def action_retry_failed(self) -> None:
        failed = [
            self.session.questions[i]
            for i, s in enumerate(self._states())
            if s in (SlotState.WRONG, SlotState.MISSED)
        ]
        if failed:
            self.app.start_test(Mode.STUDY, questions=failed, replace=True)

    def action_toggle_saved(self) -> None:
        saved = self.app.practice.toggle_saved(self.session.question.key)
        self.notify(
            "Guardada en «Preguntas guardadas»." if saved else "Quitada de «Preguntas guardadas».",
            timeout=2,
        )
        self.refresh_view()

    def action_toggle_disabled(self) -> None:
        question = self.session.question
        current = self.app.practice.flags().get(question.key)
        disabled = not (current and current.disabled)
        self.app.practice.set_disabled(question.key, disabled)
        self.notify(
            "Pregunta desactivada: no volverá a salir."
            if disabled
            else "Pregunta activada de nuevo.",
            timeout=3,
        )
        self.refresh_view()

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen("Ayuda del test", TEST_HELP))
