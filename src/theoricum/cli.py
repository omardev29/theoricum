"""Command line entry point (`dgt`). Commands and flags in English, messages in Spanish."""

import argparse
import contextlib
import os
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from theoricum import __version__
from theoricum.config import NoQuestionsFolder, Paths, resolve_paths

IMAGE_PROTOCOLS = ("auto", "tgp", "sixel", "halfcell", "unicode")
FETCH_SOURCES = ("revista-dgt", "dgt-web", "signals", "anki", "manual", "laws")
# Study material, not questions: it goes to the data folder.
DATA_SOURCES = ("manual", "laws")
# File that tells where each source lives, to update it in the folder that already has it.
FETCH_MARKERS = {
    "revista-dgt": "revista-dgt/pack.json",
    "dgt-web": "dgt-web/pack.json",
    "signals": "signals/pack.json",
    "anki": "anki/Carnet.B.apkg",
}

_ARGPARSE_ES = {
    "usage: ": "uso: ",
    "positional arguments": "argumentos",
    "options": "opciones",
    "show this help message and exit": "muestra esta ayuda y sale",
    "show program's version number and exit": "muestra la versión y sale",
    "argument %(argument_name)s: %(message)s": "argumento %(argument_name)s: %(message)s",
    "unrecognized arguments: %s": "argumentos no reconocidos: %s",
    "the following arguments are required: %s": "faltan estos argumentos: %s",
    "expected one argument": "se esperaba un valor",
    "invalid %(type)s value: %(value)r": "valor %(type)s no válido: %(value)r",
    "invalid choice: %(value)r (choose from %(choices)s)": "opción no válida: %(value)r (elige entre %(choices)s)",
    "invalid choice: %(value)r, maybe you meant %(closest)r? (choose from %(choices)s)": (
        "opción no válida: %(value)r, ¿querías decir %(closest)r? (elige entre %(choices)s)"
    ),
    "ambiguous option: %(option)s could match %(matches)s": "opción ambigua: %(option)s puede ser %(matches)s",
    "not allowed with argument %s": "no se permite junto con el argumento %s",
    "%(prog)s: error: %(message)s\n": "%(prog)s: error: %(message)s\n",
}


def _spanish_argparse() -> None:
    """argparse's own strings go through gettext; translate the visible ones."""
    argparse._ = lambda message: _ARGPARSE_ES.get(message, message)  # type: ignore[attr-defined]


