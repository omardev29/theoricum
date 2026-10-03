"""Library: the sources found in questions/, their counts, warnings and errors."""

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from theoricum.models import ORIGIN_LABELS


def fmt_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


class LibraryScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Volver"),
        Binding("r", "reload", "Recargar"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False, icon="🚗")
        with Vertical(id="library-body"):
            yield Static(f"Carpeta: {self.app.paths.questions_dir}", classes="dim")
            yield DataTable(id="sources", cursor_type="row", zebra_stripes=True)
            with VerticalScroll(id="detail-scroll"):
                yield Static("", id="source-detail")
        yield Footer()

    def on_mount(self) -> None:
        self.load()

    def load(self) -> None:
        self.sources = self.app.practice.store.sources()
        table = self.query_one("#sources", DataTable)
        table.clear(columns=True)
        table.add_columns("Archivo", "Nombre", "Origen", "Prioridad", "Preguntas", "Estado")
        for s in self.sources:
            if s.error:
                state = Text("✗ error", style="bold red")
            elif s.warnings:
                state = Text(f"⚠ {len(s.warnings)} avisos", style="yellow")
            else:
                state = Text("✓", style="green")
            if not s.enabled:
                state = Text("desactivada", style="dim")
            table.add_row(
                s.path,
                s.name or "",
                ORIGIN_LABELS.get(s.origin, s.origin),
                str(s.priority),
                fmt_int(s.n_questions),
                state,
            )
        detail = self.query_one("#source-detail", Static)
        if not self.sources:
            detail.update(
                "No hay fuentes. Deja packs JSON/TOML, mazos .apkg o carpetas CrowdAnki en la carpeta."
            )
        else:
            self.show_detail(0)

    def show_detail(self, index: int) -> None:
        if not 0 <= index < len(self.sources):
            return
        s = self.sources[index]
        text = Text()
        text.append(f"{s.path}\n", style="bold")
        if s.error:
            text.append(f"Error: {s.error}\n", style="red")
        if not s.warnings and not s.error:
            text.append("Sin avisos.\n", style="dim")
        for warning in s.warnings[:200]:
            text.append(f"· {warning}\n")
        if len(s.warnings) > 200:
            text.append(f"… y {len(s.warnings) - 200} avisos más (ver `dgt check`)\n", style="dim")
        self.query_one("#source-detail", Static).update(text)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.show_detail(event.cursor_row)

    def action_reload(self) -> None:
        self.app.run_sync(announce=True, on_done=self.load)
