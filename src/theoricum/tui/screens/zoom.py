"""Full-screen view of a question image (key `z`): every cell of the terminal goes to the image.

It is a plain Screen, not a ModalScreen: a translucent modal background would tint the kitty
(TGP) image underneath. In an exam the countdown keeps running and is shown at the top.
"""

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Static

from theoricum.engine.session import TestSession
from theoricum.models import Question
from theoricum.tui.widgets.clock import format_seconds


class ImageZoomScreen(Screen[None]):
    BINDINGS = [
        Binding("z", "close", "Volver"),
        Binding("escape", "close", "Volver", show=False),
        Binding("enter", "close", "Volver", show=False),
    ]

    def __init__(
        self, question: Question, title: str, *, session: TestSession | None = None
    ) -> None:
        super().__init__()
        self.question = question
        self.title_text = title
        self.session = session

    def compose(self) -> ComposeResult:
        yield Static("", id="zoom-title")
        with Container(id="zoom-pane"):
            image = (
                self.app.images.get(self.question.image_ref) if self.question.image_ref else None
            )
            if image is None:
                yield Static("No se pudo cargar la imagen.", id="zoom-missing")
            else:
                yield self.app.image_cls(image, id="zoom-image")
        yield Footer()

    def on_mount(self) -> None:
        self._tick()
        if self.session is not None and self.session.remaining() is not None:
            self.set_interval(1, self._tick)

    def _tick(self) -> None:
        title = Text(no_wrap=True, overflow="ellipsis")
        session = self.session
        remaining = session.remaining() if session is not None else None
        if session is not None and remaining is not None and not session.finished:
            title.append(f"⏱ {format_seconds(remaining, round_up=True)}  ", style="bold")
        title.append(self.title_text, style="bold")
        title.append(f"  ·  {' '.join(self.question.text.split())}", style="dim")
        self.query_one("#zoom-title", Static).update(title)

    def action_close(self) -> None:
        self.app.pop_screen()
