"""Command line entry point (`dgt`). Commands and flags in English, messages in Spanish."""

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from theoricum import __version__
from theoricum.config import Paths, resolve_paths

IMAGE_PROTOCOLS = ("auto", "tgp", "sixel", "halfcell", "unicode")
FETCH_SOURCES = ("revista-dgt", "dgt-web")

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
        help="carpeta de preguntas (por defecto ./questions, $THEORICUM_QUESTIONS o XDG)",
    )
    group.add_argument(
        "--data-dir",
        metavar="DIR",
        default=argparse.SUPPRESS,
        help="carpeta del progreso (por defecto ~/.local/share/theoricum o $THEORICUM_DATA)",
    )
    group.add_argument(
        "--image-protocol",
        choices=IMAGE_PROTOCOLS,
        default=argparse.SUPPRESS,
        help="cómo dibujar las imágenes (por defecto auto: kitty usa TGP)",
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
        epilog="Sin comando abre el panel de control. Las preguntas se leen de la carpeta questions/.",
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
        "--topic", metavar="TEMA", help="solo preguntas de este tema (ver `dgt topics`)"
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
    sub.add_parser(
        "check", parents=[common], help="sincroniza y valida questions/ sin abrir la interfaz"
    )

    fetch = sub.add_parser("fetch", parents=[common], help="descarga preguntas a questions/")
    fetch.add_argument("source", choices=FETCH_SOURCES, help="fuente a descargar")
    fetch.add_argument("--refresh", action="store_true", help="vuelve a descargarlo todo")

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
        "--overwrite", action="store_true", help="sobrescribe archivos de preguntas distintos"
    )
    return parser


def _paths(args: argparse.Namespace) -> Paths:
    return resolve_paths(getattr(args, "questions_dir", None), getattr(args, "data_dir", None))


def _open_synced_store(paths: Paths, *, verbose: bool):
    from theoricum.db.store import Store
    from theoricum.library import sync

    store = Store.open(paths.db_path)

    def progress(done: int, total: int, rel: str) -> None:
        if verbose and rel:
            print(f"  importando {rel} ({done + 1}/{total})…", file=sys.stderr)

    report = sync(store, paths.questions_dir, progress=progress)
    return store, report


def cmd_check(args: argparse.Namespace) -> int:
    from theoricum.models import ORIGIN_LABELS
    from theoricum.topics import topic_name

    paths = _paths(args)
    print(f"Carpeta de preguntas: {paths.questions_dir}")
    print(f"Base de datos:        {paths.db_path}")
    if not paths.questions_dir.is_dir():
        print("\nLa carpeta de preguntas no existe. Crea questions/ y deja ahí tus packs.")
        return 1
    store, report = _open_synced_store(paths, verbose=True)
    sources = store.sources()
    print(f"\nFuentes ({len(sources)}):")
    if not sources:
        print("  (ninguna) Deja packs JSON/TOML, mazos .apkg o carpetas CrowdAnki en questions/.")
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
    store.close()
    return 1 if any(s.error for s in sources) else 0


def cmd_topics(args: argparse.Namespace) -> int:
    from theoricum.topics import topic_name

    store, _ = _open_synced_store(_paths(args), verbose=False)
    topics = Counter(q.topic for q in store.load_questions(since=getattr(args, "since", None)))
    store.close()
    if not topics:
        print("No hay preguntas. Ejecuta `dgt check` para ver qué pasa con questions/.")
        return 1
    print(f"{'TEMA':<16} {'NOMBRE':<40} {'PREGUNTAS':>9}")
    for slug, count in sorted(topics.items(), key=lambda item: topic_name(item[0])):
        print(f"{slug:<16} {topic_name(slug):<40} {fmt_int(count):>9}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    paths = _paths(args)
    paths.questions_dir.mkdir(parents=True, exist_ok=True)
    try:
        if args.source == "revista-dgt":
            from theoricum.fetchers.revista_dgt import fetch_revista

            report = fetch_revista(
                paths.questions_dir, refresh=args.refresh, log=lambda m: print(m, flush=True)
            )
            print(
                f"\nListo: {len(report.tests_fetched)} tests nuevos, {fmt_int(report.questions_added)} "
                f"preguntas nuevas, {fmt_int(report.total_questions)} en total."
            )
            if report.tests_missing:
                print(
                    f"Tests que no existen en la web: {', '.join(map(str, report.tests_missing))}"
                )
            if report.images_failed:
                print(f"Imágenes que no se pudieron descargar: {report.images_failed}")
            for warning in report.warnings:
                print(f"  · {warning}")
            print(
                "Recuerda: las imágenes de la revista son solo para uso personal; no las compartas."
            )
        else:
            from theoricum.fetchers.dgt_web import SimulatorError, fetch_dgt_web

            try:
                report = fetch_dgt_web(
                    paths.questions_dir, refresh=args.refresh, log=lambda m: print(m, flush=True)
                )
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
    except ConnectionError as exc:
        print(f"Error de red: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(
            "\nInterrumpido. Lo descargado hasta ahora se ha guardado; vuelve a ejecutarlo para seguir."
        )
        return 130
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from theoricum.backup import export_zip

    paths = _paths(args)
    store, _ = _open_synced_store(paths, verbose=False)
    try:
        out = export_zip(
            store,
            paths.questions_dir,
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
    store = Store.open(paths.db_path)
    try:
        summary = import_zip(store, paths.questions_dir, Path(args.file), overwrite=args.overwrite)
        sync(store, paths.questions_dir)
    except BackupError as exc:
        print(f"No se pudo importar: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()
    print(summary.describe())
    return 0


def cmd_tui(args: argparse.Namespace) -> int:
    from theoricum.tui.terminal import guard_image_probe

    guard_image_probe()
    # Importing the TUI makes textual-image probe the terminal; this must happen before App.run().
    from theoricum.tui.app import StartRequest, run_app

    start = StartRequest(
        command=args.command or "menu",
        topic=getattr(args, "topic", None),
        n=getattr(args, "n", None),
    )
    return run_app(
        paths=_paths(args),
        start=start,
        image_protocol=getattr(args, "image_protocol", "auto"),
        since=getattr(args, "since", None),
        seed=getattr(args, "seed", None),
    )


COMMANDS = {
    "check": cmd_check,
    "topics": cmd_topics,
    "fetch": cmd_fetch,
    "export": cmd_export,
    "import": cmd_import,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = COMMANDS.get(args.command or "", cmd_tui)
    try:
        return handler(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
