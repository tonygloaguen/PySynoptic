from pathlib import Path

from pysynoptic import analyze_python_file
from pysynoptic.models import ImportReference


def write_python(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "module.py"
    path.write_text(source, encoding="utf-8")
    return path


def test_extracts_structured_import_metadata(tmp_path: Path) -> None:
    path = write_python(
        tmp_path, "import os\nimport package.module as imported_module\n"
    )

    analysis = analyze_python_file(path)

    assert analysis.import_references == (
        ImportReference("import", "os", None, None, 0, 1, 0),
        ImportReference("import", "package.module", None, "imported_module", 0, 2, 0),
    )


def test_extracts_from_import_names_and_aliases(tmp_path: Path) -> None:
    path = write_python(
        tmp_path,
        "from package.module import First as Renamed, Second\n",
    )

    analysis = analyze_python_file(path)

    assert analysis.import_references == (
        ImportReference("from", "package.module", "First", "Renamed", 0, 1, 0),
        ImportReference("from", "package.module", "Second", None, 0, 1, 0),
    )


def test_extracts_relative_import_levels(tmp_path: Path) -> None:
    path = write_python(
        tmp_path,
        "from . import sibling\nfrom ..shared import helper as imported_helper\n",
    )

    analysis = analyze_python_file(path)

    assert analysis.import_references == (
        ImportReference("from", None, "sibling", None, 1, 1, 0),
        ImportReference("from", "shared", "helper", "imported_helper", 2, 2, 0),
    )


def test_preserves_legacy_import_strings(tmp_path: Path) -> None:
    path = write_python(
        tmp_path,
        "import os as operating_system\nfrom .helpers import one as first\n",
    )

    analysis = analyze_python_file(path)

    assert analysis.imports == ("os", ".helpers.one")


def test_syntax_error_has_no_import_metadata(tmp_path: Path) -> None:
    path = write_python(tmp_path, "from package import (\n")

    analysis = analyze_python_file(path)

    assert analysis.syntax_error is not None
    assert analysis.import_references == ()
