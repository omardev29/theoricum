"""Control panel: modes, bank status and a summary of progress."""

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList, Static
from textual.widgets.option_list import Option

from theoricum.engine.rules import Mode
from theoricum.tui.screens.dialogs import HelpScreen, TopicPicker

LOGO = """\
 ▀█▀ █ █ █▀▀ █▀█ █▀█ █ █▀▀ █ █ █▀▄▀█
  █  █▀█ ██▄ █▄█ █▀▄ █ █▄▄ █▄█ █ ▀ █"""

MENU_HELP = """\
[b]↑ / ↓[/] y [b]Enter[/]   elegir modo (o su número)
[b]r[/]               recargar la carpeta questions/
[b]q[/]               salir

[b]Examen[/]: 30 preguntas, 30 minutos y máximo 3 fallos; se corrige al final.
[b]Estudio[/]: corrige cada respuesta al momento y prioriza las que no has visto.
[b]Repaso de fallos[/]: solo las falladas, con más peso a las que fallas más.
  Una pregunta sale del repaso tras 3 aciertos seguidos.
[b]Por tema[/]: estudio de un solo tema.

Para añadir preguntas, déjalas en la carpeta questions/ (JSON/TOML, .apkg o
CrowdAnki) o descarga la revista con [b]dgt fetch revista-dgt[/].
"""

ITEMS = [
    ("exam", "1", "Examen", "30 preguntas · 30 min · máx. 3 fallos"),
    ("study", "2", "Estudio", "corrección al momento"),
    ("review", "3", "Repaso de fallos", ""),
    ("topic", "4", "Por tema", "señales, velocidad, alcohol…"),
    ("stats", "5", "Estadísticas", "aprobados, temas flojos, evolución"),
    ("library", "6", "Biblioteca", "fuentes de preguntas y avisos"),
    ("quit", "q", "Salir", ""),
]


def fmt_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def pct(value: float | None) -> str:
    return "—" if value is None else f"{round(100 * value)} %"


class MenuScreen(Screen[None]):
    BINDINGS = [
        *[
            Binding(key, f"open('{item}')", label, show=False)
            for item, key, label, _ in ITEMS
            if key != "q"
        ],
        Binding("r", "reload", "Recargar preguntas"),
        Binding("q", "app.quit", "Salir"),
        Binding("question_mark", "help", "Ayuda", key_display="?"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False, icon="🚗")
        with Horizontal(id="menu-body"):
            with Vertical(id="menu-left"):
                yield Static(LOGO, id="logo")
                yield Static("Práctica del examen teórico · permiso B", id="tagline")
                yield OptionList(
                    *[Option(self._prompt(item), id=item[0]) for item in ITEMS], id="menu"
                )
            yield Static("", id="bank-info")
        yield Footer()

    def _prompt(self, item: tuple[str, str, str, str], extra: str | None = None) -> Text:
        _, key, label, hint = item
        text = Text.assemble((f" {key}  ", "bold"), (label, "bold"))
        hint = extra if extra is not None else hint
        if hint:
            text.append(f"   {hint}", style="dim")
        return text

    def on_mount(self) -> None:
        self.query_one("#menu", OptionList).focus()
        self.refresh_info()

    def on_screen_resume(self) -> None:
        self.app.practice.invalidate()
        self.refresh_info()
        self.app.run_sync()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.action_open(event.option.id)

    def action_open(self, item: str) -> None:
        app = self.app
        if app.syncing and item in ("exam", "study", "review", "topic"):
            self.notify("Espera un momento: estoy cargando las preguntas.", timeout=2)
            return
        match item:
            case "exam":
                app.start_test(Mode.EXAM)
            case "study":
                app.start_test(Mode.STUDY)
            case "review":
                app.start_test(Mode.REVIEW)
            case "topic":
                topics = app.practice.topics()
                if not topics:
                    self.notify("No hay preguntas todavía.", severity="warning")
                    return
                labels = [
                    (
                        t.slug,
                        f"{t.name}  ·  {fmt_int(t.count)} preguntas  ·  acierto {pct(t.accuracy)}",
                    )
                    for t in topics
                ]

                def chosen(slug: str | None) -> None:
                    if slug:
                        app.start_test(Mode.TOPIC, topic=slug)

                app.push_screen(TopicPicker(labels), chosen)
            case "stats":
                from theoricum.tui.screens.stats import StatsScreen

                app.push_screen(StatsScreen())
            case "library":
                from theoricum.tui.screens.library import LibraryScreen

                app.push_screen(LibraryScreen())
            case "quit":
                app.exit()

    def action_reload(self) -> None:
        self.app.run_sync(force=False, announce=True)

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen("Ayuda", MENU_HELP))

    def refresh_info(self) -> None:
        app = self.app
        info = Text()
        if app.syncing:
            info.append("Cargando preguntas…\n", style="bold")
            if app.sync_progress:
                info.append(app.sync_progress + "\n", style="dim")
            self.query_one("#bank-info", Static).update(info)
            return

        practice = app.practice
        pool = practice.pool
        sources = practice.store.sources()
        warnings = sum(len(s.warnings) for s in sources)
        errors = sum(1 for s in sources if s.error)

        info.append("Banco de preguntas\n", style="bold underline")
        if not pool:
            info.append("No hay preguntas todavía.\n\n", style="bold")
            info.append("Déjalas en la carpeta:\n", style="dim")
            info.append(f"{app.paths.questions_dir}\n\n")
            info.append("o descarga los tests de la revista de la DGT con\n", style="dim")
            info.append("dgt fetch revista-dgt\n", style="bold")
        else:
            with_image = sum(1 for q in pool if q.image_ref)
            info.append(f"{fmt_int(len(pool))} preguntas", style="bold")
            info.append(f" · {fmt_int(with_image)} con imagen · {len(sources)} fuentes\n")
        if errors:
            info.append(f"✗ {errors} fuentes con errores (abre la Biblioteca)\n", style="bold red")
        if warnings:
            info.append(
                f"⚠ {fmt_int(warnings)} avisos de importación (Biblioteca)\n", style="yellow"
            )

        if pool:
            data = practice.overview()
            review = data.review_pending
            menu = self.query_one("#menu", OptionList)
            menu.replace_option_prompt(
                "review",
                self._prompt(ITEMS[2], f"{review} pendientes" if review else "nada pendiente"),
            )
            info.append("\nTu progreso\n", style="bold underline")
            if data.exams:
                last = practice.store.exam_records()[-1]
                verdict = "APTO" if last.passed else "NO APTO"
                info.append(
                    f"Exámenes: {data.exams} · aprobados {data.exams_passed} ({pct(data.pass_rate)})\n"
                )
                info.append("Último: ")
                info.append(verdict, style="bold green" if last.passed else "bold red")
                info.append(f" con {last.n_wrong + last.n_blank} fallos\n")
            else:
                info.append("Aún no has hecho ningún examen.\n")
            info.append(f"Acierto reciente: {pct(data.recent_accuracy)}\n")
            info.append(f"Probabilidad de aprobar: {pct(data.pass_probability)}\n")
            info.append(f"Preguntas vistas: {fmt_int(data.seen)} de {fmt_int(data.pool_size)}\n")
        info.append(f"\n{app.paths.questions_dir}", style="dim")
        self.query_one("#bank-info", Static).update(info)
