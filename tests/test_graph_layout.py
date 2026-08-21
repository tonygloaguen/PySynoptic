from pathlib import Path

from pysynoptic.analyzer import analyze_project
from pysynoptic.graph import (
    DependencyGraph,
    GraphEdge,
    GraphNode,
    build_dependency_graph,
    layout_dependency_graph,
    layout_graph,
    strongly_connected_components,
)


def write_python(path: Path, source: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def test_builds_nodes_for_modules_without_dependencies(tmp_path: Path) -> None:
    write_python(tmp_path / "isolated.py")
    analysis = analyze_project(tmp_path)

    graph = build_dependency_graph(
        analysis.module_identities,
        analysis.dependencies,
    )

    assert [node.label for node in graph.nodes] == ["isolated"]
    assert graph.edges == ()


def test_deduplicates_logical_edges(tmp_path: Path) -> None:
    write_python(tmp_path / "source.py", "import target\nimport target\n")
    write_python(tmp_path / "target.py")
    analysis = analyze_project(tmp_path)

    graph = build_dependency_graph(
        analysis.module_identities,
        (*analysis.dependencies, *analysis.dependencies),
    )

    assert len(graph.edges) == 1


def test_finds_strongly_connected_components_without_recursion() -> None:
    nodes = tuple(
        GraphNode(name, name, Path(f"/{name}.py")) for name in ("a", "b", "c", "d")
    )
    graph = DependencyGraph(
        nodes=nodes,
        edges=(
            GraphEdge("a", "b"),
            GraphEdge("b", "a"),
            GraphEdge("b", "c"),
            GraphEdge("d", "d"),
        ),
    )

    components = strongly_connected_components(graph)

    assert {frozenset(component) for component in components} == {
        frozenset({"a", "b"}),
        frozenset({"c"}),
        frozenset({"d"}),
    }


def test_assigns_dependency_chain_to_successive_layers(tmp_path: Path) -> None:
    write_python(tmp_path / "a.py", "import b\n")
    write_python(tmp_path / "b.py", "import c\n")
    write_python(tmp_path / "c.py")

    layout = layout_dependency_graph(analyze_project(tmp_path))
    layers = {item.node.label: item.layer for item in layout.nodes}

    assert layers == {"a": 0, "b": 1, "c": 2}
    assert layout.layer_count == 3


def test_places_cycle_members_in_the_same_layer(tmp_path: Path) -> None:
    write_python(tmp_path / "a.py", "import b\n")
    write_python(tmp_path / "b.py", "import a\n")
    write_python(tmp_path / "entry.py", "import a\n")

    layout = layout_dependency_graph(analyze_project(tmp_path))
    nodes = {item.node.label: item for item in layout.nodes}

    assert nodes["entry"].layer == 0
    assert nodes["a"].layer == nodes["b"].layer == 1
    assert nodes["a"].component == nodes["b"].component
    assert layout.cyclic_component_count == 1


def test_counts_self_dependency_as_cyclic_component(tmp_path: Path) -> None:
    write_python(tmp_path / "recursive.py", "import recursive\n")

    layout = layout_dependency_graph(analyze_project(tmp_path))

    assert layout.cyclic_component_count == 1


def test_layout_is_deterministic(tmp_path: Path) -> None:
    write_python(tmp_path / "package" / "__init__.py")
    write_python(tmp_path / "package" / "a.py", "from . import b\n")
    write_python(tmp_path / "package" / "b.py")
    analysis = analyze_project(tmp_path)

    first = layout_dependency_graph(analysis)
    second = layout_dependency_graph(analysis)

    assert first == second


def test_positioned_nodes_do_not_overlap_within_a_layer(tmp_path: Path) -> None:
    for name in ("alpha", "beta", "gamma"):
        write_python(tmp_path / f"{name}.py")

    layout = layout_dependency_graph(analyze_project(tmp_path))
    nodes = sorted(layout.nodes, key=lambda item: item.y)

    assert all(
        first.y + first.height < second.y
        for first, second in zip(nodes, nodes[1:], strict=False)
    )


def test_empty_project_has_empty_layout(tmp_path: Path) -> None:
    layout = layout_dependency_graph(analyze_project(tmp_path))

    assert layout.nodes == ()
    assert layout.edges == ()
    assert layout.components == ()
    assert layout.layer_count == 0
    assert layout.width == 0
    assert layout.height == 0


def test_generic_layout_positions_renderer_independent_graph() -> None:
    graph = DependencyGraph(
        nodes=(
            GraphNode("caller", "package::caller", Path("package.py")),
            GraphNode("callee", "package::callee", Path("package.py")),
        ),
        edges=(GraphEdge("caller", "callee"),),
    )

    layout = layout_graph(graph)

    layers = {node.node.node_id: node.layer for node in layout.nodes}
    assert layers == {"caller": 0, "callee": 1}
