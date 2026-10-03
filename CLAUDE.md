# CLAUDE.md — theoricum

TUI en Python para practicar el examen teórico de la DGT (permiso B) desde la terminal. El motor y la
interfaz son públicos (GPL-3.0-or-later). Las preguntas son **personales** y nunca entran en el repo.

## Reglas de idioma (obligatorias)

- **Inglés**: comandos y flags de la CLI (`dgt exam --topic`), identificadores, comentarios, docstrings
  y mensajes de commit.
- **Español**: todo lo que ve el usuario. Eso incluye las preguntas, la TUI, la ayuda y los mensajes de
  la CLI (también los errores de validación), el README y este archivo.

## Herramientas

- Solo **uv**, nunca `pip`. Usa `uv add <paquete>` (o `uv add --dev`), `uv run dgt …`, `uv run pytest`,
  `uv run ruff check` y `uv run ruff format`.
- Python ≥ 3.14, porque se usa `compression.zstd` de la stdlib para leer los `.apkg` modernos de Anki.
  CachyOS/Arch trae 3.14 y uv lo descarga si falta.
- Terminal de referencia: kitty, donde textual-image usa el protocolo TGP.

## Multiplataforma (Linux, macOS, Windows)

- La CI (`.github/workflows/ci.yml`) pasa ruff y pytest en ubuntu, windows y macos. Cualquier cambio
  debe mantenerla en verde.
- Rutas de datos con `platformdirs` (`config.default_data_dir()`):
  - Linux: `~/.local/share/theoricum` (respeta `$XDG_DATA_HOME`);
  - Windows: `%LOCALAPPDATA%\theoricum`;
  - macOS: `~/Library/Application Support/theoricum`.
  Nunca escribas rutas fijas tipo `~/.local`.
- Abre siempre los archivos de texto con `encoding="utf-8"`: en Windows la codificación por defecto no
  es UTF-8.
- Las URL son rutas POSIX: usa `PurePosixPath` / `url_suffix()`, nunca `Path(url)`. Las rutas guardadas
  (`image_ref`, zip) van siempre con `/` (`as_posix()`).
- En los zips se rechazan entradas con `\`, `:` (unidades y ADS de Windows), absolutas o con `..`.
- Imágenes en Windows: Windows Terminal ≥ 1.22 soporta **Sixel**, y textual-image lo detecta solo
  (`SixelImage`). Las consolas sin gráficos usan bloques de color (halfcell). No se usa chafa: chafa.py
  no tiene wheels para Python 3.14. Hay un test de la TUI con `SixelImage`.
- `THEORICUM_IMAGE_PROTOCOL` fija el protocolo sin necesidad del flag.
- La CLI reconfigura stdout/stderr con `errors="replace"` para no romper con tuberías en cp1252.

## Arquitectura (capas)

```
src/theoricum/
  models.py     dataclasses compartidas (Question, PackMeta, …)
  config.py     resolución de rutas (flags > env > ./questions > XDG)
  topics.py     temas canónicos (data/topics.toml) y clasificador por palabras clave
  media.py      resuelve image_ref ("file:…", "apkg:…!miembro") a bytes
  practice.py   pegamento store ↔ engine que usa la TUI (montar tests, guardar respuestas, estadísticas)
  importers/    adaptadores de SOLO LECTURA sobre questions/: native (JSON/TOML), apkg, anki_json (CrowdAnki)
  fetchers/     descargadores (`dgt fetch`) que escriben packs nativos en questions/ (http.py: cliente educado)
  library/      escaneo de questions/ y sincronización incremental con SQLite
  db/           esquema, migraciones (PRAGMA user_version) y consultas (store.py)
  engine/       lógica PURA del test, sin Textual ni SQLite: reglas, sesión, selección, corrección, estadísticas
  tui/          solo presentación (Textual); se importa únicamente al lanzar la TUI
  backup.py     `dgt export` / `dgt import`
  cli.py        argparse; entry point `dgt`
