"""«Manual»: the DGT manual by topics (opened in the system PDF viewer) and the sheet of changes
made after it (data/changes.toml)."""

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList, Static
from textual.widgets.option_list import Option

from theoricum.manual import Manual, load_manual
from theoricum.models import date_label
from theoricum.validity import novelties

FULL = "full"


def novelties_text(manual: Manual | None) -> Text:
    """The sheet of changes, marking those that came after the manual."""
    text = Text()
    text.append("Novedades de la norma\n", style="bold underline")
    since = manual.date if manual else "2023-12"
    text.append(
        f"Lo que ha cambiado desde el manual ({date_label(since)}) y desde las preguntas más "
        "antiguas. Las preguntas afectadas lo avisan al corregirlas.\n",
        style="dim",
    )
    for change in novelties():
        text.append("\n")
        text.append(change.title, style="bold")
        text.append(f"  · desde {date_label(change.since)}", style="dim")
        if change.since > since:
            text.append("  · posterior al manual", style="bold dark_orange")
        text.append(f"\n{change.summary}\n")
        if manual and change.manual:
            chapters = [c for n in change.manual if (c := manual.chapter(n))]
            if chapters:
                names = ", ".join(f"{c.number}. {c.title}" for c in chapters)
                text.append(f"En el manual: {names}\n", style="dim")
    return text


class ManualScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Volver"),
        Binding("d", "download", "Descargar el manual"),
    ]

    def compose(self) -> ComposeResult:
        manual = load_manual(self.app.paths.data_dir)
        yield Header(show_clock=False, icon="🚗")
        with Horizontal(id="manual-body"):
            with Vertical(id="manual-left"):
                if manual is None:
                    yield Static(
                        "Aún no tienes el manual del permiso B de la DGT.\n\n"
                        "Pulsa [b]d[/] para descargarlo (17 MB) o usa [b]dgt fetch manual[/].",
                        id="manual-missing",
                    )
                else:
                    yield Static(
                        f"[b]{manual.title}[/]\n[dim]Enter abre el tema en tu visor de PDF[/]",
                        id="manual-title",
                    )
                    yield OptionList(
                        Option("Manual completo", id=FULL),
                        *[
                            Option(f"{c.number:>2}. {c.title}  [dim]pág. {c.first_page}[/]",
                                   id=str(c.number))
                            for c in manual.chapters
                        ],
                        id="chapters",
                    )  # fmt: skip
            with VerticalScroll(id="novelties"):
                yield Static(novelties_text(manual), id="novelties-text")
        yield Footer()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "download":
            return load_manual(self.app.paths.data_dir) is None
        return True

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        manual = load_manual(self.app.paths.data_dir)
        if manual is None or event.option.id is None:
            return
        if event.option.id == FULL:
            self.app.open_in_viewer(manual.full, "el manual completo")
        elif chapter := manual.chapter(int(event.option.id)):
            self.app.open_in_viewer(manual.path(chapter), f"el tema {chapter.number}")

    def action_download(self) -> None:
        self.notify("Descargando el manual de la DGT…", timeout=4)
        self._download()

    @work(thread=True, exclusive=True, group="manual", exit_on_error=False)
    def _download(self) -> None:
        from theoricum.fetchers.manual import fetch_manual

        try:
            fetch_manual(self.app.paths.data_dir, log=lambda _: None)
        except (ConnectionError, ValueError, OSError) as exc:
            self.app.call_from_thread(
                self.notify, f"No se pudo descargar el manual: {exc}", severity="error"
            )
            return
        self.app.call_from_thread(self._downloaded)

    def _downloaded(self) -> None:
        self.notify("Manual descargado.", timeout=3)
        self.refresh(recompose=True)
        self.refresh_bindings()
