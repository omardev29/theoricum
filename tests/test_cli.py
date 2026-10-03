from pathlib import Path

from theoricum.cli import build_parser, main

from conftest import make_questions, write_pack


def args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--questions-dir",
        str(tmp_path / "questions"),
        "--data-dir",
        str(tmp_path / "data"),
        *extra,
    ]


def test_check_topics_export_import(tmp_path: Path, capsys, monkeypatch):
    write_pack(tmp_path / "questions" / "p.json", make_questions(5, topic="velocidad"), {"id": "p"})
    assert main([*args(tmp_path), "check"]) == 0
    out = capsys.readouterr().out
    assert "✓ p.json" in out and "Banco activo: 5 preguntas" in out

    assert main([*args(tmp_path), "topics"]) == 0
    assert "velocidad" in capsys.readouterr().out

    monkeypatch.chdir(tmp_path)
    assert main([*args(tmp_path), "export", "-o", str(tmp_path / "copia.zip")]) == 0
    assert (tmp_path / "copia.zip").is_file()

    other = tmp_path / "other"
    other.mkdir()
    rc = main(
        [
            "--questions-dir",
            str(other / "q"),
            "--data-dir",
            str(other / "d"),
            "import",
            str(tmp_path / "copia.zip"),
        ]
    )
    assert rc == 0
    assert "archivos de preguntas nuevos: 1" in capsys.readouterr().out
    assert (other / "q" / "p.json").is_file()


def test_check_reports_errors_with_exit_code(tmp_path: Path, capsys):
    (tmp_path / "questions").mkdir()
    (tmp_path / "questions" / "roto.toml").write_text('format = "theoricum/1"\n[', encoding="utf-8")
    assert main([*args(tmp_path), "check"]) == 1
    assert "✗ roto.toml" in capsys.readouterr().out


def test_parser_accepts_global_flags_after_command():
    ns = build_parser().parse_args(["study", "--topic", "señales", "-n", "10", "--seed", "3"])
    assert (ns.command, ns.topic, ns.n, ns.seed) == ("study", "señales", 10, 3)
    ns = build_parser().parse_args(["--image-protocol", "unicode", "exam"])
    assert ns.image_protocol == "unicode" and ns.command == "exam"
