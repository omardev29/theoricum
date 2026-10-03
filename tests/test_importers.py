import json
from pathlib import Path

import pytest

from theoricum.importers import ImportContext
from theoricum.importers.anki_json import CrowdAnkiImporter
from theoricum.importers.apkg import ApkgImporter
from theoricum.importers.base import dedup_key, html_to_text, image_sources, strip_number_prefix
from theoricum.importers.native import NativeImporter
from theoricum.media import MediaResolver

from anki_builder import FakeNote, FakeNotetype, anki_mc_deck, build_apkg

PNG = b"\x89PNG\r\n\x1a\nfake-image-bytes"


def load(importer, qdir: Path, path: Path):
    assert importer.detect(path)
    return importer.load(ImportContext(questions_dir=qdir, path=path))


# --- helpers -----------------------------------------------------------------------------------


def test_html_helpers():
    assert html_to_text("Hola&nbsp;<b>mundo</b><br>adiós [sound:x.mp3]") == "Hola mundo\nadiós"
    assert image_sources('<div><img class="x" src="a&amp;b.png"></div><img src=c.jpg>') == [
        "a&b.png",
        "c.jpg",
    ]
    assert strip_number_prefix("12. ¿Qué?") == "¿Qué?"
    assert strip_number_prefix("A) Sí") == "Sí"
    assert strip_number_prefix("1.5 metros") == "1.5 metros"
    assert strip_number_prefix("A la derecha") == "A la derecha"


def test_dedup_ignores_accents_punctuation_and_option_order():
    a = dedup_key("¿Qué indica esta señal?", ["Prohibido", "Obligatorio", "Fin"])
    b = dedup_key("Que indica esta senal", ["fin", "obligatorio.", "PROHIBIDO"])
    assert a == b
    assert a != dedup_key("¿Qué indica esta señal?", ["Prohibido", "Obligatorio", "Otro"])


# --- native ------------------------------------------------------------------------------------


def test_native_toml_pack(qdir: Path):
    (qdir / "img").mkdir()
    (qdir / "img" / "s1.png").write_bytes(PNG)
    path = qdir / "mias.toml"
    path.write_text(
        """
format = "theoricum/1"
[pack]
id = "mias"
origin = "ia"
date = 2026-09-01
topic = "Señales"

[[questions]]
id = "s-1"
text = "¿Qué indica?"
image = "img/s1.png"
options = ["Uno", "Dos", "Tres"]
answer = "b"
explanation = "Porque sí."

[[questions]]
id = "s-2"
text = "Mal"
options = ["Uno", "Dos"]
answer = "C"

[[questions]]
text = "Sin id"
options = ["Uno", "Dos"]
answer = "A"
image = "../fuera.png"
""",
        encoding="utf-8",
    )
    result = load(NativeImporter(), qdir, path)
    assert (
        result.meta.origin == "ia"
        and result.meta.date == "2026-09-01"
        and result.meta.topic == "senales"
    )
    assert [q.key for q in result.questions] == ["mias:s-1", "mias:q3"]
    first = result.questions[0]
    assert (
        first.answer == 1
        and first.image_ref == "file:img/s1.png"
        and first.explanation == "Porque sí."
    )
    joined = "\n".join(result.warnings)
    assert "questions[1].answer: «C» no existe (2 opciones)" in joined
    assert "questions[2].id: falta" in joined
    assert "sale de la carpeta" in joined


def test_native_json_and_detection(qdir: Path):
    path = qdir / "p.json"
    path.write_text(json.dumps({"format": "theoricum/1", "questions": []}), encoding="utf-8")
    other = qdir / "other.json"
    other.write_text('{"hello": 1}', encoding="utf-8")
    assert NativeImporter().detect(path) and not NativeImporter().detect(other)
    result = load(NativeImporter(), qdir, path)
    assert result.questions == [] and "no tiene preguntas" in result.warnings[0]


# --- apkg --------------------------------------------------------------------------------------


