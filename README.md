# theoricum

Una TUI open source para practicar el examen teórico de la DGT (permiso B) gratis y en la terminal.

- **Examen como el real**: 30 preguntas, 30 minutos y un máximo de 3 fallos. Arriba tienes la rejilla
  del 1 al 30 y el cronómetro; abajo, la imagen a la izquierda y la pregunta a la derecha. Se corrige al
  final.
- **Estudio**: corrige cada respuesta al momento y prioriza las preguntas que aún no has visto.
- **Repaso de fallos**: solo las preguntas que has fallado, con más peso a las que fallas más a menudo.
  Una pregunta sale del repaso tras 3 aciertos seguidos.
- **Por tema**: señales, velocidad, alcohol y drogas, prioridad…
- **Estadísticas**: porcentaje de aprobados, evolución, temas flojos, cobertura del banco y una
  probabilidad estimada de aprobar.
- **Imágenes en la terminal**: en kitty usa su protocolo gráfico (TGP), en otras terminales sixel, y si
  no hay soporte gráfico, bloques Unicode.
- **Las preguntas no van en el código**: déjalas en la carpeta `questions/` y se adoptan solas. Admite
  packs JSON/TOML, mazos de Anki (`.apkg`) y carpetas CrowdAnki.
- **Copias de seguridad**: `dgt export` y `dgt import` guardan y restauran tus preguntas y tu
  historial.

El repositorio **no incluye ninguna pregunta**. Cada persona descarga o crea las suyas, por licencias y
porque las preguntas cambian con la normativa.

## Instalación

Necesitas [uv](https://docs.astral.sh/uv/). Si te falta Python 3.14, uv lo descarga solo.

```sh
git clone <url-del-repo> theoricum
cd theoricum
uv sync
uv run dgt
```

Para tener el comando `dgt` disponible en todo el sistema, usa `uv tool install .`. En ese caso la
carpeta de preguntas será `~/.local/share/theoricum/questions`, salvo que indiques otra con
`--questions-dir` o con la variable `THEORICUM_QUESTIONS`.

Las imágenes se ven mejor en una terminal con soporte gráfico:
- kitty: TGP;
- WezTerm, Konsole, foot, etc.: sixel.

En el resto de terminales se dibujan con bloques de color. Puedes forzar el método con
`--image-protocol {auto,tgp,sixel,halfcell,unicode}`.

## Conseguir preguntas

```sh
uv run dgt fetch revista-dgt   # tests de la revista «Tráfico y Seguridad Vial» de la DGT (~750 preguntas)
uv run dgt fetch dgt-web       # cuestionarios del simulador oficial de examen de la DGT
uv run dgt check               # comprueba lo que hay en questions/ y muestra avisos
```

- **Mazos de Anki**: deja el `.apkg` dentro de `questions/` y listo.
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
| `dgt check` | Sincroniza y valida `questions/` sin abrir la interfaz |
| `dgt fetch {revista-dgt,dgt-web} [--refresh]` | Descarga preguntas |
| `dgt export [-o ARCHIVO] [--no-history]` | Crea un `.zip` con tus preguntas y tu historial |
| `dgt import ARCHIVO [--overwrite]` | Restaura un `.zip` exportado; el historial se fusiona sin duplicar |

Opciones globales:

| Opción | Para qué sirve |
|---|---|
| `--questions-dir DIR` | Usar otra carpeta de preguntas |
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
| `f` | Marcar la pregunta como dudosa |
| `x` | Desactivar la pregunta para que no vuelva a salir (cuando ya ves la solución) |
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
revista > Anki > IA. Puedes cambiarla con `priority` en `[pack]`.

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
uv run dgt export                    # crea theoricum-AAAA-MM-DD.zip con questions/ y tu historial
uv run dgt import theoricum-2026-10-03.zip
```

El `.zip` contiene preguntas e imágenes con derechos de terceros. Guárdalo en tu nube privada (Mega,
Proton Drive…) y **no lo compartas públicamente**.

## Dónde se guarda todo

- **Preguntas**: `./questions/` si existe en la carpeta actual; si no, `~/.local/share/theoricum/questions`.
- **Progreso** (SQLite): `~/.local/share/theoricum/theoricum.db`.

## Fuentes y aviso legal

- **Revista «Tráfico y Seguridad Vial» (DGT)**:
  - Su aviso legal permite reproducir los textos citando la revista como fuente.
  - Prohíbe reproducir sus imágenes sin autorización por escrito.
  - `dgt fetch revista-dgt` las descarga solo para tu estudio personal y privado.
- **Simulador oficial de la DGT**: la DGT permite el uso personal y privado de sus contenidos.
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

La arquitectura y las convenciones están en [CLAUDE.md](CLAUDE.md).
- El motor (`src/theoricum/engine/`) es lógica pura sin interfaz.
- Los importadores (`importers/`) leen cada formato de preguntas.
- La biblioteca (`library/`) sincroniza `questions/` con SQLite.
- La TUI (`tui/`) usa [Textual](https://textual.textualize.io/) y
  [textual-image](https://github.com/lnqs/textual-image).

El descargador de la revista se basa en la estructura de la web, con
[jorgebg/dgt-anki-flashcards](https://github.com/jorgebg/dgt-anki-flashcards) (MIT) como referencia.

## Licencia

GPL-3.0-or-later. Consulta [LICENSE](LICENSE).
