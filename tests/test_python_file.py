from pathlib import Path

import pytest

from pysynoptic.analyzer import analyze_python_file


def write_python_file(tmp_path: Path, source: str, name: str = "sample.py") -> Path:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


def test_analyzes_valid_python_file(tmp_path: Path) -> None:
    path = write_python_file(tmp_path, "value = 42\n")

    analysis = analyze_python_file(path)

    assert analysis.path == path
    assert analysis.module_name == "sample"
    assert analysis.syntax_error is None


def test_collects_top_level_functions_including_async(tmp_path: Path) -> None:
    path = write_python_file(
        tmp_path,
        "def first():\n    pass\n\nasync def second():\n    pass\n",
    )

    analysis = analyze_python_file(path)

    assert analysis.functions == ("first", "second")


def test_collects_only_top_level_classes(tmp_path: Path) -> None:
    path = write_python_file(
        tmp_path,
        "class Public:\n    class Nested:\n        pass\n",
    )

    analysis = analyze_python_file(path)

    assert analysis.classes == ("Public",)


def test_collects_import_statements(tmp_path: Path) -> None:
    path = write_python_file(tmp_path, "import os\nimport sys as system\n")

    analysis = analyze_python_file(path)

    assert analysis.imports == ("os", "sys")


def test_collects_from_import_statements(tmp_path: Path) -> None:
    path = write_python_file(
        tmp_path,
        "from pathlib import Path\nfrom .helpers import one, two as second\n",
    )

    analysis = analyze_python_file(path)

    assert analysis.imports == ("pathlib.Path", ".helpers.one", ".helpers.two")


def test_analyzes_empty_file(tmp_path: Path) -> None:
    path = write_python_file(tmp_path, "")

    analysis = analyze_python_file(path)

    assert analysis.functions == ()
    assert analysis.classes == ()
    assert analysis.imports == ()
    assert analysis.syntax_error is None


def test_returns_syntax_error_instead_of_raising(tmp_path: Path) -> None:
    path = write_python_file(tmp_path, "def broken(:\n    pass\n")

    analysis = analyze_python_file(path)

    assert analysis.syntax_error is not None
    assert "line 1" in analysis.syntax_error
    assert analysis.functions == ()


def test_rejects_missing_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.py"

    with pytest.raises(FileNotFoundError, match="Python file not found"):
        analyze_python_file(missing_path)


def test_rejects_non_python_extension(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("def valid():\n    pass\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"expected a \.py file"):
        analyze_python_file(path)


def test_never_executes_analyzed_source(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    path = write_python_file(
        tmp_path,
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
    )

    analyze_python_file(path)

    assert not marker.exists()
