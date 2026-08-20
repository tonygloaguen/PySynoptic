from pathlib import Path

import pytest

from pysynoptic.cli import main


def test_cli_displays_project_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "module.py").write_text(
        "def run():\n    pass\n\nclass Application:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")

    exit_code = main([str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Project: {tmp_path.name}" in output
    assert "Python files: 1" in output
    assert "Resources: 1" in output
    assert "Functions: 1" in output
    assert "Classes: 1" in output
    assert "Syntax errors: 0" in output
    assert "- module\n  module.py" in output


def test_cli_preserves_single_file_analysis(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "module.py"
    path.write_text("def run():\n    pass\n", encoding="utf-8")

    exit_code = main([str(path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"File: {path}" in output
    assert "Functions: run" in output


def test_cli_rejects_non_python_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("text\n", encoding="utf-8")

    exit_code = main([str(path)])
    output = capsys.readouterr().out

    assert exit_code == 2
    assert "expected a .py file" in output


def test_cli_displays_resolved_dependencies(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "target.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "source.py").write_text("import target\n", encoding="utf-8")

    exit_code = main([str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Dependencies: 1" in output
    assert "- source -> target" in output


def test_cli_renders_mermaid_to_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "module.py").write_text("value = 1\n", encoding="utf-8")

    exit_code = main([str(tmp_path), "--format", "mermaid"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert output == 'flowchart LR\n  module_module["module"]\n'


def test_cli_writes_mermaid_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "module.py").write_text("value = 1\n", encoding="utf-8")
    output_path = tmp_path / "docs" / "dependencies.mmd"

    exit_code = main(
        [str(tmp_path), "--format", "mermaid", "--output", str(output_path)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert output_path.read_text(encoding="utf-8") == (
        'flowchart LR\n  module_module["module"]\n'
    )
    assert f"Wrote Mermaid graph to {output_path}" in output


def test_cli_rejects_mermaid_for_single_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "module.py"
    path.write_text("value = 1\n", encoding="utf-8")

    exit_code = main([str(path), "--format", "mermaid"])
    output = capsys.readouterr().out

    assert exit_code == 2
    assert "Mermaid output requires a project directory" in output
