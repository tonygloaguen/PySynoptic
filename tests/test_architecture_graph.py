from pathlib import Path

from pysynoptic import analyze_project
from pysynoptic.graph import (
    architecture_roots,
    build_contextual_architecture_graph,
    build_cycle_architecture_graph,
    module_details,
    search_architecture_roots,
)


def write_python(path: Path, source: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def sample_analysis(tmp_path: Path):
    write_python(tmp_path / "package" / "__init__.py")
    write_python(tmp_path / "package" / "a.py", "from package import b\n")
    write_python(tmp_path / "package" / "b.py", "from package import a\n")
    write_python(tmp_path / "entry.py", "from package import a\n")
    return analyze_project(tmp_path)


def root_named(analysis, name: str):
    return next(root for root in architecture_roots(analysis) if root.label == name)


def test_defaults_to_both_depth_one_and_keeps_edge_direction(tmp_path: Path) -> None:
    analysis = sample_analysis(tmp_path)
    root = root_named(analysis, "package.a")

    result = build_contextual_architecture_graph(analysis, root)
    labels = {node.label for node in result.graph.nodes}

    assert result.direction == "both"
    assert result.depth == 1
    assert {"entry", "package.a", "package.b"} <= labels
    assert {edge.label for edge in result.graph.edges} == {"imports"}


def test_search_depth_and_cycle_only_are_deterministic(tmp_path: Path) -> None:
    analysis = sample_analysis(tmp_path)

    assert [root.label for root in search_architecture_roots(analysis, "A")] == [
        "package",
        "package.a",
        "package.b",
    ]
    first = build_cycle_architecture_graph(analysis)
    second = build_cycle_architecture_graph(analysis)

    assert first == second
    assert {node.label for node in first.nodes} == {"package.a", "package.b"}
    assert all(node.cyclic for node in first.nodes)


def test_module_details_expose_imports_symbols_and_cycle(tmp_path: Path) -> None:
    write_python(
        tmp_path / "package" / "a.py",
        (
            "import json\n"
            "from package import b\n"
            "def run():\n    pass\n"
            "class Item:\n    pass\n"
        ),
    )
    write_python(tmp_path / "package" / "__init__.py")
    write_python(tmp_path / "package" / "b.py", "from package import a\n")
    analysis = analyze_project(tmp_path)
    root = root_named(analysis, "package.a")

    details = module_details(analysis, root.root_id)

    assert details is not None
    assert details.module == "package.a"
    assert details.functions == ("run",)
    assert details.classes == ("Item",)
    assert "json" in details.external_imports
    assert details.cycle_number == 1
    assert set(details.cycle_modules) == {"package.a", "package.b"}