@pytest.mark.parametrize("version", [1, 2, 3])
def test_apkg_all_versions(qdir: Path, tmp_path: Path, version: int):
    notetypes, notes = anki_mc_deck()
    path = build_apkg(
        qdir / f"deck{version}.apkg",
        version=version,
        notetypes=notetypes,
        notes=notes,
        media={"señal 1.png": PNG},
        tmp=tmp_path,
    )
    (qdir / f"deck{version}.apkg.toml").write_text(
        '[pack]\nname = "Mazo"\ndate = "2025-02"\n[clean]\nstrip_suffix = ["¿Crees que la respuesta es incorrecta?"]\n',
        encoding="utf-8",
    )
    importer = ApkgImporter()
    assert importer.related_files(path) == [qdir / f"deck{version}.apkg.toml"]
    result = load(importer, qdir, path)
    by_key = {q.key: q for q in result.questions}
    assert set(by_key) == {"anki:guid-mc-1", "anki:guid-mc-2", "anki:guid-basic-1"}

    mc1 = by_key["anki:guid-mc-1"]
    assert mc1.text == "¿Qué indica esta señal?"
    assert mc1.options == ("Prohibido adelantar", "Fin de prohibición", "Calzada con prioridad")
    assert mc1.answer == 1
    assert mc1.explanation == "Porque sí."
    assert mc1.topic == "senales" and mc1.date == "2025-02"
    assert MediaResolver(qdir).read(mc1.image_ref) == PNG

    mc2 = by_key["anki:guid-mc-2"]
    assert mc2.options == ("100 km/h", "120 km/h") and mc2.answer == 1 and mc2.image_ref is None

    basic = by_key["anki:guid-basic-1"]
    assert basic.text == "¿Qué hacer ante un accidente?"
    assert basic.options == ("Huir", "Proteger, avisar y socorrer", "Nada") and basic.answer == 1
    assert basic.topic == "accidentes"  # from the deck name DGT::Accidentes

    joined = "\n".join(result.warnings)
    assert "sin una única respuesta correcta" in joined
    assert "cloze" in joined
    assert result.meta.name == "Mazo" and result.meta.origin == "anki"


def test_apkg_sidecar_field_mapping(qdir: Path, tmp_path: Path):
    nt = FakeNotetype(5, "Raro", ["Enunciado raro", "Op1", "Op2", "Op3", "Buena", "Foto"])
    notes = [FakeNote("g1", "Raro", ["¿Sí o no?", "Sí", "No", "Quizá", "No", '<img src="x.png">'])]
    path = build_apkg(
        qdir / "raro.apkg",
        version=1,
        notetypes=[nt],
        notes=notes,
        media={"x.png": PNG},
        tmp=tmp_path,
    )
    (qdir / "raro.apkg.toml").write_text(
        '[fields]\nquestion = "Enunciado raro"\noptions = ["Op1", "Op2", "Op3"]\nanswer = "Buena"\n'
        'answer_format = "text"\nimage = "Foto"\n',
        encoding="utf-8",
    )
    (q,) = load(ApkgImporter(), qdir, path).questions
    assert q.answer == 1 and q.image_ref is not None


def test_apkg_unknown_notetype_warns(qdir: Path, tmp_path: Path):
    nt = FakeNotetype(5, "Raro", ["Uno", "Dos"])
    path = build_apkg(
        qdir / "raro.apkg",
        version=1,
        notetypes=[nt],
        notes=[FakeNote("g", "Raro", ["a", "b"])],
        tmp=tmp_path,
    )
    result = load(ApkgImporter(), qdir, path)
    assert result.questions == [] and "no sé leer el tipo de nota «Raro»" in result.warnings[0]


# --- CrowdAnki ---------------------------------------------------------------------------------


def test_crowdanki_deck(qdir: Path):
    deck_dir = qdir / "crowd"
    (deck_dir / "media").mkdir(parents=True)
    (deck_dir / "media" / "s.png").write_bytes(PNG)
    deck = {
        "__type__": "Deck",
        "name": "DGT",
        "note_models": [
            {
                "crowdanki_uuid": "m1",
                "name": "MC",
                "type": 0,
                "flds": [
                    {"name": "Pregunta", "ord": 0},
                    {"name": "A", "ord": 1},
                    {"name": "B", "ord": 2},
                    {"name": "C", "ord": 3},
                    {"name": "Respuesta", "ord": 4},
                    {"name": "Imagen", "ord": 5},
                ],
            },
        ],
        "notes": [],
        "children": [
            {
                "__type__": "Deck",
                "name": "Velocidad",
                "notes": [
                    {
                        "__type__": "Note",
                        "guid": "c1",
                        "note_model_uuid": "m1",
                        "tags": [],
                        "fields": [
                            "¿Máxima en autopista?",
                            "90",
                            "120",
                            "150",
                            "B",
                            '<img src="s.png">',
                        ],
                    },
                ],
                "children": [],
            }
        ],
    }
    path = deck_dir / "deck.json"
    path.write_text(json.dumps(deck), encoding="utf-8")
    result = load(CrowdAnkiImporter(), qdir, path)
    (q,) = result.questions
    assert q.key == "anki:c1" and q.answer == 1 and q.topic == "velocidad"
    assert q.image_ref == "file:crowd/media/s.png"
    assert result.meta.name == "DGT"