```

- `engine/` no importa ni `textual` ni `sqlite3`: recibe dataclasses y devuelve dataclasses, con tests
  unitarios puros.
- La BD tiene dos partes:
  - **Caché de contenido** (`sources`, `questions`): se reconstruye desde `questions/` en cualquier momento.
  - **Datos del usuario** (`sessions`, `answers`, `flags`, `saved`): referencian la `key` estable de la
    pregunta, sin FK, así que sobreviven a que cambien o desaparezcan los archivos. La sincronización
    **nunca** los toca.
- Migraciones:
  - v1 es `db/schema.sql`;
  - v2 añade `saved` («Preguntas guardadas», tecla `g`), que sustituye a la antigua marca «dudosa»
    (`flags.flagged`, ya sin uso).
- Repaso de fallos: una pregunta está pendiente si se ha fallado alguna vez y aún no lleva 3 aciertos
  seguidos (`MASTERED_STREAK`). El peso es `(1 + fallos) / (1 + racha)²`.
  - La TUI muestra «↻ repaso n/3» y «✓ sale del repaso» al conseguirlo.
  - En el examen solo se muestra tras corregir, para no revelar si se ha acertado.
- Las sesiones de estudio que se abandonan sin responder nada no cuentan (quedan como `abandoned`).

## Contrato de `questions/`

- Vacía en el repo (solo `.gitkeep`). Todo lo que se deja dentro se adopta automáticamente: al arrancar,
  al volver al menú, con la tecla `r` o con `dgt check`.
- Formato nativo `theoricum/1` en JSON o TOML (mismo esquema), con las imágenes en rutas relativas al pack:

  ```toml
  format = "theoricum/1"
  [pack]
  id = "senales-nuevas"   # opcional; si no, la ruta
  name = "Señales nuevas"
  origin = "ia"           # dgt | revista-dgt | anki | ia | otro
  date = "2026-09"
  [[questions]]
  id = "s-001"
  text = "¿Qué indica esta señal?"
  image = "img/s-001.png"
  options = ["…", "…", "…"]
  answer = "A"
  topic = "senales"
  explanation = "…"
  ```

- También se adoptan:
  - `*.apkg`/`*.colpkg` de Anki, con un sidecar opcional `<archivo>.toml` que define el mapeo de campos
    y los metadatos;
  - carpetas CrowdAnki (`deck.json`).
- Identidad estable: `key = "<pack.id>:<id>"`; en Anki, `anki:<guid>`. **No cambiar el cálculo de la
  key** sin una migración, o se pierde el historial.
- Duplicados entre fuentes: se usa `dedup`, que es el hash del texto y de las opciones normalizados. Gana
  la fuente con mayor `priority` (dgt 100 > revista-dgt 90 > anki 50 > ia 10).
- Las opciones **no se barajan**, porque hay respuestas del tipo «Ambas son correctas».

## Fuentes y reglas legales

- **Nunca se commitean preguntas, imágenes ni exports** (`questions/*`, `*.apkg`, `theoricum-*.zip`
  están en `.gitignore`).
- **Revista DGT** («Tráfico y Seguridad Vial»), con `dgt fetch revista-dgt`:
  - Los textos se pueden reproducir citando la revista como fuente.
  - Las imágenes no se pueden reproducir sin autorización: solo uso personal y privado.
  - Tests 224–278, unas 753 preguntas.
  - El código es propio. driveprep no tiene licencia, así que no se copia nada de él.
    `jorgebg/dgt-anki-flashcards` (MIT) solo sirve de referencia.
- **Mazo Anki «Carnet B»** (donmerendolo/anki-carnet-conducir): se descarga a mano en
  `questions/anki/` y es solo para uso privado. Su origen es dudoso (scrapeado de una autoescuela), así
  que **no se añade un descargador al código público**.
- **Tests oficiales de la sede DGT** (`dgt fetch dgt-web`), en `fetchers/dgt_web.py`:
  - Es una app JSF (Apache MyFaces Tobago) con sesión y solo 2–3 cuestionarios por permiso.
  - Cada paso es un POST del formulario **exterior**: Tobago anida `<form>` y el exterior lleva el token
    Secret. `javax.faces.source` indica el botón pulsado.
  - Los botones se localizan por clase o sufijo de id (nunca por `j_id_*`).
  - El flujo va directo a «finalizar examen». La corrección marca la opción buena con `…:rbrok` y
    `boton_correcta.gif`, y «Siguiente» recorre las 30 preguntas.
  - Se repiten sesiones hasta que dejan de salir preguntas nuevas.
- El usuario guarda sus preguntas y su historial con `dgt export` (un zip) en su nube privada, y los
  restaura con `dgt import`.

## Tests

- `uv run pytest`: motor, importadores (los `.apkg` v1/v2/v3 se generan en `tests/anki_builder.py`),
  sincronización, backup, descargadores (HTML sintético y HTTP falso, sin red) y TUI con Pilot.
- Para revisar el diseño sin terminal gráfica: `app.save_screenshot()` dentro de `run_test()` y
  `rsvg-convert` a PNG. Ojo: el SVG a veces se come espacios; en la terminal real salen bien.
- `examples/ejemplo.toml` es un pack demo propio (sin contenido DGT) que documenta el formato.

## Reglas del examen (permiso B)

- 30 preguntas, 30 minutos y un máximo de 3 fallos. Las preguntas en blanco cuentan como fallo. Cada
  pregunta tiene 3 opciones (A/B/C), con una sola correcta.
- Base legal: RD 818/2009. Comprobado vigente en 2026. La pregunta de vídeo anunciada en 2025 no ha
  entrado en vigor.
- Las reglas son configurables en `engine/rules.py` (`ExamRules`) por si cambian.
- Hay normas recientes que pueden dejar anticuadas las preguntas antiguas, por eso cada pregunta
  conserva su fecha y se muestra en pantalla:
  - RD 465/2025: nuevo catálogo de señales.
  - RD 518/2026: usuarios vulnerables, en vigor desde el 1-10-2026.

## textual-image: avisos

- Detecta la terminal **al importarse**, y deja de poder hacerlo cuando Textual arranca. Por eso:
  - `theoricum.tui` solo se importa al lanzar la TUI, antes de `App.run()`;
  - nunca se importa desde `export`, `import`, `check` ni `fetch`.
- No hay variable de entorno para forzar el protocolo. `--image-protocol` elige la clase concreta
  (`TGPImage`, `SixelImage`, `HalfcellImage` o `UnicodeImage`), que se inyecta en la App.
- Los modales translúcidos rompen las imágenes TGP: el tinte cambia el color de primer plano, que
  codifica el ID de la imagen. Por eso:
  - todos los `ModalScreen` llevan **fondo opaco**;
  - la paleta de comandos está desactivada;
  - no se usa `opacity`/`tint`/`:hover` en los contenedores de la imagen.
- textual-image re-codifica la imagen en cada `render()`. Se le pasan `PIL.Image` ya reescaladas, que
  `tui/images.py` guarda en una caché LRU.
- En los tests se usa `UnicodeImage`, que es determinista. `TGPImage` escribe directo a stdout.

## Textual 8: notas

- `MODES`/`SCREENS` reciben clases o callables, no instancias. Se usa `Static.content`, no `.renderable`.
- En los tests: `app.screen.query_one(...)` y `await pilot.pause()` tras cada cambio de pantalla.
  pytest-textual-snapshot no se usa, porque obliga a pytest < 9.

## Comandos de la app

```
dgt                                  panel de control
dgt exam | study [--topic T] [-n N] | review [-n N]
dgt topics | stats | saved | check
dgt fetch {revista-dgt,dgt-web} [--refresh]
dgt export [-o FILE] [--no-history] | dgt import FILE [--overwrite]
globales: --questions-dir --data-dir --image-protocol --since AAAA[-MM] --seed --version
```
