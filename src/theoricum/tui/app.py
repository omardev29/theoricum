"""The Textual application. Importing this module makes textual-image probe the terminal, so it is
imported only when the TUI is about to run (never from export/import/check/fetch)."""

from collections.abc import Callable
from dataclasses import dataclass

from textual import work
from textual.app import App
from textual.widget import Widget
from textual_image.widget import HalfcellImage, SixelImage, TGPImage, UnicodeImage
from textual_image.widget import Image as AutoImage

from theoricum.config import Paths
from theoricum.db.store import Store
from theoricum.engine.rules import Mode, rules_for
from theoricum.engine.session import TestSession
from theoricum.library import SyncReport, sync
from theoricum.media import MediaResolver
from theoricum.models import Question
from theoricum.practice import Practice
from theoricum.topics import cli_name
from theoricum.tui.images import ImageCache, describe_images, install_quality_hooks
from theoricum.tui.screens.menu import MenuScreen
from theoricum.tui.screens.test import TestScreen

install_quality_hooks()

IMAGE_CLASSES: dict[str, type[Widget]] = {
    "auto": AutoImage,
    "tgp": TGPImage,
    "sixel": SixelImage,
    "halfcell": HalfcellImage,
    "unicode": UnicodeImage,
}

EMPTY_MESSAGES = {
    Mode.REVIEW: "No tienes fallos pendientes de repaso. ¡Bien hecho!",
    Mode.TOPIC: "No hay preguntas de ese tema.",
}


@dataclass(frozen=True, slots=True)
class StartRequest:
    command: str = "menu"  # menu | exam | study | review | stats | saved | laws
    topic: str | None = None
    n: int | None = None
    query: str = ""  # laws: what to search


def describe_sync(report: SyncReport) -> str:
    parts = []
    if report.added:
        parts.append(f"{len(report.added)} fuentes nuevas")
    if report.updated:
        parts.append(f"{len(report.updated)} actualizadas")
    if report.removed:
        parts.append(f"{len(report.removed)} eliminadas")
    if report.errors:
        parts.append(f"{len(report.errors)} con errores")
    return "Preguntas: " + (", ".join(parts) if parts else "sin cambios") + "."


