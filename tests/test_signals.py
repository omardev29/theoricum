import json
from io import BytesIO
from pathlib import Path

from PIL import Image

from theoricum.fetchers import signals
from theoricum.importers import ImportContext
from theoricum.importers.native import NativeImporter

from pdf_builder import Page, Row, build_catalogue_pdf

RED, GREEN, BLUE, GRAY, BLACK, ORANGE = (
    (220, 30, 30),
    (30, 180, 60),
    (30, 60, 220),
    (128, 128, 128),
    (10, 10, 10),
    (240, 140, 20),
)

PAGES = [
    Page(
        "SEÑALES DE ADVERTENCIA DE PELIGRO",
        [
            Row("P-1", ["Intersección con prioridad"], ["Peligro por una intersección."], RED),
            Row(
                "P-1c",
                ["Intersección con prioridad sobre incorporación por la", "derecha"],
                [
                    "Peligro por una incorporación por la derecha.",
                    "P-18 Obras, ya que esta línea es parte del significado.",
                ],
                GREEN,
            ),
            Row("P-2", ["Intersección con prioridad de la derecha"], ["Peligro por un"], BLUE),
        ],
    ),
    Page(
        "SEÑALES DE PRIORIDAD",
        [
            Row("R-1", ["Ceda el paso"], ["Obligación de ceder el paso."], GRAY),
            Row("R-2", ["Detención obligatoria o stop"], ["Obligación de detenerse."], BLACK),
            Row(
                "R-308d",
                ["Estacionamiento prohibido la segunda quincena"],
                ["Prohibición de estacionar del 16 al final de mes."],
                ORANGE,
            ),
        ],
        before=["cruce donde rige la prioridad de la derecha."],
    ),
]


