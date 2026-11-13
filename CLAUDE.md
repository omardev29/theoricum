# CLAUDE.md — theoricum

A Python TUI to practise the Spanish DGT theory exam (driving permit B) in the terminal, free and
open source. The engine and the UI are public (GPL-3.0-or-later). The questions are **personal**
and never enter the repository.

## Sacred contracts — read this first

The question format and the backups are the most important part of this project. People keep
their question packs and their history for years and move them between Linux, macOS and Windows
with `dgt export` / `dgt import`. **Never break them, for any reason.** No feature, refactor or
cleanup justifies it.

Frozen, forever:

1. **Native pack format `theoricum/1`** (JSON or TOML, same schema; see "The question folder
   contract" below). Every field keeps its name and meaning. Every pack that imports today must
   import tomorrow with the same result, including the lenient bits: lowercase answer letters,
   TOML dates, a missing question `id` (becomes `q<position>` with a warning), unknown keys
   ignored. You may add *optional* fields; you may not rename, remove or reinterpret one, or make
   a valid pack invalid.
2. **Question keys** — the identity that the whole history points to:
   - `<pack.id>:<id>`;
   - without a pack `id`: the pack's path inside the questions folder that holds it, without
     extension and always with `/` (`ia/mias:q1`, also on Windows). The folder itself never
     matters, so packs can move between `./questions`, `~/Questions` or any other folder;
   - without a question `id`: `q<position>` (1-based);
   - Anki notes: `anki:<guid>`.
   Changing how a key is computed silently orphans the user's history. Never do it without a
   database migration that rewrites the old keys.
3. **Image refs** stored relative to the questions folder, with `/`: `file:<path>` and
   `apkg:<path>!<member>`.
4. **Backups `theoricum-export/1`**: a zip with `manifest.json`, `questions/…` and `history.json`
   (`theoricum-history/1`: sessions by `uuid` with their answers, `flags`, `saved`). Every v1 zip
   ever written must keep importing: sessions merge by `uuid`, importing twice changes nothing,
   the user's files are never deleted, and differing files are kept unless `--overwrite`. A new
   export must still write every v1 field (adding fields is fine: older versions ignore them).
5. **User data in SQLite** (`sessions`, `answers`, `flags`, `saved`): the sync never touches it.
   Schema changes only through a new migration appended in `db/migrations.py` (`PRAGMA
   user_version`); never edit a released migration.
6. **Origins** `dgt | revista-dgt | anki | ia | otro`: packs in the wild use them.
7. **Pack ids and folders written by the fetchers**: `revista-dgt`, `dgt-web`,
   `signals-rd465` (folder `signals/`) and the Anki deck `anki/Carnet.B.apkg` (keys
   `anki:<guid>`). Renaming them orphans the history of everyone who already fetched them.
8. **Where questions are found**: a `questions/` folder in the current directory and
   `~/Questions` (both in any case), plus the old default `<data dir>/questions` while
   `~/Questions` does not exist. Never stop reading a location users already rely on.

If a breaking change is truly unavoidable: add a new version (`theoricum/2`,
`theoricum-export/2`) next to the old one, keep reading the old one forever, write the migration
and its tests, and tell the user before merging.

Enforcement:
- `tests/test_contract.py` imports the **frozen fixtures** in `tests/contract/` (packs with and
  without ids, an Anki deck, a v1 export) and checks keys, content, history, flags and saved
  questions. **Never edit the fixtures or the expectations to make a test pass**: fix the code.
- Run `uv run pytest tests/test_contract.py` after touching `models.py`, `importers/`,
  `library/`, `db/`, `backup.py` or `media.py`. CI runs everything on Linux, macOS and Windows.
- When an importer's output changes, bump `IMPORTER_VERSION` (`importers/__init__.py`) so cached
  sources are re-imported.

## Language rules (mandatory)

- **English**: everything you type on the command line — commands, subcommands, flags and their
  values (`dgt fetch signals --into DIR`, `dgt exam --no-global`) — plus identifiers, comments,
  docstrings, commit messages and the docs for developers and agents (this file,
  `tests/contract/README.md`).
- **Spanish**: everything the user reads — questions, the TUI, `--help` texts, CLI messages
  (validation errors too), the README and the comments of data files users may open
  (`data/*.toml`, generated sidecars). The audience is people taking the exam in Spain, so there
  is no English UI.

## Tooling

- **uv only**, never `pip`: `uv add <pkg>` (or `uv add --dev`), `uv run dgt …`, `uv run pytest`,
  `uv run ruff check`, `uv run ruff format`.
- **Minimum uv: 0.9.0** (`[tool.uv] required-version`), the first one that downloads a stable
  CPython 3.14 (0.8.x installs 3.14.0rc3). Keep the floor as low as the project allows: users get
  uv from Scoop, pacman, Homebrew or the official installer and do not always update. The `min-uv`
  CI job runs the suite with exactly that version; raise the floor only when a feature needs it
  (e.g. a lockfile revision 0.9.0 cannot read), and say why in `pyproject.toml`. The build backend
  (`uv_build>=0.13.7,<0.14.0`) is downloaded from PyPI, so it does not constrain the user's uv.
- **Python 3.14, always uv-managed** (`.python-version`, `requires-python >= 3.14`,
  `python-preference = "only-managed"`): the system Python is never used, so Linux, macOS and
  Windows run the same python-build-standalone build (with `compression.zstd`, which reads modern
  Anki `.apkg` files).
- Global install: `uv tool install --managed-python git+https://github.com/omardev29/theoricum`
  (or `.` from a clone, `-e .` to follow the working tree). CI installs it this way on every OS.
- New dependencies: prefer pure-Python wheels that work on all three OSes; lock a release that has
  been out for a couple of weeks (e.g. `pypdf>=6.21,<7`), not one published today.
- Reference terminals: **kitty** (TGP) and **foot** (Sixel) on Linux, **Windows Terminal ≥ 1.22**
  (Sixel) on Windows. All of them matter equally.

## Cross-platform (Linux, macOS, Windows)

- CI (`.github/workflows/ci.yml`) runs ruff and pytest on ubuntu, windows and macos. Keep it green.
- Data paths come from `platformdirs` (`config.default_data_dir()`): `~/.local/share/theoricum`
  (honours `$XDG_DATA_HOME`), `%LOCALAPPDATA%\theoricum`, `~/Library/Application
  Support/theoricum`. Never hard-code `~/.local`.
- Always open text files with `encoding="utf-8"`: Windows does not default to UTF-8.
- URLs are POSIX paths: use `PurePosixPath` / `url_suffix()`, never `Path(url)`. Stored paths
  (`image_ref`, zip entries, keys of packs without `id`) always use `/` (`as_posix()`).
- Zip entries with `\`, `:` (drives, Windows ADS), absolute paths or `..` are rejected.
- `dgt import` skips and lists files the OS cannot create (e.g. `?` or `*` on Windows), goes on,
  and exits with code 1.
- The CLI reconfigures stdout/stderr with `errors="replace"` so cp1252 pipes do not crash.
- Home folder: `Path.home()` (`$HOME`; `%USERPROFILE%` on Windows). Tests that need a home fake
  both variables, or pass `home=`/`cwd=` to `resolve_paths`.

## Question folders (`config.py`)

- Read, in this order: `./questions` (the **local** folder, in the current directory) and
  `~/Questions` (the **global** folder). Names match in any case (`qUestions`), keeping the real
  spelling; if several match on a case-sensitive file system, the exact spelling wins.
- While `~/Questions` does not exist, the old default `<data dir>/questions` is the global folder
  if it has files (`dgt check` suggests moving it; keys and history do not change).
- **First folder wins**: a relative path (pack, image, sidecar…) always means the file of the
  first folder that has it; copies in later folders are ignored (`ScanResult.shadowed`). The
  scan, `MediaResolver`, `dgt export` and `dgt import` all apply this same rule.
- `--no-local` / `--no-global` ignore one of them (both → error). `--questions-dir` or
  `$THEORICUM_QUESTIONS` use one explicit folder and nothing else (tests and CI use this).
- New files go to `Paths.questions_dir`: the local folder if it exists, else the global one
  (created on demand). `dgt fetch` updates a source in the folder that already has it
  (`FETCH_MARKERS`); `dgt import` does not copy files that a folder in use already has, treats
  different ones as conflicts and, with `--overwrite`, rewrites them where they are. `--into DIR`
  forces the destination of both.

## Architecture (layers)

```
src/theoricum/
  models.py      shared dataclasses (Question, Notice, PackMeta…) and label helpers
  config.py      folders: ./questions + ~/Questions (any case), flags, the old default
  topics.py      canonical topics (data/topics.toml), keyword classifier, keyword_pattern()
  validity.py    regulatory changes (data/changes.toml) -> notices on older questions
  media.py       resolves image_ref ("file:…", "apkg:…!member") to bytes
  practice.py    store <-> engine glue used by the TUI (build tests, record answers, stats)
  importers/     READ-ONLY adapters over questions/: native (JSON/TOML), apkg, anki_json (CrowdAnki)
  fetchers/      `dgt fetch` downloaders (http.py: polite client with streamed downloads;
                 revista_dgt, dgt_web, signals, anki)
  library/       scan of questions/ and incremental sync into SQLite
  db/            schema, migrations (PRAGMA user_version), queries (store.py)
  engine/        PURE test logic, no Textual, no SQLite: rules, session, selection, grading,
                 stats, pool (duplicate resolution)
  tui/           presentation only (Textual); imported only when the TUI starts
  backup.py      `dgt export` / `dgt import`
  cli.py         argparse; entry point `dgt`
```

- `engine/` imports neither `textual` nor `sqlite3`: dataclasses in, dataclasses out, pure tests.
- The database has two parts:
  - **content cache** (`sources`, `questions`): rebuilt from the question folders at any time;
  - **user data** (`sessions`, `answers`, `flags`, `saved`): references the stable question `key`
    without foreign keys, so it survives files changing or disappearing. The sync **never**
    touches it.
- Migrations: v1 is `db/schema.sql`; v2 adds `saved` («Preguntas guardadas», key `g`), which
  replaced the old «dudosa» mark (`flags.flagged`, no longer used but still exported).

## The active pool (`Store.load_questions`)

1. Enabled sources, minus questions disabled by the user (`x`), excluded topics and `--since`.
2. **Duplicates** across sources share `dedup` (hash of the normalized statement and options);
   `engine/pool.py` picks the copy to ask:
   - all copies agree on the answer → highest `priority` wins (dgt 100 > signals 95 >
     revista-dgt 90 > anki 50 > ia 10). Priority only picks the copy: it never changes how often
     a question is asked (that is `engine/selection.py`);
   - they disagree and the statement refers to its picture («esta señal», «este vehículo»…) →
     they are different questions that share wording: one copy per answer is kept;
   - they disagree otherwise → the rules changed: the **most recent date** wins and carries an
     `info` notice with the other answer (real case: 100 km/h in 2017 vs 90 km/h in 2025).
3. **Validity** (`validity.py`, `data/changes.toml`): a question dated before a regulatory change
   (or undated) whose statement or *right answer* matches its keywords gets a notice. `warning`
   marks it «⚠ posible anticuada» and keeps it out of exams; `info` only adds a note after the
   correction. Only add changes with a verified legal basis and cite the norm in the note.
- Options are **never shuffled**: some answers read «Ambas son correctas».

## Selection and review

- **Official quota**: the 90-odd questions of the official simulator (`origin = "dgt"`) are real
  exam questions, but a uniform draw from ~4,000 would ask 0.67 per exam and none in half of them.
  So every exam and every study/topic session includes up to `OFFICIAL_QUOTA` (6) official
  questions that are not mastered yet (3 right in a row), weighted by `review_weight` (never seen
  = 1, failed often = more). Once all are mastered they come back only by chance.
- Exam: the quota, then a uniform random sample of the current (non-outdated) pool.
- Study: the quota, then never-seen questions, the **most recent dates first** (official ones are
  dated when fetched, so they come first until seen), then the ones seen longest ago; the picked
  ones are asked in random order.
- Review: a question is pending if it was ever failed and has not yet been answered right 3 times
  in a row (`MASTERED_STREAK`). Weight `(1 + fails) / (1 + streak)²`. The TUI shows
  «↻ repaso n/3» and «✓ sale del repaso»; in an exam only after the correction.
- Study sessions left without answering anything do not count (`abandoned`).

## The question folder contract

- The repo's `questions/` is empty (only `.gitkeep`); when `dgt` runs from the repo it is the
  local folder. Everything inside the question folders is adopted automatically: on start, when
  returning to the menu, with `r` in the menu or with `dgt check`. Hidden files and folders are
  ignored (also by `dgt export`).
- Native format `theoricum/1`, JSON or TOML (same schema), images relative to the pack:

  ```toml
  format = "theoricum/1"
  [pack]
  id = "senales-nuevas"   # optional; otherwise the path is the namespace
  name = "Señales nuevas"
  origin = "ia"           # dgt | revista-dgt | anki | ia | otro
  date = "2026-09"
  priority = 10           # optional; default by origin
  enabled = true          # optional
  exclude_topics = []     # optional
  [[questions]]
  id = "s-001"
  text = "¿Qué indica esta señal?"
  image = "img/s-001.png"
  options = ["…", "…", "…"]   # 2 to 4
  answer = "A"
  topic = "senales"           # optional; otherwise classified by keywords
  date = "2026-09"            # optional; otherwise the pack date
  explanation = "…"           # optional
  tags = []                   # optional
  source = "…"                # optional
  ```

- Also adopted: Anki `*.apkg`/`*.colpkg` (v1/v2 legacy SQLite, v3 zstd) with an optional sidecar
  `<file>.toml` (field mapping, metadata, cleanup); CrowdAnki folders (`deck.json`). Anki images
  are read on demand from inside the package, never extracted.

## Sources and legal rules

- **Never commit questions, images or exports** (`questions/*`, `*.apkg`, `*.zip` are ignored).
  `examples/` and `tests/contract/` hold only self-made content without DGT material.
- **DGT magazine** «Tráfico y Seguridad Vial» (`dgt fetch revista-dgt [--last N]`,
  `fetchers/revista_dgt.py`):
  - goes **newest first** (an interrupted run already has the latest test); `--last N` keeps to
    the N most recent published tests;
  - texts may be reproduced citing the magazine; images only for personal, private use;
  - tests 224 onwards (~4 per year, 15 questions each); the pages publish 250×226 px images
    only (no larger version exists on the site);
  - own code: driveprep has no license (nothing copied); `jorgebg/dgt-anki-flashcards` (MIT) is
    only a reference.
- **Official sign catalogue** (`dgt fetch signals`, `fetchers/signals.py`): downloads the BOE PDF
  of RD 465/2025 (BOE-A-2025-12199, ~27 MB, immutable) and builds «¿Qué indica esta señal?»
  questions (455 P/R/S signs) with the official name as the answer, the official meaning as the
  explanation and the embedded images. Legal texts are not copyrighted in Spain (art. 13 LPI) and
  the BOE allows reuse citing the source; still, the result lives only in `signals/` of a
  questions folder (pack id `signals-rd465`, priority 95: the law itself, above the magazine).
  Without `--refresh`, an existing pack only gets the current `[pack]` settings (`PACK_META`),
  without downloading the BOE again.
  - Structure comes from positioned chunks (code column, name column, image box per table row);
    wording comes from pypdf's plain text, aligned by comparing without spaces;
    `heal_split_words` rejoins the few words the justified PDF splits.
  - Distractors are the nearest signs of the same section, and every sign gets a set of options
    no other sign has. The option order depends only on the code (stable across runs).
- **Official DGT simulator** (`dgt fetch dgt-web`, `fetchers/dgt_web.py`): JSF (Apache MyFaces
  Tobago) with a session and only 2–3 questionnaires per permit. Every step is a POST of the
  **outer** form (Tobago nests `<form>`; the outer one carries the Secret token);
  `javax.faces.source` names the clicked button. Buttons are found by class or id suffix, never
  by `j_id_*`. The flow goes straight to «finalizar examen»; the correction marks the right option
  (`…:rbrok`, `boton_correcta.gif`) and «Siguiente» walks the 30 questions. Sessions repeat until
  no new questions appear.
- **Anki deck «Carnet B»** (`dgt fetch anki`, `fetchers/anki.py`; donmerendolo/anki-carnet-conducir,
  GPL-3.0): downloads `Carnet.B.apkg` from the repo's latest GitHub release into `anki/`, writes
  a sidecar marked as generated (a hand-written sidecar is never touched) and remembers the
  release in a hidden `.carnet-b.json`. A deck already there that it did not download is only
  replaced with `--refresh`. Its author says the questions come from a driving school website,
  so the command only automates the public download, prints a private-use warning, and the deck
  is never bundled with theoricum (owner's decision, 2026-11-13). Commercial test sites: never.
- Users back up questions and history with `dgt export` to their private cloud and restore with
  `dgt import`.

## Images

Most images are small (magazine 250×226 px, Anki ~200 px, BOE signs ~208 px; only the official
simulator gives 640×480), so they are always enlarged. `tui/images.py`:
- decodes once into an LRU cache bounded by pixel count (`MAX_SIDE` 1600 for the zoom); small
  images get a mild unsharp mask once, at their own size;
- `install_quality_hooks()` patches two textual-image internals: `PixelData.scaled` uses Lanczos
  (instead of bicubic) and the Sixel quantizer dithers with Floyd–Steinberg (instead of
  posterizing to 256 colors). If textual-image renames them, the app still works (softer images)
  and `test_image_quality_hooks_are_installed_in_textual_image` fails: update the hooks;
- `z` opens `ImageZoomScreen` (a plain Screen, never a ModalScreen) with the whole terminal for
  the image; in an exam the countdown keeps running and is shown;
- the help screens (`?`) show the protocol in use and the cell size, to diagnose terminals.
- Windows Terminal draws Sixel in a fixed 10×20 px virtual cell and scales it to the real font,
  so detail comes from the number of cells: the zoom (or a smaller font) is what helps there.
- To check image quality without a graphic terminal, reproduce the pipeline with PIL (`prepare`,
  `PixelData.scaled`, `_sixel._prepare_image`) and look at the PNGs.

## textual-image: caveats

- It probes the terminal **when imported** and cannot once Textual runs. So `theoricum.tui` is
  imported only when launching the TUI, before `App.run()`, and never from `export`, `import`,
  `check` or `fetch`. `tui/terminal.py` guards the probe on 0×0 ptys.
- There is no environment variable to force a protocol in textual-image itself:
  `--image-protocol` (or `THEORICUM_IMAGE_PROTOCOL`) picks the class (`TGPImage`, `SixelImage`,
  `HalfcellImage`, `UnicodeImage`) that is injected into the App. No chafa (no 3.14 wheels).
- Translucent overlays break kitty (TGP) images: the tint changes the foreground color, which
  encodes the image id. So `ModalScreen` backgrounds are `transparent` (no tint), the command
  palette is disabled, and there is no `opacity`/`tint`/`:hover` on image containers.
- textual-image re-encodes on every `render()`: it is given already decoded `PIL.Image`s.
- Tests use `UnicodeImage` (deterministic); `TGPImage` writes straight to stdout. One test drives
  `SixelImage` (the Windows Terminal / foot path).

## Textual 8 notes

- `MODES`/`SCREENS` take classes or callables, not instances. Use `Static.content`, not
  `.renderable`.
- In tests: `app.screen.query_one(...)` and `await pilot.pause()` after every screen change.
  pytest-textual-snapshot is not used (it pins pytest < 9).
- To review the layout without a graphic terminal: `app.save_screenshot()` inside `run_test()`
  and `rsvg-convert` to PNG (the SVG sometimes eats spaces; the real terminal is fine).

## Tests

`uv run pytest`: engine, importers (`.apkg` v1/v2/v3 built by `tests/anki_builder.py`), sync,
contracts, backup, validity, fetchers (synthetic HTML, fake HTTP and a synthetic BOE-like PDF from
`tests/pdf_builder.py`, never the network) and the TUI with Pilot. `examples/ejemplo.toml` is a
self-made demo pack that documents the format.

## Exam rules (permit B)

- 30 questions, 30 minutes, at most 3 errors; blanks count as errors; 3 options (A/B/C), one
  right. Legal basis: RD 818/2009, checked in force in 2026; the video question announced in 2025
  is not in force.
- Configurable in `engine/rules.py` (`ExamRules`).
- Recent norms that can make older questions outdated (each question keeps and shows its date):
  RD 465/2025 (new sign catalogue), RD 159/2021 (V-16 beacon since 1-1-2026), RD 518/2026
  (vulnerable road users, in force since 1-10-2026). See `data/changes.toml`.

## App commands

```
dgt                                  control panel
dgt exam | study [--topic T] [-n N] | review [-n N]
dgt topics | stats | saved | check
dgt fetch {revista-dgt,dgt-web,signals,anki} [--refresh] [--into DIR] [--last N (revista-dgt)]
dgt export [-o FILE] [--no-history] | dgt import FILE [--overwrite] [--into DIR]
global: --questions-dir --no-local --no-global --data-dir --image-protocol --since YYYY[-MM]
        --seed --version
test keys: a/b/c answer · ←/→ move · Enter submit/next · g save · x disable · z zoom image
```
