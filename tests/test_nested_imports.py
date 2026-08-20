from pathlib import Path

import pytest

from pysynoptic import analyze_project, analyze_python_file


def write_python(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "source",
    [
        "def run():\n    import nested_dependency\n",
        "async def run():\n    import nested_dependency\n",
        "class Container:\n    import nested_dependency\n",
        "if condition:\n    import nested_dependency\n",
        "if condition:\n    pass\nelse:\n    import nested_dependency\n",
        "try:\n    import nested_dependency\nexcept ImportError:\n    pass\n",
        "try:\n    pass\nexcept Exception:\n    import nested_dependency\n",
        "try:\n    pass\nfinally:\n    import nested_dependency\n",
        "with manager:\n    import nested_dependency\n",
        "for item in items:\n    import nested_dependency\n",
        "while condition:\n    import nested_dependency\n",
        "match value:\n    case _:\n        import nested_dependency\n",
    ],
    ids=[
        "function",
        "async-function",
        "class",
        "if",
        "else",
        "try",
        "except",
        "finally",
        "with",
        "for",
        "while",
        "match-case",
    ],
)
def test_collects_import_from_nested_scope(tmp_path: Path, source: str) -> None:
    path = write_python(tmp_path / "module.py", source)

    analysis = analyze_python_file(path)

    assert analysis.imports == ("nested_dependency",)
    assert analysis.import_references[0].module == "nested_dependency"


def test_collects_type_checking_import(tmp_path: Path) -> None:
    path = write_python(
        tmp_path / "module.py",
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from package.models import Model\n",
    )

    analysis = analyze_python_file(path)

    assert analysis.imports == ("typing.TYPE_CHECKING", "package.models.Model")


def test_collects_import_from_nested_function(tmp_path: Path) -> None:
    path = write_python(
        tmp_path / "module.py",
        "def outer():\n    def inner():\n        from package import service\n",
    )

    analysis = analyze_python_file(path)

    assert analysis.imports == ("package.service",)


def test_orders_imports_by_source_position_deterministically(tmp_path: Path) -> None:
    path = write_python(
        tmp_path / "module.py",
        "if condition:\n"
        "    import first\n"
        "def later():\n"
        "    import second\n"
        "import third\n",
    )

    first = analyze_python_file(path)
    second = analyze_python_file(path)

    assert first.imports == second.imports == ("first", "second", "third")
    assert tuple(reference.line for reference in first.import_references) == (2, 4, 5)


def test_does_not_duplicate_module_level_import(tmp_path: Path) -> None:
    path = write_python(tmp_path / "module.py", "import os\n")

    analysis = analyze_python_file(path)

    assert analysis.imports == ("os",)
    assert len(analysis.import_references) == 1


def test_creates_project_dependency_from_nested_import(tmp_path: Path) -> None:
    write_python(tmp_path / "target.py", "value = 1\n")
    write_python(
        tmp_path / "source.py",
        "def load_target():\n    import target\n",
    )

    analysis = analyze_project(tmp_path)

    assert tuple(
        (dependency.source.dotted_name, dependency.target.dotted_name)
        for dependency in analysis.dependencies
    ) == (("source", "target"),)


def test_classifies_nested_external_import(tmp_path: Path) -> None:
    write_python(
        tmp_path / "module.py",
        "try:\n    import optional_external_package\nexcept ImportError:\n    pass\n",
    )

    analysis = analyze_project(tmp_path)

    assert len(analysis.import_resolutions) == 1
    assert analysis.import_resolutions[0].status == "external"