def color_of(data: bytes) -> tuple[int, int, int]:
    image = Image.open(BytesIO(data)).convert("RGB")
    return image.getpixel((image.width // 2, image.height // 2))  # type: ignore[return-value]


def close(a: tuple[int, int, int], b: tuple[int, int, int]) -> bool:
    return all(abs(x - y) <= 12 for x, y in zip(a, b, strict=True))


def test_parse_catalogue_reads_codes_names_meanings_and_images(tmp_path: Path):
    pdf = tmp_path / "boe.pdf"
    pdf.write_bytes(build_catalogue_pdf(PAGES))
    signs, pages = signals.parse_catalogue(pdf, lambda _: None)
    assert [s.code for s in signs] == ["P-1", "P-1c", "P-2", "R-1", "R-2", "R-308d"]
    by_code = {s.code: s for s in signs}
    wrapped = by_code["P-1c"]
    assert wrapped.name == "Intersección con prioridad sobre incorporación por la derecha"
    assert wrapped.meaning.endswith("P-18 Obras, ya que esta línea es parte del significado.")
    # The meaning of the last sign of a page continues on the next one.
    assert by_code["P-2"].meaning == "Peligro por un cruce donde rige la prioridad de la derecha."
    assert by_code["R-308d"].name == "Estacionamiento prohibido la segunda quincena"
    assert by_code["P-1"].section == "SEÑALES DE ADVERTENCIA DE PELIGRO"
    assert by_code["R-2"].section == "SEÑALES DE PRIORIDAD"
    colors = [RED, GREEN, BLUE, GRAY, BLACK, ORANGE]
    for sign, color in zip(signs, colors, strict=True):
        data, suffix = signals.image_bytes(pages, sign)
        assert suffix == ".jpg" and data[:3] == b"\xff\xd8\xff"
        assert close(color_of(data), color), sign.code


def test_fetch_signals_writes_an_importable_stable_pack(tmp_path: Path, qdir: Path):
    pdf = tmp_path / "boe.pdf"
    pdf.write_bytes(build_catalogue_pdf(PAGES))
    report = signals.fetch_signals(qdir, pdf_path=pdf, log=lambda _: None)
    assert report.signs == 6 and report.questions == 6 and not report.skipped
    pack = qdir / "signals" / "pack.json"
    data = json.loads(pack.read_text(encoding="utf-8"))
    first = next(q for q in data["questions"] if q["id"] == "P-1")
    right = first["options"]["ABC".index(first["answer"])]
    assert right == "Intersección con prioridad" and len(set(first["options"])) == 3
    assert first["explanation"].startswith("P-1 · Intersección con prioridad. Peligro")
    assert (qdir / "signals" / first["image"]).is_file()

    result = NativeImporter().load(ImportContext(questions_dir=qdir, path=pack))
    assert {q.key for q in result.questions} == {
        f"signals-rd465:{code}" for code in ("P-1", "P-1c", "P-2", "R-1", "R-2", "R-308d")
    }
    assert not result.warnings
    assert all(q.topic == "senales" and q.image_ref for q in result.questions)

    again = signals.fetch_signals(qdir, pdf_path=pdf, log=lambda _: None)
    assert again.already and again.questions == 6
    regenerated = signals.fetch_signals(qdir, pdf_path=pdf, refresh=True, log=lambda _: None)
    assert regenerated.questions == 6
    same = json.loads(pack.read_text(encoding="utf-8"))["questions"]
    assert [q["options"] for q in same] == [q["options"] for q in data["questions"]]


def test_distractors_prefer_siblings_of_the_same_section():
    signs = [
        signals.Sign("P-1", "Intersección con prioridad", "A"),
        signals.Sign("P-1a", "Intersección con prioridad sobre vía a la derecha", "A"),
        signals.Sign("P-1b", "Intersección con prioridad sobre vía a la izquierda", "A"),
        signals.Sign("P-1b2", "Intersección con prioridad sobre vía a la izquierda.", "A"),
        signals.Sign("R-1", "Ceda el paso", "B"),
    ]
    assert signals.distractors(signs, 1) == [
        "Intersección con prioridad",
        "Intersección con prioridad sobre vía a la izquierda",
    ]
    assert signals.distractors(signs, 4) == []  # alone in its section
    taken = {
        signals.dedup_key(
            signals.QUESTION,
            (signs[1].name, "Intersección con prioridad", signs[2].name),
        )
    }
    # The only possible set is taken: the nearest names are used anyway (the picture tells the
    # two questions apart, see engine/pool.py).
    assert signals.distractors(signs, 2, taken) == [
        "Intersección con prioridad sobre vía a la derecha",
        "Intersección con prioridad",
    ]


def test_split_words_are_rejoined_only_when_safe():
    signs = [
        signals.Sign(
            "S-1", "Carril", "S", meaning="Cuando circula por el carril y por la derecha."
        ),
        signals.Sign("S-2", "Otro", "S", meaning="po r tanto, cu ando el ca rril de la izquierd a"),
        signals.Sign("S-3", "Otro", "S", meaning="deja de tener vigencia y se ve la izquierda."),
    ]
    signals.heal_split_words(signs)
    assert signs[1].meaning == "por tanto, cuando el carril de la izquierda"
    assert signs[2].meaning == "deja de tener vigencia y se ve la izquierda."


def test_sibling_signs_never_share_the_same_set_of_options(tmp_path: Path, qdir: Path):
    from theoricum.importers.base import dedup_key

    rows = [
        Row(f"P-{n}", [name], ["Peligro."], (20 * n, 40, 200))
        for n, name in enumerate(["Uno", "Dos", "Tres", "Cuatro"], start=1)
    ]
    pdf = tmp_path / "boe.pdf"
    pdf.write_bytes(build_catalogue_pdf([Page("SEÑALES DE ADVERTENCIA DE PELIGRO", rows)]))
    signals.fetch_signals(qdir, pdf_path=pdf, log=lambda _: None)
    data = json.loads((qdir / "signals" / "pack.json").read_text(encoding="utf-8"))
    keys = {dedup_key(q["text"], q["options"]) for q in data["questions"]}
    assert len(keys) == len(data["questions"]) == 4


def test_an_existing_pack_gets_new_settings_without_downloading_again(tmp_path: Path, qdir: Path):
    pdf = tmp_path / "boe.pdf"
    pdf.write_bytes(build_catalogue_pdf(PAGES))
    signals.fetch_signals(qdir, pdf_path=pdf, log=lambda _: None)
    pack = qdir / "signals" / "pack.json"
    data = json.loads(pack.read_text(encoding="utf-8"))
    data["pack"]["priority"] = 60  # as written by an older version
    pack.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def no_download(*args, **kwargs):
        raise AssertionError("it must not download the BOE again")

    report = signals.fetch_signals(qdir, pdf_path=None, http=no_download, log=lambda _: None)  # type: ignore[arg-type]
    assert report.already and report.meta_updated
    again = json.loads(pack.read_text(encoding="utf-8"))
    assert again["pack"]["priority"] == 95 and again["questions"] == data["questions"]
