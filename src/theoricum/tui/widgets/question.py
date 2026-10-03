"""Question view: image on the left; statement, options and feedback on the right."""

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.events import Click
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from theoricum.engine.session import TestSession
from theoricum.models import LETTERS, MAX_OPTIONS, ORIGIN_LABELS, Question
from theoricum.topics import topic_name
from theoricum.tui.images import ImageCache

MONTHS_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def date_label(value: str | None) -> str | None:
    if not value:
        return None
    parts = value.split("-")
    if len(parts) >= 2 and parts[1].isdigit() and 1 <= int(parts[1]) <= 12:
        return f"{MONTHS_ES[int(parts[1]) - 1]} {parts[0]}"
    return parts[0]


def source_label(question: Question) -> str:
    label = ORIGIN_LABELS.get(question.origin, question.origin)
    if question.source_name and question.origin not in ("revista-dgt",):
        label = question.source_name
    return label


class OptionRow(Static):
    """One answer option. Not focusable, so the screen keys (a/b/c, Enter, arrows) always work."""

    class Chosen(Message):
        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    def __init__(self, index: int) -> None:
        super().__init__("", classes="option")
        self.index = index

    def on_click(self, event: Click) -> None:
        event.stop()
        self.post_message(self.Chosen(self.index))


class QuestionView(Horizontal):
    def __init__(self, image_cls: type[Widget], images: ImageCache, **kwargs) -> None:
        super().__init__(**kwargs)
        self.image_cls = image_cls
        self.images = images
        self._image_widget: Widget | None = None
        self._image_ref: str | None = None

    def compose(self) -> ComposeResult:
        with Container(id="image-pane"):
            yield Static("", id="image-missing")
        with VerticalScroll(id="qa-pane"):
            yield Static("", id="q-meta")
            yield Static("", id="q-text")
            with Vertical(id="q-options"):
                for index in range(MAX_OPTIONS):
                    yield OptionRow(index)
            yield Static("", id="q-feedback")

    def show(
        self,
        question: Question,
        *,
        index: int,
        total: int,
        chosen: int | None,
        reveal: bool,
        saved: bool = False,
        disabled: bool = False,
        browse: bool = False,
    ) -> None:
        """Render a question. `reveal` shows the right answer; `browse` is the read-only viewer."""
        meta = Text()
        meta.append(f"Pregunta {index + 1} de {total}", style="bold")
        details = [topic_name(question.topic), source_label(question)]
        if when := date_label(question.date):
            details.append(when)
        meta.append("  ·  " + "  ·  ".join(details), style="dim")
        if saved:
            meta.append("  ★ guardada", style="bold yellow")
        if disabled:
            meta.append("  ⊘ desactivada", style="bold red")
        self.query_one("#q-meta", Static).update(meta)
        self.query_one("#q-text", Static).update(Text(question.text))

        for row in self.query(OptionRow):
            if row.index >= len(question.options):
                row.display = False
                continue
            row.display = True
            row.update(
                Text.assemble((f"{LETTERS[row.index]}) ", "bold"), question.options[row.index])
            )
            row.set_class(chosen == row.index and not reveal, "-selected")
            row.set_class(reveal and row.index == question.answer, "-correct")
            row.set_class(reveal and chosen == row.index and row.index != question.answer, "-wrong")
            row.set_class(reveal and chosen != row.index and row.index != question.answer, "-dim")

        feedback = self.query_one("#q-feedback", Static)
        if reveal:
            feedback.update(self._feedback(question, chosen, browse))
            feedback.display = True
            ok = browse or chosen == question.answer
            feedback.set_class(ok, "-ok")
            feedback.set_class(not ok, "-ko")
        else:
            feedback.display = False
        self.query_one("#qa-pane", VerticalScroll).scroll_home(animate=False)
        self._show_image(question.image_ref)

    def show_session(
        self, session: TestSession, *, saved: bool = False, disabled: bool = False
    ) -> None:
        index = session.current
        self.show(
            session.question,
            index=index,
            total=len(session),
            chosen=session.answers[index],
            reveal=session.reveals(index),
            saved=saved,
            disabled=disabled,
        )

    def _feedback(self, question: Question, chosen: int | None, browse: bool) -> Text:
        text = Text()
        correct = LETTERS[question.answer]
        if browse:
            text.append(f"Respuesta correcta: {correct}", style="bold")
        elif chosen is None:
            text.append(f"Sin responder. La correcta es la {correct}.", style="bold")
        elif chosen == question.answer:
            text.append("✓ ¡Correcto!", style="bold")
        else:
            text.append(f"✗ Incorrecto. La correcta es la {correct}.", style="bold")
        if question.explanation:
            text.append("\n\n")
            text.append(question.explanation)
        if question.source:
            text.append(f"\n\nFuente: {question.source}", style="dim")
        return text

    def _show_image(self, ref: str | None) -> None:
        missing = self.query_one("#image-missing", Static)
        if ref is None:
            self.add_class("-no-image")
            return
        self.remove_class("-no-image")
        if ref == self._image_ref and self._image_widget is not None:
            return
        self._image_ref = ref
        image = self.images.get(ref)
        if image is None:
            missing.update("No se pudo cargar la imagen.")
            missing.display = True
            if self._image_widget is not None:
                self._image_widget.display = False
            return
        missing.display = False
        if self._image_widget is None:
            self._image_widget = self.image_cls(image, id="q-image")
            self.query_one("#image-pane", Container).mount(self._image_widget)
        else:
            self._image_widget.image = image  # type: ignore[attr-defined]
            self._image_widget.display = True
