# theoricum

[![CI](https://github.com/omardev29/theoricum/actions/workflows/ci.yml/badge.svg)](https://github.com/omardev29/theoricum/actions/workflows/ci.yml)

Una TUI open source para practicar el examen teórico de la DGT (permiso B) gratis y en la terminal.

- **Examen como el real**: 30 preguntas, 30 minutos y un máximo de 3 fallos. Arriba tienes la
  rejilla del 1 al 30 y el cronómetro; abajo, la imagen a la izquierda y la pregunta a la derecha. Se
  corrige al final. Cada examen incluye hasta 6 preguntas oficiales de la DGT que aún no dominas:
  siguen saliendo hasta que las aciertas 3 veces seguidas.
- **Estudio**: corrige cada respuesta al momento y prioriza las preguntas que aún no has visto,
  empezando por las más recientes.
- **Repaso de fallos**: solo las preguntas que has fallado, con más peso a las que fallas más a menudo.
  Una pregunta sale del repaso tras 3 aciertos seguidos; el progreso se ve como «↻ repaso 1/3».
- **Por tema**: señales, velocidad, alcohol y drogas, prioridad…
- **Preguntas guardadas**: pulsa `g` en cualquier test (también en el examen) para guardar la pregunta
  que estás viendo. Desde el menú puedes repasarlas con la solución y la explicación, o estudiarlas
  todas de golpe.
- **Estadísticas**: porcentaje de aprobados, evolución, temas flojos, cobertura del banco y una
  probabilidad estimada de aprobar.
- **Imágenes en la terminal, lo más nítidas posible**: en kitty usa su protocolo gráfico (TGP); en
  foot, Windows Terminal, WezTerm o Konsole, Sixel; y si no hay soporte gráfico, bloques de color.
  Pulsa `z` para ver la imagen a pantalla completa.
- **Preguntas fiables**: avisa de las preguntas que pueden haber quedado anticuadas por un cambio
  de norma (por ejemplo, la baliza V-16) y no las pone en el examen; si dos fuentes dan respuestas
  distintas a la misma pregunta, usa la más reciente y te lo cuenta.
- **Linux, macOS y Windows** (nativo, sin WSL).
- **Las preguntas no van en el código**: déjalas en `~/Questions` (o en una carpeta `questions/`
  del directorio donde lo ejecutes) y se adoptan solas. Admite packs JSON/TOML, mazos de Anki
  (`.apkg`) y carpetas CrowdAnki.
- **Copias de seguridad**: `dgt export` y `dgt import` guardan y restauran tus preguntas y tu
  historial.

El repositorio **no incluye ninguna pregunta**. Cada persona descarga o crea las suyas, por licencias y
porque las preguntas cambian con la normativa.

## Instalación

Necesitas [uv](https://docs.astral.sh/uv/) 0.9.0 o posterior (sirve el de Scoop, el de pacman, el de
Homebrew o el instalador oficial; para actualizarlo: `scoop update uv`, `sudo pacman -Syu uv`,
`brew upgrade uv` o `uv self update`). No hace falta instalar Python:
theoricum usa siempre su propio Python 3.14, gestionado por uv, y no el de tu sistema, así que
funciona igual en Linux, macOS y Windows.

La forma más cómoda es instalar el comando `dgt` para todo el sistema:

```sh
uv tool install --managed-python git+https://github.com/omardev29/theoricum
dgt
```

Para actualizarlo, `uv tool upgrade theoricum`. Si prefieres trabajar desde una copia del
repositorio:

```sh
git clone https://github.com/omardev29/theoricum
cd theoricum
uv run dgt                             # sin instalar nada
uv tool install --managed-python .     # o instala el comando dgt desde la copia
uv tool install --managed-python -e .  # o hazlo «editable»: dgt sigue los cambios del código
```

### Windows

1. Instala uv desde PowerShell:

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   # o con scoop
   scoop install uv
   ```

2. Instala y arranca la app:

   ```powershell
   uv tool install --managed-python git+https://github.com/omardev29/theoricum
   dgt
   ```

Funciona en Windows de forma nativa, sin WSL. Usa **Windows Terminal 1.22 o posterior**, que dibuja
las imágenes con Sixel; la consola clásica o un Windows Terminal más antiguo las muestran con bloques
de color. Tus preguntas van en `%USERPROFILE%\Questions` y tu progreso en `%LOCALAPPDATA%\theoricum`.

### Dónde busca las preguntas

`dgt` usa dos carpetas a la vez, estés donde estés:

1. **`questions/` en el directorio donde lo ejecutas** (la carpeta local), si existe;
2. **`Questions/` en tu carpeta personal** (la global): `~/Questions` en Linux y macOS,
   `%USERPROFILE%\Questions` en Windows.

Da igual cómo escribas los nombres: `Questions`, `questions` o `qUestions` valen. Si el mismo archivo
(por ejemplo, `revista-dgt/pack.json`) está en las dos, se usa el de la carpeta local y no se duplica
nada. `dgt check` te enseña qué carpetas usa.

- `--no-local` ignora la carpeta local y `--no-global`, la global.
- `--questions-dir DIR` (o la variable `THEORICUM_QUESTIONS`) usa solo esa carpeta.
- `dgt import` y `dgt fetch` guardan lo nuevo en la carpeta local si existe y, si no, en
  `~/Questions` (que se crea sola). Con `--into DIR` eliges otra. Si ya tienes una fuente
  descargada, `dgt fetch` la actualiza en la carpeta donde esté.

Puedes mover un pack de una carpeta a otra cuando quieras: tu historial no cambia.

Si instalaste una versión anterior, tus preguntas pueden estar aún en la carpeta antigua
(`~/.local/share/theoricum/questions` en Linux). Se siguen usando mientras no exista `~/Questions`, y
`dgt check` te recuerda que puedes moverlas.

### Imágenes

Las imágenes son importantes en el teórico, así que se ven lo mejor que permite cada terminal:
- **kitty**: protocolo gráfico TGP, a color completo;
- **foot, Windows Terminal ≥ 1.22, WezTerm, Konsole…**: Sixel, con *dithering* para que los
  degradados no se vean a manchas;
- en el resto, bloques de color.

Casi todas las imágenes de las fuentes son pequeñas (las de la revista miden 250×226 px), así que se
amplían con un filtro Lanczos y un enfoque suave. Pulsa **`z`** en cualquier pregunta para verla a
pantalla completa (también en el examen, sin parar el reloj). En Windows Terminal es lo que más
ayuda, porque dibuja Sixel en celdas virtuales de 10×20 px: cuantas más celdas ocupe la imagen,
más detalle.

La ayuda (`?`) muestra qué método se está usando. Si ves bloques de color en una terminal con
gráficos, fuerza el método con `--image-protocol {auto,tgp,sixel,halfcell,unicode}` o déjalo fijo
con la variable `THEORICUM_IMAGE_PROTOCOL`.

## Conseguir preguntas

```sh
dgt fetch revista-dgt   # tests de la revista «Tráfico y Seguridad Vial» de la DGT (~770 preguntas)
dgt fetch dgt-web       # cuestionarios del simulador oficial de examen de la DGT
dgt fetch signals       # «¿Qué indica esta señal?» con el catálogo oficial (455 señales)
dgt fetch anki          # mazo de la comunidad «Carnet B» (~2.950 preguntas, 177 MB)
dgt check               # comprueba tus carpetas de preguntas y muestra avisos
```

- **Revista DGT**: descarga del test más nuevo al más antiguo, así que si lo cortas ya tienes lo
  último. Con `--last 8` solo baja los 8 tests más recientes. Vuelve a ejecutarlo de vez en cuando:
  solo descarga los tests nuevos.
- **Señales**: se generan a partir del catálogo oficial de señales del Real Decreto 465/2025,
  publicado en el BOE. La respuesta correcta es el nombre oficial de la señal, la explicación es su
  significado oficial y las opciones incorrectas son señales parecidas de la misma familia (por
  ejemplo, «… a la derecha» frente a «… a la izquierda»).
- **Anki «Carnet B»**: descarga la última versión publicada del mazo
  [donmerendolo/anki-carnet-conducir](https://github.com/donmerendolo/anki-carnet-conducir)
  (GPL-3.0) en `anki/`, con sus ajustes. Si ya lo tienes, solo lo vuelve a bajar cuando sale una
  versión nueva; si pusiste tú un mazo distinto con el mismo nombre, no lo toca sin `--refresh`.
  Su autor indica que las preguntas salen de la web de una autoescuela: úsalo solo para estudiar.

(Si trabajas desde una copia del repositorio sin instalar el comando, antepón `uv run`: `uv run dgt
fetch revista-dgt`.)

- **Otros mazos de Anki**: deja el `.apkg` en tu carpeta de preguntas y listo.
  - Se reconocen solos los mazos tipo test hechos con el complemento *anki-mc*, que tienen los campos
    `Question`, `Q_1…Q_n` y `Answers`.
  - También se reconocen los mazos con campos llamados pregunta/a/b/c/respuesta o similares.
  - Si el tuyo no se reconoce, `dgt check` te lo dirá y podrás indicar el mapeo en un archivo `.toml` al
    lado del mazo (ver más abajo).
- **Tus propias preguntas**: escríbelas en JSON o TOML con el formato de `examples/ejemplo.toml`.

## Uso

| Comando | Qué hace |
|---|---|
| `dgt` | Abre el panel de control |
| `dgt exam` | Examen: 30 preguntas, 30 minutos, máximo 3 fallos |
| `dgt study [--topic TEMA] [-n N]` | Estudio con corrección inmediata, opcionalmente de un solo tema |
| `dgt review [-n N]` | Repaso de fallos |
| `dgt topics` | Lista los temas y cuántas preguntas tiene cada uno |
| `dgt stats` | Abre las estadísticas |
| `dgt saved` | Abre tus preguntas guardadas |
| `dgt check` | Sincroniza y valida tus carpetas de preguntas sin abrir la interfaz |
| `dgt fetch {revista-dgt,dgt-web,signals,anki} [--refresh] [--into DIR]` | Descarga preguntas (`--last N`: solo los N tests más recientes de la revista) |
| `dgt export [-o ARCHIVO] [--no-history]` | Crea un `.zip` con tus preguntas y tu historial |
| `dgt import ARCHIVO [--overwrite]` | Restaura un `.zip` exportado; el historial se fusiona sin duplicar |

Opciones globales:

| Opción | Para qué sirve |
|---|---|
| `--questions-dir DIR` | Usar solo esta carpeta de preguntas |
| `--no-local` | No usar la carpeta `questions/` del directorio actual |
| `--no-global` | No usar la carpeta global `~/Questions` |
| `--data-dir DIR` | Usar otra carpeta para el progreso |
| `--image-protocol P` | Elegir cómo se dibujan las imágenes |
| `--since AAAA[-MM]` | Usar solo preguntas con fecha igual o posterior |
| `--seed N` | Repetir la misma selección de preguntas |

Los temas no distinguen tildes: `--topic señales` es lo mismo que `--topic senales`.

### Teclas del test

| Tecla | Acción |
|---|---|
| `a` `b` `c` | Responder (también con el ratón) |
| `←` `→` | Pregunta anterior / siguiente (también con clic en la rejilla) |
| `Enter` | Examen: entregar · Estudio: siguiente |
| `g` | Guardar la pregunta en «Preguntas guardadas» (o quitarla) |
| `x` | Desactivar la pregunta para que no vuelva a salir (cuando ya ves la solución) |
| `z` | Ver la imagen a pantalla completa |
| `r` | Tras corregir: repasar ahora las falladas |
| `Esc` | Salir |
| `?` | Ayuda |

## Formato de las preguntas (`questions/`)

Todo lo que dejes en `questions/` se adopta automáticamente:
- al arrancar;
- al volver al menú;
- al pulsar `r` en el menú;
- al ejecutar `dgt check`.

Puedes organizarlo en subcarpetas como quieras; las carpetas y archivos ocultos se ignoran.

Un pack nativo es un `.json` o `.toml` con `format = "theoricum/1"`:

```toml
format = "theoricum/1"

[pack]
id = "senales-nuevas"      # identificador estable (no lo cambies o perderás el historial)
name = "Señales nuevas"
origin = "ia"              # dgt | revista-dgt | anki | ia | otro
date = "2026-09"           # fecha de la pregunta o de su revisión

[[questions]]
id = "s-001"
text = "¿Qué indica esta señal?"
image = "img/s-001.png"    # relativa al archivo del pack
options = ["…", "…", "…"]  # de 2 a 4 opciones; no se barajan
answer = "A"
topic = "senales"          # opcional; si falta, se deduce del texto
explanation = "…"          # opcional; se ve en estudio y al revisar
```

**Duplicados.** Si la misma pregunta está en varias fuentes, se usa la de mayor prioridad: DGT oficial >
señales del BOE > revista > Anki > IA. La prioridad solo decide qué copia se usa, no cuántas veces
sale. Puedes cambiarla con `priority` en `[pack]`. Si las fuentes no
coinciden en la respuesta, gana la de fecha más reciente, porque la norma ha podido cambiar, y al
corregir se indica qué decía la otra.

**Preguntas anticuadas.** La normativa cambia: desde el 1-1-2026 la baliza V-16 sustituye a los
triángulos, en 2021 cambiaron los límites en ciudad, en 2025 llegó un nuevo catálogo de señales… Las
preguntas anteriores a un cambio que hablan de lo que cambió llevan la marca «⚠ posible anticuada»,
no salen en el examen y, al corregir, explican el cambio con la norma que lo establece. La lista de
cambios está en `src/theoricum/data/changes.toml`. `dgt check` cuenta cuántas hay.

**Mazos de Anki.** Un archivo opcional con el mismo nombre más `.toml` (por ejemplo
`mazo.apkg.toml`) permite fijar metadatos y el mapeo de campos:

```toml
source = "https://…"          # se muestra como fuente de cada pregunta

[pack]
name = "Mi mazo"
date = "2025-02"
priority = 50
exclude_topics = ["senales"]  # no usar las preguntas de estos temas

[fields]                      # solo si el mazo no se reconoce solo
question = "Pregunta"
options = ["A", "B", "C"]
answer = "Correcta"
answer_format = "letter"      # bitmask | letter | index | text
image = "Imagen"
explanation = "Explicación"

[clean]
strip_suffix = ["texto basura al final de la explicación"]
```

## Copias de seguridad

```sh
dgt export                    # crea theoricum-AAAA-MM-DD.zip con tus preguntas y tu historial
dgt import theoricum-2026-10-03.zip
dgt import theoricum-2026-10-03.zip --into ~/Questions   # elige dónde dejar las preguntas
```

El `.zip` sirve en cualquier sistema: puedes exportarlo en Linux e importarlo en Windows o macOS (o al
revés) sin perder el historial. El export junta tus dos carpetas tal y como las ve la app; el import
deja lo nuevo en la carpeta local si existe y si no en `~/Questions`, y no copia lo que ya tienes.

El `.zip` contiene preguntas e imágenes con derechos de terceros. Guárdalo en tu nube privada (Mega,
Proton Drive…) y **no lo compartas públicamente**.

## Dónde se guarda todo

- **Preguntas**: `questions/` en el directorio actual y `~/Questions` (ver «Dónde busca las
  preguntas»).
- **Progreso, incluidas las preguntas guardadas** (SQLite): `theoricum.db` en la carpeta de datos.
- **Carpeta de datos**:
  - Linux: `~/.local/share/theoricum`;
  - Windows: `%LOCALAPPDATA%\theoricum`;
  - macOS: `~/Library/Application Support/theoricum`.

## Fuentes y aviso legal

- **Revista «Tráfico y Seguridad Vial» (DGT)**:
  - Su aviso legal permite reproducir los textos citando la revista como fuente.
  - Prohíbe reproducir sus imágenes sin autorización por escrito.
  - `dgt fetch revista-dgt` las descarga solo para tu estudio personal y privado.
- **Simulador oficial de la DGT**: la DGT permite el uso personal y privado de sus contenidos.
- **Catálogo oficial de señales (BOE, RD 465/2025)**: los textos legales no tienen derechos de
  autor (art. 13 de la Ley de Propiedad Intelectual) y el BOE permite reutilizar sus contenidos
  citando la fuente. Aun así, las preguntas generadas se quedan en tu carpeta de preguntas.
- **Mazos de Anki y otras fuentes**: respeta sus licencias y su procedencia.
- **Vigencia de las preguntas**: la normativa cambia y las preguntas antiguas pueden quedar mal; por
  ejemplo, el RD 465/2025 trajo un nuevo catálogo de señales y el RD 518/2026 está en vigor desde el
  1-10-2026. Cada pregunta muestra su fuente y su fecha, y puedes filtrar con `--since` o desactivar
  preguntas con `x`.

Este proyecto no está afiliado a la DGT.

## Desarrollo

```sh
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
```

La integración continua (GitHub Actions) pasa los tests en Linux, Windows y macOS.

La arquitectura y las convenciones están en [CLAUDE.md](CLAUDE.md), en inglés, para quien
desarrolle y para los agentes de IA. Lo más importante: el formato de las preguntas, sus claves y
las copias de seguridad no se rompen nunca. Lo vigilan los tests de contrato
(`tests/test_contract.py`).
- El motor (`src/theoricum/engine/`) es lógica pura sin interfaz.
- Los importadores (`importers/`) leen cada formato de preguntas.
- La biblioteca (`library/`) sincroniza `questions/` con SQLite.
- La TUI (`tui/`) usa [Textual](https://textual.textualize.io/) y
  [textual-image](https://github.com/lnqs/textual-image).

El descargador de la revista se basa en la estructura de la web, con
[jorgebg/dgt-anki-flashcards](https://github.com/jorgebg/dgt-anki-flashcards) (MIT) como referencia.

## Licencia

GPL-3.0-or-later. Consulta [LICENSE](LICENSE).
