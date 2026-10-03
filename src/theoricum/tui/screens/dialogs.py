"""Modal dialogs. Their background is transparent on purpose: a translucent tint would alter the
foreground colors that encode kitty TGP image ids, garbling the image underneath."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, Static
from textual.widgets.option_list import Option


class ConfirmScreen(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancelar")]

    def __init__(self, title: str, message: str, buttons: list[tuple[str, str, str]]) -> None:
        super().__init__()
        self.title_text = title
        self.message = message
        self.buttons = buttons

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(self.title_text, classes="dialog-title")
            yield Static(self.message, classes="dialog-body")
            with Horizontal(classes="dialog-buttons"):
                for button_id, label, variant in self.buttons:
                    yield Button(label, id=button_id, variant=variant)  # type: ignore[arg-type]

    def on_mount(self) -> None:
        self.query(Button).first().focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "close", "Cerrar"),
        Binding("enter", "close", "Cerrar", show=False),
        Binding("question_mark", "close", "Cerrar", show=False),
    ]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self.title_text = title
        self.body = body

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(self.title_text, classes="dialog-title")
            yield Static(self.body, classes="dialog-body")
            yield Static("Esc para cerrar", classes="dialog-hint")

    def action_close(self) -> None:
        self.dismiss(None)


class TopicPicker(ModalScreen[str | None]):
    """Choose a topic for the «Por tema» mode."""

    BINDINGS = [Binding("escape", "cancel", "Cancelar")]

    def __init__(self, topics: list[tuple[str, str]]) -> None:
        super().__init__()
        self.topics = topics  # (slug, label)

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog dialog-tall"):
            yield Static("Elige un tema", classes="dialog-title")
            yield OptionList(
                *[Option(label, id=slug) for slug, label in self.topics], id="topic-list"
            )
            yield Static("↑↓ elegir · Enter empezar · Esc cancelar", classes="dialog-hint")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)
