"""«Normativa»: the traffic law downloaded from the BOE (`dgt fetch laws`), with a search box."""

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, OptionList, Static
from textual.widgets.option_list import Option

from theoricum.laws import LawArticle, LawLibrary, load_laws
from theoricum.models import date_label


def article_text(article: LawArticle, query: str = "") -> Text:
    text = Text()
    text.append(f"{article.title}\n", style="bold")
    text.append(article.law, style="bold cyan")
    if article.section:
        text.append(f" · {article.section}", style="dim")
    when = date_label(article.in_force[:7]) if article.in_force else None
    if article.future:
        text.append(f"\nEntra en vigor el {article.in_force}.", style="bold dark_orange")
    elif when:
        text.append(f"\nTexto vigente desde el {article.in_force}.", style="dim")
    text.append("\n\n")
    body = Text(article.text)
    words = [w for w in query.split() if len(w) > 2]
    if words:
        body.highlight_words(words, style="reverse", case_sensitive=False)
    text.append_text(body)
    if article.notes:
        text.append(f"\n\n{article.notes}", style="dim italic")
    if article.law_url:
        text.append(f"\n\nFuente: BOE, {article.law_url}", style="dim")
    return text


class LawsScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Volver"),
        # Not a letter or ctrl+d: the search box uses them. Priority, so it works while typing.
        Binding("f5", "download", "Descargar o actualizar", priority=True),
    ]

    def __init__(self, query: str = "") -> None:
        super().__init__()
        self.initial_query = query
        self.library: LawLibrary | None = None
        self.results: list[LawArticle] = []

    def compose(self) -> ComposeResult:
        self.library = load_laws(self.app.paths.data_dir)
        yield Header(show_clock=False, icon="🚗")
        with Vertical(id="laws-body"):
            yield Input(
                value=self.initial_query,
                placeholder="Busca en la normativa: velocidad, alcohol, glorieta…",
                id="laws-search",
            )
            with Horizontal(id="laws-main"):
                yield OptionList(id="laws-results")
                with VerticalScroll(id="laws-article"):
                    yield Static("", id="laws-text")
            yield Static("", id="laws-status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#laws-search", Input).focus()
        self._search(self.initial_query)

    def _status(self) -> Text:
        if self.library is None:
            return Text.from_markup(
                "Aún no tienes la normativa. Pulsa [b]F5[/] para descargarla del BOE "
                "(unos 4 MB) o usa [b]dgt fetch laws[/]."
            )
        laws = " · ".join(f"{name} ({updated})" for name, updated, _ in self.library.laws)
        return Text(f"{len(self.results)} artículos · {laws}", style="dim")

    def _search(self, query: str) -> None:
        options = self.query_one("#laws-results", OptionList)
        options.clear_options()
        self.results = self.library.search(query) if self.library else []
        options.add_options(
            Option(Text.assemble((f"{a.title[:70]}\n", "bold"), (a.law, "dim")))
            for a in self.results
        )
        self.query_one("#laws-status", Static).update(self._status())
        self._show(0)

    def _show(self, index: int) -> None:
        static = self.query_one("#laws-text", Static)
        if not 0 <= index < len(self.results):
            static.update("" if self.library else "Sin normativa descargada.")
            return
        query = self.query_one("#laws-search", Input).value
        static.update(article_text(self.results[index], query))
        self.query_one("#laws-article", VerticalScroll).scroll_home(animate=False)

    def on_input_changed(self, event: Input.Changed) -> None:
        self._search(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self.results:
            self.query_one("#laws-results", OptionList).focus()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self._show(event.option_index)

    def action_download(self) -> None:
        self.notify("Descargando la normativa del BOE…", timeout=4)
        self._download()

    @work(thread=True, exclusive=True, group="laws", exit_on_error=False)
    def _download(self) -> None:
        from theoricum.fetchers.laws import fetch_laws

        try:
            fetch_laws(self.app.paths.data_dir, log=lambda _: None)
        except (ConnectionError, ValueError, OSError) as exc:
            self.app.call_from_thread(
                self.notify, f"No se pudo descargar la normativa: {exc}", severity="error"
            )
            return
        self.app.call_from_thread(self._downloaded)

    def _downloaded(self) -> None:
        self.library = load_laws(self.app.paths.data_dir)
        self.notify("Normativa descargada.", timeout=3)
        self._search(self.query_one("#laws-search", Input).value)