class TheoricumApp(App[None]):
    CSS_PATH = "app.tcss"
    TITLE = "theoricum"
    SUB_TITLE = "Teórico DGT · permiso B"
    ENABLE_COMMAND_PALETTE = False
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (110, "-wide")]

    def __init__(
        self,
        *,
        paths: Paths,
        start: StartRequest | None = None,
        image_cls: type[Widget] = AutoImage,
        since: str | None = None,
        seed: int | None = None,
    ) -> None:
        super().__init__()
        self.paths = paths
        self.image_cls = image_cls
        self.store = Store.open(paths.db_path)
        self.practice = Practice(self.store, since=since, seed=seed)
        self.media = MediaResolver(paths.question_dirs)
        self.images = ImageCache(self.media)
        self.syncing = False
        self.sync_progress = ""
        self.last_sync: SyncReport | None = None
        self._pending_start = start if start is not None and start.command != "menu" else None
        self._sync_callbacks: list[Callable[[], None]] = []
        self._announce_sync = False

    def on_mount(self) -> None:
        self.store.abandon_stale_sessions()
        self.push_screen(MenuScreen())
        self.run_sync()

    def on_unmount(self) -> None:
        self.media.close()
        self.store.close()

    # --- synchronization of questions/ (in a worker thread with its own connection) -----------

    def run_sync(
        self,
        *,
        force: bool = False,
        announce: bool = False,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        if on_done is not None:
            self._sync_callbacks.append(on_done)
        self._announce_sync = self._announce_sync or announce
        if self.syncing:
            return
        self.syncing = True
        self.sync_progress = ""
        self._refresh_menu()
        self._sync_worker(force)

    @work(thread=True, exclusive=True, group="sync", exit_on_error=False)
    def _sync_worker(self, force: bool) -> None:
        report: SyncReport | None = None
        error: Exception | None = None
        store = Store.open(self.paths.db_path)
        try:
            report = sync(
                store,
                self.paths.question_dirs,
                force=force,
                progress=lambda done, total, rel: self.call_from_thread(
                    self._sync_step, done, total, rel
                ),
            )
        except Exception as exc:  # Surface it in the UI instead of crashing the app.
            error = exc
        finally:
            store.close()
        self.call_from_thread(self._sync_finished, report, error)

    def _sync_step(self, done: int, total: int, rel: str) -> None:
        self.sync_progress = f"{done + 1}/{total} · {rel}" if rel else ""
        self._refresh_menu()

    def _sync_finished(self, report: SyncReport | None, error: Exception | None) -> None:
        self.syncing = False
        self.sync_progress = ""
        self.last_sync = report
        self.practice.invalidate()
        if error is not None:
            self.notify(f"Error al cargar las preguntas: {error}", severity="error", timeout=10)
        elif report is not None and (self._announce_sync or report.changed):
            severity = "warning" if report.errors else "information"
            self.notify(describe_sync(report), severity=severity)
        self._announce_sync = False
        self._refresh_menu()
        callbacks, self._sync_callbacks = self._sync_callbacks, []
        for callback in callbacks:
            callback()
        if self._pending_start is not None:
            start, self._pending_start = self._pending_start, None
            self.launch(start)

    def open_in_viewer(self, path, what: str) -> None:
        """Open a PDF in the system viewer; a failure becomes a notification with the path."""
        from theoricum.manual import open_document

        try:
            open_document(path)
        except OSError as exc:
            self.notify(f"No he podido abrir {what} ({exc}). Está en {path}", severity="error")
            return
        self.notify(f"Abriendo {what} en tu visor de PDF.", timeout=3)

    def open_manual_for(self, question: Question) -> None:
        """The topic of the DGT manual that explains a question (or the whole manual)."""
        from theoricum.manual import load_manual

        manual = load_manual(self.paths.data_dir)
        if manual is None:
            self.notify(
                "Aún no tienes el manual: descárgalo desde Manual en el menú o con "
                "`dgt fetch manual`.",
                severity="warning",
                timeout=6,
            )
            return
        chapter = manual.for_topic(question.topic)
        if chapter is None:
            self.open_in_viewer(manual.full, "el manual completo")
        else:
            self.open_in_viewer(manual.path(chapter), f"el tema {chapter.number}: {chapter.title}")

    def open_laws_for(self, question: Question | None = None, query: str = "") -> None:
        from theoricum.laws import TOPIC_QUERIES
        from theoricum.tui.screens.laws import LawsScreen

        if question is not None:
            query = TOPIC_QUERIES.get(question.topic, "")
        self.push_screen(LawsScreen(query))

    def image_summary(self) -> str:
        return describe_images(self.image_cls)

    def zoom_image(
        self, question: Question, title: str, session: TestSession | None = None
    ) -> None:
        from theoricum.tui.screens.zoom import ImageZoomScreen

        if question.image_ref:
            self.push_screen(ImageZoomScreen(question, title, session=session))

    def _refresh_menu(self) -> None:
        for screen in self.screen_stack:
            if isinstance(screen, MenuScreen) and screen.is_mounted:
                screen.refresh_info()

    # --- starting things ----------------------------------------------------------------------

    def launch(self, start: StartRequest) -> None:
        """Jump straight to a mode (from the command line)."""
        match start.command:
            case "exam":
                self.start_test(Mode.EXAM)
            case "review":
                self.start_test(Mode.REVIEW, n=start.n)
            case "study" if start.topic:
                topic = start.topic  # the internal slug (the CLI translates the English name)
                if not any(q.topic == topic for q in self.practice.pool):
                    self.notify(
                        f"No hay preguntas del tema «{cli_name(topic)}». Mira los disponibles con "
                        "`dgt topics`.",
                        severity="error",
                        timeout=8,
                    )
                    return
                self.start_test(Mode.TOPIC, topic=topic, n=start.n)
            case "study":
                self.start_test(Mode.STUDY, n=start.n)
            case "stats":
                from theoricum.tui.screens.stats import StatsScreen

                self.push_screen(StatsScreen())
            case "saved":
                from theoricum.tui.screens.saved import SavedScreen

                self.push_screen(SavedScreen())
            case "laws":
                self.open_laws_for(query=start.query)

    def start_test(
        self,
        mode: Mode,
        *,
        topic: str | None = None,
        n: int | None = None,
        questions: list[Question] | None = None,
        replace: bool = False,
    ) -> bool:
        if questions is not None:
            session = TestSession(questions, rules_for(mode, len(questions)), mode, topic=topic)
        else:
            session = self.practice.build(mode, topic=topic, n=n)
        if session is None:
            message = EMPTY_MESSAGES.get(
                mode, "No hay preguntas. Revisa la Biblioteca o la carpeta questions/."
            )
            self.notify(message, severity="warning")
            return False
        if mode is Mode.EXAM and len(session) < session.rules.n_questions:
            self.notify(
                f"Solo hay {len(session)} preguntas disponibles: el examen tendrá menos de "
                f"{session.rules.n_questions}.",
                severity="warning",
            )
        session_id = self.practice.start(session)
        screen = TestScreen(session, session_id)
        if replace:
            self.switch_screen(screen)
        else:
            self.push_screen(screen)
        return True


def run_app(
    *,
    paths: Paths,
    start: StartRequest,
    image_protocol: str = "auto",
    since: str | None = None,
    seed: int | None = None,
) -> int:
    app = TheoricumApp(
        paths=paths, start=start, image_cls=IMAGE_CLASSES[image_protocol], since=since, seed=seed
    )
    app.run()
    return app.return_code or 0
