"""«Preguntas guardadas»: questions saved with `g` from any test, and a read-only viewer."""

from datetime import datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from theoricum.engine.rules import Mode
from theoricum.models import Question
from theoricum.topics import topic_name
from theoricum.tui.widgets.question import QuestionView, source_label

SHORT_SOURCES = {"dgt": "DGT oficial", "revista-dgt": "Revista DGT", "ia": "IA"}


def _preview(text: str, width: int) -> str:
    line = " ".join(text.split())
    return line if len(line) <= width else line[: width - 1] + "…"


def _short_source(question: Question) -> str:
    return SHORT_SOURCES.get(question.origin) or question.source_name or source_label(question)


def _saved_on(value: str) -> str:
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%d/%m/%Y")
    except ValueError:
        return value[:10]


class SavedScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Volver"),
        Binding("e", "study", "Estudiarlas"),
        Binding("g", "remove", "Quitar"),
        Binding("delete", "remove", "Quitar", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.items: list[tuple[Question, str]] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False, icon="🚗")
        with Vertical(id="saved-body"):
            yield Static("", id="saved-title")
            yield DataTable(id="saved-table", cursor_type="row", zebra_stripes=True)
            yield Static(
                "Aún no has guardado ninguna pregunta.\n\n"
                "Durante cualquier test (examen, estudio, repaso o por tema) pulsa [b]g[/] para "
                "guardar la pregunta que estés viendo, y aparecerá aquí.",
                id="saved-empty",
            )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#saved-table", DataTable)
        table.add_columns("Pregunta", "Tema", "Fuente", "Guardada")
        self.load()

    def on_screen_resume(self) -> None:
        self.load()

    def load(self) -> None:
        table = self.query_one("#saved-table", DataTable)
        row = table.cursor_row
        self.items = self.app.practice.saved_questions()
        table.clear()
        # Leave room for the other columns so the table never needs horizontal scrolling.
        width = max(30, self.app.size.width - 70)
        for question, saved_at in self.items:
            table.add_row(
                _preview(question.text, width),
                topic_name(question.topic),
                _short_source(question),
                _saved_on(saved_at),
            )
        empty = not self.items
        table.display = not empty
        self.query_one("#saved-empty", Static).display = empty
        count = len(self.items)
        self.query_one("#saved-title", Static).update(
            f"[b]Preguntas guardadas[/] · {count} "
            + ("pregunta" if count == 1 else "preguntas")
            + "\n[dim]Enter para verla con la solución · e para estudiarlas todas · g para quitarla[/]"
        )
        if self.items:
            table.move_cursor(row=min(row, len(self.items) - 1))
            table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if 0 <= event.cursor_row < len(self.items):
            questions = [q for q, _ in self.items]
            self.app.push_screen(BrowseScreen(questions, event.cursor_row))

    def action_study(self) -> None:
        if not self.items:
            self.notify("No hay preguntas guardadas.", severity="warning")
            return
        self.app.start_test(Mode.SAVED, questions=[q for q, _ in self.items])

    def action_remove(self) -> None:
        table = self.query_one("#saved-table", DataTable)
        if not 0 <= table.cursor_row < len(self.items):
            return
        question = self.items[table.cursor_row][0]
        self.app.practice.store.set_saved(question.key, False)
        self.notify("Quitada de «Preguntas guardadas».", timeout=2)
        self.load()


class BrowseScreen(Screen[None]):
    """Read-only viewer: each question with its right answer and explanation."""

    BINDINGS = [
        Binding("left", "move(-1)", "Anterior", key_display="←", priority=True),
        Binding("right", "move(1)", "Siguiente", key_display="→", priority=True),
        Binding("g", "toggle_saved", "Guardar/Quitar"),
        Binding("escape", "app.pop_screen", "Volver"),
    ]

    def __init__(self, questions: list[Question], index: int = 0) -> None:
        super().__init__()
        self.questions = questions
        self.index = index

    def compose(self) -> ComposeResult:
        yield Static("Preguntas guardadas", id="browse-title")
        yield QuestionView(self.app.image_cls, self.app.images, id="question")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_view()

    def refresh_view(self) -> None:
        question = self.questions[self.index]
        self.query_one(QuestionView).show(
            question,
            index=self.index,
            total=len(self.questions),
            chosen=None,
            reveal=True,
            saved=self.app.practice.is_saved(question.key),
            browse=True,
        )

    def action_move(self, delta: int) -> None:
        index = self.index + delta
        if 0 <= index < len(self.questions):
            self.index = index
            self.refresh_view()

    def action_toggle_saved(self) -> None:
        saved = self.app.practice.toggle_saved(self.questions[self.index].key)
        self.notify(
            "Guardada en «Preguntas guardadas»." if saved else "Quitada de «Preguntas guardadas».",
            timeout=2,
        )
        self.refresh_view()
