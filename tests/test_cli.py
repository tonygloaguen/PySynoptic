from pathlib import Path

from pysynoptic.cli import main


def test_cli_displays_project_summary(tmp_path: Path, capsys: object) -> None:
    (tmp_path / "module.py").write_text(
        "def run():\n    pass\n\nclass Application:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")

    exit_code = main([str(tmp_path)])
    output = capsys.readouterr().out  # type: ignore[attr-defined]

    assert exit_code == 0
    assert f"Project: {tmp_path.name}" in output
    assert "Python files: 1" in output
    assert "Resources: 1" in output
    assert "Functions: 1" in output
    assert "Classes: 1" in output
    assert "Syntax errors: 0" in output
    assert "- module.py: 1 functions, 1 classes" in output


def test_cli_preserves_single_file_analysis(tmp_path: Path, capsys: object) -> None:
    path = tmp_path / "module.py"
    path.write_text("def run():\n    pass\n", encoding="utf-8")

    exit_code = main([str(path)])
    output = capsys.readouterr().out  # type: ignore[attr-defined]

    assert exit_code == 0
    assert f"File: {path}" in output
    assert "Functions: run" in output


def test_cli_rejects_non_python_file(tmp_path: Path, capsys: object) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("text\n", encoding="utf-8")

    exit_code = main([str(path)])
    output = capsys.readouterr().out  # type: ignore[attr-defined]

    assert exit_code == 2
    assert "expected a .py file" in output