def fmt_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def build_parser() -> argparse.ArgumentParser:
    _spanish_argparse()
    common = argparse.ArgumentParser(add_help=False)
    group = common.add_argument_group("opciones globales")
    group.add_argument(
        "--questions-dir",
        metavar="DIR",
        default=argparse.SUPPRESS,
        help="usa solo esta carpeta de preguntas (o $THEORICUM_QUESTIONS); por defecto se usan "
        "./questions y ~/Questions",
    )
    group.add_argument(
        "--no-local",
        action="store_true",
        default=argparse.SUPPRESS,
        help="no usar la carpeta questions/ del directorio actual",
    )
    group.add_argument(
        "--no-global",
        action="store_true",
        default=argparse.SUPPRESS,
        help="no usar la carpeta global ~/Questions",
    )
    group.add_argument(
        "--data-dir",
        metavar="DIR",
        default=argparse.SUPPRESS,
        help="carpeta del progreso (por defecto la de datos del usuario o $THEORICUM_DATA)",
    )
    group.add_argument(
        "--image-protocol",
        choices=IMAGE_PROTOCOLS,
        default=argparse.SUPPRESS,
        help="cómo dibujar las imágenes (por defecto auto o $THEORICUM_IMAGE_PROTOCOL: "
        "kitty usa TGP y Windows Terminal, Sixel)",
    )
    group.add_argument(
        "--since",
        metavar="AAAA[-MM]",
        default=argparse.SUPPRESS,
        help="usar solo preguntas con fecha igual o posterior (las que no tienen fecha se usan)",
    )
    group.add_argument(
        "--seed",
        type=int,
        metavar="N",
        default=argparse.SUPPRESS,
        help="semilla para repetir una selección",
    )

    parser = argparse.ArgumentParser(
        prog="dgt",
        description="Practica el examen teórico de la DGT (permiso B) en la terminal.",
        epilog="Sin comando abre el panel de control. Las preguntas se leen de ./questions (en el "
        "directorio actual) y de ~/Questions; si un archivo está en las dos, se usa el de "
        "./questions. Los nombres de las carpetas dan igual en mayúsculas o minúsculas.",
        parents=[common],
    )
    parser.add_argument("--version", action="version", version=f"theoricum {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMANDO", title="comandos")

    sub.add_parser(
        "exam", parents=[common], help="examen: 30 preguntas, 30 minutos, máximo 3 fallos"
    )
    study = sub.add_parser(
        "study", parents=[common], help="estudio: corrige cada respuesta al momento"
    )
    study.add_argument(
        "--topic",
        metavar="TEMA",
        help="solo preguntas de este tema, con su nombre en inglés: signals, speed… "
        "(ver `dgt topics`)",
    )
    study.add_argument("-n", type=int, metavar="N", default=30, help="número de preguntas (30)")
    review = sub.add_parser(
        "review", parents=[common], help="repaso de fallos, con más peso a los frecuentes"
    )
    review.add_argument("-n", type=int, metavar="N", default=30, help="número de preguntas (30)")
    sub.add_parser(
        "topics", parents=[common], help="lista los temas y cuántas preguntas tiene cada uno"
    )
    sub.add_parser("stats", parents=[common], help="abre las estadísticas")
    sub.add_parser("saved", parents=[common], help="abre tus preguntas guardadas")
    manual = sub.add_parser(
        "manual",
        parents=[common],
        help="abre el manual del permiso B de la DGT (entero o un tema) en tu visor de PDF",
    )
    manual.add_argument(
        "chapter",
        nargs="?",
        metavar="TEMA",
        help="número de tema (1-17), un tema de theoricum en inglés (signals, speed…; ver "
        "`dgt topics`) o «points» para el carnet por puntos",
    )
    laws = sub.add_parser(
        "laws", parents=[common], help="abre la normativa de tráfico del BOE, con buscador"
    )
    laws.add_argument("query", nargs="*", metavar="BÚSQUEDA", help="palabras que buscar")
    sub.add_parser(
        "check", parents=[common], help="sincroniza y valida las preguntas sin abrir la interfaz"
    )

    into_help = (
        "carpeta donde guardar (por defecto ./questions si existe y si no ~/Questions; "
        "si ya lo tienes, se actualiza donde esté)"
    )
    fetch = sub.add_parser("fetch", parents=[common], help="descarga preguntas")
    fetch.add_argument(
        "source",
        choices=FETCH_SOURCES,
        help="revista-dgt: tests de la revista de la DGT · dgt-web: simulador oficial · "
        "signals: catálogo oficial de señales (BOE) · anki: mazo de la comunidad «Carnet B» · "
        "manual: manual del permiso B de la DGT · laws: normativa de tráfico del BOE",
    )
    fetch.add_argument("--into", metavar="DIR", help=into_help)
    fetch.add_argument("--refresh", action="store_true", help="vuelve a descargarlo todo")
    fetch.add_argument(
        "--last",
        type=int,
        metavar="N",
        help="revista-dgt: solo los N tests más recientes (por defecto, todos, del más nuevo al más antiguo)",
    )

    export = sub.add_parser(
        "export", parents=[common], help="crea un .zip con tus preguntas y tu historial"
    )
    export.add_argument(
        "-o",
        "--output",
        metavar="ARCHIVO",
        help="ruta del .zip (por defecto theoricum-AAAA-MM-DD.zip)",
    )
    export.add_argument("--no-history", action="store_true", help="exporta solo las preguntas")

    imp = sub.add_parser(
        "import", parents=[common], help="restaura un .zip creado con `dgt export`"
    )
    imp.add_argument("file", metavar="ARCHIVO", help="el .zip exportado")
    imp.add_argument(
        "--into",
        metavar="DIR",
        help="carpeta donde dejar las preguntas nuevas (por defecto ./questions si existe y si "
        "no ~/Questions)",
    )
    imp.add_argument(
        "--overwrite", action="store_true", help="sobrescribe archivos de preguntas distintos"
    )
    return parser


def _paths(args: argparse.Namespace) -> Paths:
    return resolve_paths(
        getattr(args, "questions_dir", None),
        getattr(args, "data_dir", None),
        use_local=not getattr(args, "no_local", False),
        use_global=not getattr(args, "no_global", False),
    )


