"""The 1–N question grid at the top of the test screen."""

from math import ceil

from rich.text import Text
from textual.events import Click
from textual.geometry import Size
from textual.message import Message
from textual.widget import Widget

from theoricum.engine.session import SlotState

CELL_WIDTH = 5  # " 12• " plus a gap
MAX_PER_ROW = 15
SYMBOLS = {
    SlotState.BLANK: " ",
    SlotState.ANSWERED: "•",
    SlotState.CORRECT: "✓",
    SlotState.WRONG: "✗",
    SlotState.MISSED: "·",
}


class QuestionGrid(Widget):
    """Clickable grid; each cell is colored by its state (and marked with a symbol)."""

    COMPONENT_CLASSES = {
        "grid--blank",
        "grid--answered",
        "grid--correct",
        "grid--wrong",
        "grid--missed",
        "grid--current",
    }

    class Selected(Message):
        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    def __init__(self, states: list[SlotState], current: int = 0, **kwargs) -> None:
        super().__init__(**kwargs)
        self.states = states
        self.current = current

    def set_states(self, states: list[SlotState], current: int) -> None:
        self.states = states
        self.current = current
        self.refresh()

    def _per_row(self, width: int) -> int:
        return max(1, min(len(self.states), MAX_PER_ROW, (width + 1) // CELL_WIDTH))

    def get_content_width(self, container: Size, viewport: Size) -> int:
        return self._per_row(container.width) * CELL_WIDTH - 1

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return ceil(len(self.states) / self._per_row(width))

    def render(self) -> Text:
        per_row = self._per_row(self.size.width)
        text = Text(no_wrap=True, overflow="crop")
        for index, state in enumerate(self.states):
            if index and index % per_row == 0:
                text.append("\n")
            elif index:
                text.append(" ")
            style = self.get_component_rich_style(f"grid--{state.value}")
            if index == self.current:
                style += self.get_component_rich_style("grid--current")
            text.append(f"{index + 1:>2}{SYMBOLS[state]} ", style)
        return text

    def on_click(self, event: Click) -> None:
        offset = event.get_content_offset(self)
        if offset is None:
            return
        per_row = self._per_row(self.size.width)
        column = offset.x // CELL_WIDTH
        if column >= per_row or offset.x % CELL_WIDTH == CELL_WIDTH - 1:
            return
        index = offset.y * per_row + column
        if 0 <= index < len(self.states):
            self.post_message(self.Selected(index))
