from dataclasses import replace
from pathlib import Path

import pytest

from pysynoptic import analyze_project
from pysynoptic.graph import (
    build_contextual_call_graph,
    call_graph_roots,
    layout_graph,
    search_call_graph_roots,
)


def write_python(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def sample_analysis(tmp_path: Path):
    write_python(
        tmp_path / "flow.py",
        (
            "def first():\n"
            "    second()\n"
            "def second():\n"
            "    third()\n"
            "def third():\n"
            "    pass\n"
            "def recursive():\n"
            "    recursive()\n"
        ),
    )
    write_python(
        tmp_path / "entry.py",
        (
            "from flow import first\n"
            "def caller():\n"
            "    first()\n"
            "def noisy():\n"
            "    first()\n"
            "    missing()\n"
            "    registry[key]()\n"
            "first()\n"
        ),
    )
    return analyze_project(tmp_path)


def root_by_label(analysis, label: str):
    return next(root for root in call_graph_roots(analysis) if root.label == label)


def labels(result) -> set[str]:
    return {node.label for node in result.graph.nodes}


def test_roots_include_modules_and_callables_in_stable_order(tmp_path: Path) -> None:
    analysis = sample_analysis(tmp_path)

    first = call_graph_roots(analysis)
    second = call_graph_roots(analysis)

    assert first == second
    assert root_by_label(analysis, "flow").kind == "module"
    assert root_by_label(analysis, "flow::first").kind == "callable"


def test_searches_roots_by_case_insensitive_substring(tmp_path: Path) -> None:
    analysis = sample_analysis(tmp_path)

    matches = search_call_graph_roots(analysis, "FIRST")

    assert [root.label for root in matches] == ["flow::first"]


def test_callable_outgoing_depth_one_contains_direct_callee(tmp_path: Path) -> None:
    analysis = sample_analysis(tmp_path)
    root = root_by_label(analysis, "flow::first")

    result = build_contextual_call_graph(analysis, root)

    assert labels(result) == {"flow::first", "flow::second"}
    assert result.diagnostics.visible_edge_count == 1
    assert result.diagnostics.outgoing_count == 1


def test_increasing_depth_rebuilds_with_next_hop(tmp_path: Path) -> None:
    analysis = sample_analysis(tmp_path)
    root = root_by_label(analysis, "flow::first")

    depth_one = build_contextual_call_graph(analysis, root, depth=1)
    depth_two = build_contextual_call_graph(analysis, root, depth=2)

    assert "flow::third" not in labels(depth_one)
    assert "flow::third" in labels(depth_two)
    assert len(depth_two.graph.edges) == 2


def test_incoming_context_follows_callers_and_module_level_calls(
    tmp_path: Path,
) -> None:
    analysis = sample_analysis(tmp_path)
    root = root_by_label(analysis, "flow::first")

    result = build_contextual_call_graph(
        analysis,
        root,
        direction="incoming",
    )

    assert labels(result) == {
        "flow::first",
        "entry::caller",
        "entry::noisy",
        "entry::<module>",
    }
    assert result.diagnostics.incoming_count == 3


def test_both_context_preserves_original_edge_directions(tmp_path: Path) -> None:
    analysis = sample_analysis(tmp_path)
    root = root_by_label(analysis, "flow::first")

    result = build_contextual_call_graph(analysis, root, direction="both")
    edge_labels = {
        (
            next(
                node.label
                for node in result.graph.nodes
                if node.node_id == edge.source_id
            ),
            next(
                node.label
                for node in result.graph.nodes
                if node.node_id == edge.target_id
            ),
        )
        for edge in result.graph.edges
    }

    assert ("flow::first", "flow::second") in edge_labels
    assert ("entry::caller", "flow::first") in edge_labels


def test_module_root_seeds_module_level_and_all_module_callables(
    tmp_path: Path,
) -> None:
    analysis = sample_analysis(tmp_path)
    root = root_by_label(analysis, "entry")

    result = build_contextual_call_graph(analysis, root)

    assert {"entry::<module>", "entry::caller", "entry::noisy"} <= labels(result)
    assert "flow::first" in labels(result)
    assert len(result.root_node_ids) == 3


def test_diagnostics_count_resolution_statuses_for_selected_callable(
    tmp_path: Path,
) -> None:
    analysis = sample_analysis(tmp_path)
    root = root_by_label(analysis, "entry::noisy")

    result = build_contextual_call_graph(analysis, root)
    diagnostics = result.diagnostics

    assert diagnostics.outgoing_count == 1
    assert diagnostics.resolved_count == 1
    assert diagnostics.ambiguous_count == 0
    assert diagnostics.unresolved_count == 1
    assert diagnostics.dynamic_count == 1


def test_recursive_call_remains_a_visible_cycle(tmp_path: Path) -> None:
    analysis = sample_analysis(tmp_path)
    root = root_by_label(analysis, "flow::recursive")

    result = build_contextual_call_graph(analysis, root)
    layout = layout_graph(result.graph)

    assert len(result.graph.nodes) == 1
    assert len(result.graph.edges) == 1
    assert layout.cyclic_component_count == 1


@pytest.mark.parametrize("depth", [0, 4])
def test_rejects_unsupported_depth(tmp_path: Path, depth: int) -> None:
    analysis = sample_analysis(tmp_path)
    root = root_by_label(analysis, "flow::first")

    with pytest.raises(ValueError, match="depth"):
        build_contextual_call_graph(analysis, root, depth=depth)


def test_rejects_root_from_another_analysis(tmp_path: Path) -> None:
    analysis = sample_analysis(tmp_path)
    root = replace(root_by_label(analysis, "flow::first"), root_id="not-present")

    with pytest.raises(ValueError, match="does not belong"):
        build_contextual_call_graph(analysis, root)