def _print_folders(paths: Paths, shadowed: list[tuple[str, Path]] | None = None) -> None:
    print("Carpetas de preguntas (si un archivo está en varias, se usa la primera):")
    for folder in paths.folders:
        state = "" if folder.path.is_dir() else " (aún no existe)"
        print(f"  · {folder.path} — {folder.label}{state}")
    if legacy := paths.legacy_folder():
        print(
            f"  Consejo: tus preguntas están en la carpeta antigua {legacy.path}. "
            f"Muévelas a {Path.home() / 'Questions'} cuando quieras: el historial no cambia."
        )
    if shadowed:
        many = len(shadowed) > 1
        print(
            f"  {len(shadowed)} archivo{'s' if many else ''} de una carpeta posterior "
            f"{'se ignoran' if many else 'se ignora'} porque {'están' if many else 'está'} "
            "también en una anterior:"
        )
        for rel, folder in shadowed[:5]:
            print(f"      - {rel} (en {folder})")


def _open_synced_store(paths: Paths, *, verbose: bool):
    from theoricum.db.store import Store
    from theoricum.library import sync

    store = Store.open(paths.db_path)

    def progress(done: int, total: int, rel: str) -> None:
        if verbose and rel:
            print(f"  importando {rel} ({done + 1}/{total})…", file=sys.stderr)

    report = sync(store, paths.question_dirs, progress=progress)
    return store, report


def cmd_check(args: argparse.Namespace) -> int:
    from theoricum.models import ORIGIN_LABELS
    from theoricum.topics import topic_name

    paths = _paths(args)
    if not any(d.is_dir() for d in paths.question_dirs):
        _print_folders(paths)
        print(f"Base de datos: {paths.db_path}")
        print(
            "\nNo existe ninguna carpeta de preguntas. Crea ~/Questions (o questions/ en este "
            "directorio) y deja ahí tus packs, o descarga preguntas con `dgt fetch`."
        )
        return 1
    store, report = _open_synced_store(paths, verbose=True)
    _print_folders(paths, report.shadowed)
    print(f"Base de datos: {paths.db_path}")
    sources = store.sources()
    print(f"\nFuentes ({len(sources)}):")
    if not sources:
        print("  (ninguna) Deja packs JSON/TOML, mazos .apkg o carpetas CrowdAnki en la carpeta.")
    for s in sources:
        if s.error:
            print(f"  ✗ {s.path}: {s.error}")
            continue
        label = ORIGIN_LABELS.get(s.origin, s.origin)
        extra = f", {len(s.warnings)} avisos" if s.warnings else ""
        state = "" if s.enabled else " [desactivada]"
        print(
            f"  ✓ {s.path} — {s.name or s.path} ({label}, prioridad {s.priority}){state}: "
            f"{fmt_int(s.n_questions)} preguntas{extra}"
        )
        for warning in s.warnings[:20]:
            print(f"      · {warning}")
        if len(s.warnings) > 20:
            print(f"      · … y {len(s.warnings) - 20} avisos más")
    if report.ignored:
        print("\nIgnorados (formato desconocido):")
        for rel in report.ignored:
            print(f"  · {rel}")
    pool = store.load_questions(since=getattr(args, "since", None))
    topics = Counter(q.topic for q in pool)
    with_image = sum(1 for q in pool if q.image_ref)
    print(
        f"\nBanco activo: {fmt_int(len(pool))} preguntas ({fmt_int(with_image)} con imagen) "
        f"en {len(topics)} temas, sin duplicados ni desactivadas."
    )
    for slug, count in topics.most_common():
        print(f"  {topic_name(slug):<40} {fmt_int(count):>6}")
    _print_notices(pool)
    store.close()
    return 1 if any(s.error for s in sources) else 0


def _print_notices(pool) -> None:
    """Summary of the questions with notices (see data/changes.toml and engine/pool.py)."""
    kinds: Counter[str] = Counter()
    outdated = 0
    for question in pool:
        outdated += question.outdated
        kinds.update(notice.kind for notice in question.notices)
    if not kinds:
        return
    print("\nAvisos de vigencia (se ven al corregir cada pregunta):")
    if outdated:
        print(f"  ⚠ {fmt_int(outdated)} posibles anticuadas: se marcan y no salen en el examen.")
    for kind, count in sorted(kinds.items()):
        label = (
            "respuesta distinta en otra fuente (gana la más reciente)"
            if kind == "conflict"
            else kind
        )
        print(f"  · {label}: {fmt_int(count)}")


