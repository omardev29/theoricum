"""Statistics: pass rate, evolution, weak topics and coverage."""

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Digits, Footer, Header, ProgressBar, Sparkline, Static

from theoricum.engine.stats import MIN_ANSWERS_FOR_ODDS, MIN_ANSWERS_PER_TOPIC
from theoricum.topics import topic_name

BAR_WIDTH = 20


def fmt_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def percent(value: float | None) -> str:
    return "--" if value is None else str(round(100 * value))


def bar(value: float | None) -> Text:
    if value is None:
        return Text("·" * BAR_WIDTH, style="dim")
    filled = round(value * BAR_WIDTH)
    color = "green" if value >= 0.9 else "yellow" if value >= 0.75 else "red"
    return Text("█" * filled, style=color) + Text("░" * (BAR_WIDTH - filled), style="dim")


class StatCard(Vertical):
    def __init__(self, label: str, value: str, note: str, **kwargs) -> None:
        super().__init__(classes="card", **kwargs)
        self.label, self.value, self.note = label, value, note

    def compose(self) -> ComposeResult:
        yield Static(self.label, classes="card-label")
        yield Digits(self.value, classes="card-value")
        yield Static(self.note, classes="card-note")


class StatsScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Volver"),
        Binding("q", "app.pop_screen", "Volver", show=False),
    ]

    def compose(self) -> ComposeResult:
        data = self.app.practice.overview()
        yield Header(show_clock=False, icon="🚗")
        with VerticalScroll(id="stats-body"):
            with Horizontal(id="cards"):
                yield StatCard(
                    "Exámenes aprobados",
                    f"{data.exams_passed}",
                    f"de {data.exams} hechos" if data.exams else "aún no hay exámenes",
                )
                yield StatCard("Tasa de aprobados", percent(data.pass_rate), "% de tus exámenes")
                yield StatCard(
                    "Acierto reciente",
                    percent(data.recent_accuracy),
                    f"% en tus últimas {fmt_int(data.recent_answers)} respuestas",
                )
                yield StatCard(
                    "Probabilidad de aprobar",
                    percent(data.pass_probability),
                    "% estimado (máx. 3 fallos de 30)"
                    if data.pass_probability is not None
                    else f"necesita {MIN_ANSWERS_FOR_ODDS} respuestas",
                )
            yield Static(
                "Evolución: fallos por examen (el límite para aprobar es 3)", classes="section"
            )
            errors = list(data.exam_errors[-40:])
            if len(errors) >= 2:
                yield Sparkline(errors, summary_function=max, id="evolution")
            if errors:
                last = ", ".join(str(e) for e in errors[-15:])
                yield Static(
                    f"Fallos en tus últimos exámenes (del más antiguo al más reciente): {last}",
                    classes="dim",
                )
            else:
                yield Static("Haz algún examen para ver tu evolución.", classes="dim")

            yield Static("Cobertura del banco", classes="section")
            coverage = ProgressBar(total=max(1, data.pool_size), show_eta=False, id="coverage")
            coverage.advance(data.seen)
            yield coverage
            yield Static(
                f"Vistas {fmt_int(data.seen)} de {fmt_int(data.pool_size)} · dominadas (3 aciertos seguidos) "
                f"{fmt_int(data.mastered)} · pendientes de repaso {fmt_int(data.review_pending)} · "
                f"respuestas totales {fmt_int(data.answers)}",
                classes="dim",
            )

            yield Static(
                f"Temas (los flojos primero; hacen falta {MIN_ANSWERS_PER_TOPIC} respuestas para valorarlos)",
                classes="section",
            )
            table = DataTable(id="topics", cursor_type="row", zebra_stripes=True)
            table.add_columns("Tema", "Preguntas", "Respondidas", "Acierto", "")
            ranked = sorted(
                data.topics,
                key=lambda t: (
                    t.answered < MIN_ANSWERS_PER_TOPIC,
                    t.accuracy if t.accuracy is not None else 2.0,
                    topic_name(t.topic),
                ),
            )
            for t in ranked:
                if not t.pool_size and not t.answered:
                    continue
                acc = None if t.answered < MIN_ANSWERS_PER_TOPIC else t.accuracy
                table.add_row(
                    topic_name(t.topic),
                    fmt_int(t.pool_size),
                    fmt_int(t.answered),
                    "—" if acc is None else f"{round(100 * acc)} %",
                    bar(acc),
                )
            yield table
        yield Footer()