def cmd_topics(args: argparse.Namespace) -> int:
    from theoricum.topics import cli_name, topic_name

    store, _ = _open_synced_store(_paths(args), verbose=False)
    topics = Counter(q.topic for q in store.load_questions(since=getattr(args, "since", None)))
    store.close()
    if not topics:
        print("No hay preguntas. Ejecuta `dgt check` para ver qué pasa con tus carpetas.")
        return 1
    print(f"{'--topic':<18} {'TEMA':<40} {'PREGUNTAS':>9}")
    for slug, count in sorted(topics.items(), key=lambda item: topic_name(item[0])):
        print(f"{cli_name(slug):<18} {topic_name(slug):<40} {fmt_int(count):>9}")
    print("\nPor ejemplo: dgt study --topic signals · dgt manual signals")
    return 0


def _fetch_target(args: argparse.Namespace, paths: Paths) -> Path:
    """`--into`, or the folder that already has this source, or the folder for new files."""
    if args.into:
        return Path(args.into).expanduser().resolve()
    return paths.home_of(FETCH_MARKERS[args.source]) or paths.questions_dir


def _fetch_revista(args: argparse.Namespace, target: Path) -> int:
    from theoricum.fetchers.revista_dgt import fetch_revista

    report = fetch_revista(
        target, refresh=args.refresh, last=args.last, log=lambda m: print(m, flush=True)
    )
    print(
        f"\nListo: {len(report.tests_fetched)} tests nuevos, {fmt_int(report.questions_added)} "
        f"preguntas nuevas, {fmt_int(report.total_questions)} en total."
    )
    if report.tests_missing:
        print(f"Tests que no existen en la web: {', '.join(map(str, report.tests_missing))}")
    if report.images_failed:
        print(f"Imágenes que no se pudieron descargar: {report.images_failed}")
    for warning in report.warnings:
        print(f"  · {warning}")
    print("Recuerda: las imágenes de la revista son solo para uso personal; no las compartas.")
    return 0


def _fetch_dgt_web(args: argparse.Namespace, target: Path) -> int:
    from theoricum.fetchers.dgt_web import SimulatorError, fetch_dgt_web

    try:
        report = fetch_dgt_web(target, refresh=args.refresh, log=lambda m: print(m, flush=True))
    except SimulatorError as exc:
        print(f"No se pudo usar el simulador de la DGT: {exc}", file=sys.stderr)
        return 1
    print(
        f"\nListo: {report.sessions} sesiones, {report.new_questions} preguntas nuevas, "
        f"{report.total_questions} en total."
    )
    if report.images_failed:
        print(f"Imágenes que no se pudieron descargar: {report.images_failed}")
    print("Son preguntas oficiales de la DGT: úsalas solo para tu estudio personal.")
    return 0


def _fetch_signals(args: argparse.Namespace, target: Path) -> int:
    from theoricum.fetchers.signals import fetch_signals

    report = fetch_signals(target, refresh=args.refresh, log=lambda m: print(m, flush=True))
    if report.already:
        print(
            f"Ya tienes las {fmt_int(report.questions)} preguntas de señales del catálogo "
            f"oficial en {report.pack_path}. Usa --refresh para volver a generarlas."
        )
        if report.meta_updated:
            print("He actualizado los datos del pack (nombre, fecha y prioridad).")
        return 0
    print(
        f"\nListo: {fmt_int(report.signs)} señales en el catálogo, "
        f"{fmt_int(report.questions)} preguntas en {report.pack_path}."
    )
    if report.skipped:
        print(f"Omitidas ({len(report.skipped)}):")
        for line in report.skipped[:30]:
            print(f"  · {line}")
    print(
        "Fuente: catálogo oficial de señales del RD 465/2025 (BOE). "
        "Cada pregunta enlaza su código y su significado oficial."
    )
    return 0


def _fetch_anki(args: argparse.Namespace, target: Path) -> int:
    from theoricum.fetchers.anki import REPO_URL, fetch_anki

    report = fetch_anki(target, refresh=args.refresh, log=lambda m: print(m, flush=True))
    release = report.release
    version = f"versión {release.tag}" if release else "versión desconocida"
    if report.differs:
        print(
            f"Ya hay un {report.path.name} en {report.path.parent} que no es la última "
            f"{version}. No lo toco: usa --refresh para reemplazarlo."
        )
        return 1
    if report.up_to_date:
        print(f"\nYa tienes la última {version} del mazo en {report.path}.")
    else:
        print(f"\nListo: mazo «Carnet B» ({version}) en {report.path}.")
    if report.sidecar_written:
        print(f"Ajustes del mazo en {report.path.name}.toml (fecha, prioridad y limpieza).")
    print(
        f"Es un mazo de la comunidad ({REPO_URL}, GPL-3.0). Su autor indica que las preguntas "
        "salen de la web de una autoescuela: úsalo solo para tu estudio personal."
    )
    return 0


FETCHERS = {
    "revista-dgt": _fetch_revista,
    "dgt-web": _fetch_dgt_web,
    "signals": _fetch_signals,
    "anki": _fetch_anki,
}


def _fetch_manual(args: argparse.Namespace, data_dir: Path) -> int:
    from theoricum.fetchers.manual import TITLE, fetch_manual

    report = fetch_manual(data_dir, refresh=args.refresh, log=lambda m: print(m, flush=True))
    state = "Ya tenías" if report.already else "Listo:"
    print(f"\n{state} el «{TITLE}», {len(report.chapters)} temas en {report.folder}.")
    print("Ábrelo con `dgt manual` o un tema con `dgt manual signals` (o la tecla m en un test).")
    print("Es material de la DGT: úsalo para tu estudio personal.")
    return 0


def _fetch_laws(args: argparse.Namespace, data_dir: Path) -> int:
    from theoricum.fetchers.laws import fetch_laws

    report = fetch_laws(data_dir, log=lambda m: print(m, flush=True))
    print()
    for name, count, updated in report.laws:
        print(f"  ✓ {name}: {fmt_int(count)} artículos, actualizado el {updated or '¿?'}")
    print("Consúltala con `dgt laws` (o la tecla n en un test). Fuente: BOE, texto consolidado.")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    if args.last is not None and (args.source != "revista-dgt" or args.last < 1):
        print("--last solo vale para revista-dgt y debe ser 1 o más.", file=sys.stderr)
        return 2
    if args.source in DATA_SOURCES and args.into:
        print(
            "--into solo vale para preguntas: el manual y la normativa van a tu carpeta de datos.",
            file=sys.stderr,
        )
        return 2
    paths = _paths(args)
    if args.source in DATA_SOURCES:
        fetch = _fetch_manual if args.source == "manual" else _fetch_laws
        try:
            return fetch(args, paths.data_dir)
        except ConnectionError as exc:
            print(f"Error de red: {exc}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(f"No se pudo leer lo descargado: {exc}", file=sys.stderr)
            return 1
    target = _fetch_target(args, paths)
    target.mkdir(parents=True, exist_ok=True)
    print(f"Carpeta: {target}")
    try:
        code = FETCHERS[args.source](args, target)
    except ConnectionError as exc:
        print(f"Error de red: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(
            "\nInterrumpido. Lo descargado hasta ahora se ha guardado; vuelve a ejecutarlo para seguir."
        )
        return 130
    if not any(target == d for d in paths.question_dirs):
        print(
            f"Ojo: {target} no es una de tus carpetas de preguntas; usa --questions-dir para leerla."
        )
    return code


def _english_only(command: str, exc: Exception) -> str:
    from theoricum.topics import SpanishTopicName

    assert isinstance(exc, SpanishTopicName)
    return (
        f"Los comandos van en inglés: usa «{exc.cli}» en vez de «{exc.value}» "
        f"(por ejemplo, `dgt {command} {exc.cli}`). `dgt topics` lista los nombres."
    )


def cmd_manual(args: argparse.Namespace) -> int:
    from theoricum.manual import POINTS, TOPIC_CHAPTERS, load_manual, open_document
    from theoricum.models import date_label
    from theoricum.topics import SpanishTopicName, cli_name
    from theoricum.validity import novelties

    paths = _paths(args)
    manual = load_manual(paths.data_dir)
    if manual is None:
        print("Aún no tienes el manual: lo descargo ahora.\n")
        try:
            _fetch_manual(argparse.Namespace(refresh=False), paths.data_dir)
        except (ConnectionError, ValueError) as exc:
            print(f"No se pudo descargar el manual: {exc}", file=sys.stderr)
            return 1
        manual = load_manual(paths.data_dir)
        if manual is None:
            return 1
    target, what = manual.full, "el manual completo"
    if args.chapter:
        try:
            chapter = manual.find(args.chapter)
        except SpanishTopicName as exc:
            print(_english_only("manual", exc), file=sys.stderr)
            return 2
        if chapter is None:
            print(f"No encuentro el tema «{args.chapter}». Puedes usar:", file=sys.stderr)
            for c in manual.chapters:
                print(f"  {c.number:>2}. {c.title}", file=sys.stderr)
            names = ", ".join(sorted(cli_name(t) for t in TOPIC_CHAPTERS))
            print(f"o un tema de theoricum ({names}) o «{POINTS}».", file=sys.stderr)
            return 2
        target, what = manual.path(chapter), f"el tema {chapter.number}: {chapter.title}"
    else:
        print(f"{manual.title}. Temas:")
        for c in manual.chapters:
            print(f"  {c.number:>2}. {c.title} (página {c.first_page})")
    changes = novelties(after=manual.date)
    if changes:
        print(f"\nOjo: el manual es de {date_label(manual.date)}. Desde entonces ha cambiado:")
        for change in changes:
            print(f"  · {change.title} ({date_label(change.since)}): {change.summary}")
    print(f"\nAbriendo {what}: {target}")
    try:
        open_document(target)
    except OSError as exc:
        print(f"No he podido abrirlo ({exc}). Ábrelo tú desde esa ruta.", file=sys.stderr)
        return 1
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from theoricum.backup import export_zip

    paths = _paths(args)
    store, _ = _open_synced_store(paths, verbose=False)
    try:
        out = export_zip(
            store,
            paths.question_dirs,
            Path(args.output) if args.output else None,
            history=not args.no_history,
        )
    finally:
        store.close()
    print(f"Exportado: {out}")
    print(
        "Guárdalo en tu nube privada. Contiene preguntas e imágenes que no se pueden compartir públicamente."
    )
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    from theoricum.backup import BackupError, import_zip
    from theoricum.db.store import Store
    from theoricum.library import sync

    paths = _paths(args)
    target = Path(args.into).expanduser().resolve() if args.into else paths.questions_dir
    store = Store.open(paths.db_path)
    try:
        summary = import_zip(
            store,
            target,
            Path(args.file),
            overwrite=args.overwrite,
            # With --into, compare only with that folder: the files are wanted there.
            search_dirs=[target] if args.into else paths.question_dirs,
        )
        sync(store, paths.question_dirs)
    except BackupError as exc:
        print(f"No se pudo importar: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()
    print(f"Carpeta para las preguntas nuevas: {target}")
    print(summary.describe())
    if not any(target == d for d in paths.question_dirs):
        print(
            f"Ojo: {target} no es una de tus carpetas de preguntas; usa --questions-dir para leerla."
        )
    return 1 if summary.failed else 0


def _image_protocol(args: argparse.Namespace) -> str:
    chosen = getattr(args, "image_protocol", None) or os.environ.get(
        "THEORICUM_IMAGE_PROTOCOL", "auto"
    )
    if chosen not in IMAGE_PROTOCOLS:
        print(f"Protocolo de imagen desconocido «{chosen}»; uso «auto».", file=sys.stderr)
        return "auto"
    return chosen


def cmd_tui(args: argparse.Namespace) -> int:
    from theoricum.topics import SpanishTopicName, topic_from_cli
    from theoricum.tui.terminal import guard_image_probe

    topic = getattr(args, "topic", None)
    if topic:
        try:
            topic = topic_from_cli(topic)
        except SpanishTopicName as exc:
            print(_english_only("study --topic", exc), file=sys.stderr)
            return 2
    guard_image_probe()
    # Importing the TUI makes textual-image probe the terminal; this must happen before App.run().
    from theoricum.tui.app import StartRequest, run_app

    start = StartRequest(
        command=args.command or "menu",
        topic=topic,
        n=getattr(args, "n", None),
        query=" ".join(getattr(args, "query", None) or []),
    )
    return run_app(
        paths=_paths(args),
        start=start,
        image_protocol=_image_protocol(args),
        since=getattr(args, "since", None),
        seed=getattr(args, "seed", None),
    )


COMMANDS = {
    "check": cmd_check,
    "manual": cmd_manual,
    "topics": cmd_topics,
    "fetch": cmd_fetch,
    "export": cmd_export,
    "import": cmd_import,
}


def _robust_console() -> None:
    """Never crash on characters the console cannot encode (e.g. a cp1252 pipe on Windows)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(OSError, ValueError):
                reconfigure(errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    _robust_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = COMMANDS.get(args.command or "", cmd_tui)
    try:
        return handler(args)
    except NoQuestionsFolder as exc:
        print(f"dgt: error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
