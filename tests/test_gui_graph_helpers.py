from pathlib import Path

import pytest

from pysynoptic import analyze_python_file_context
from pysynoptic.graph import DependencyGraph, GraphNode, graph_readability_message
from pysynoptic.gui.graph_helpers import (
    DEFAULT_CALL_DEPTH,
    DEFAULT_CALL_DIRECTION,
    default_flow_callable,
    empty_outgoing_suggestion,
    search_flow_callables,
)
from pysynoptic.renderers import render_mermaid_export


def write_python(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")


def test_focused_call_defaults_and_empty_suggestion() -> None:
    assert DEFAULT_CALL_DIRECTION == "both"
    assert DEFAULT_CALL_DEPTH == 1
    assert empty_outgoing_suggestion(3, "outgoing") == (
        "No resolved outgoing calls.\n\n3 resolved incoming callers are available."
    )
    assert empty_outgoing_suggestion(3, "both") is None


def test_flow_selector_prefers_main_for_single_file(tmp_path: Path) -> None:
    path = tmp_path / "script.py"
    write_python(path, "def first():\n    pass\ndef main():\n    pass\n")
    analysis = analyze_python_file_context(path)

    selected = default_flow_callable(analysis)

    assert selected is not None
    assert selected.symbol.name == "main"
    assert [item.symbol.name for item in search_flow_callables(analysis, "FIRST")] == [
        "first"
    ]


def test_flow_selector_falls_back_to_first_top_level_not_method(
    tmp_path: Path,
) -> None:
    path = tmp_path / "script.py"
    write_python(
        path,
        "def first():\n    pass\nclass C:\n    def method(self):\n        pass\n",
    )
    analysis = analyze_python_file_context(path)

    selected = default_flow_callable(analysis)

    assert selected is not None
    assert selected.symbol.name == "first"


def test_large_graph_readability_guard() -> None:
    small = DependencyGraph((GraphNode("a", "a", Path("a.py")),), ())
    large = DependencyGraph(
        tuple(
            GraphNode(str(index), str(index), Path(f"{index}.py"))
            for index in range(81)
        ),
        (),
    )

    assert graph_readability_message(small) is None
    assert graph_readability_message(large) == (
        "Large graph (81 nodes): select a module/callable or reduce depth for a "
        "readable view."
    )
    with pytest.raises(ValueError, match="positive"):
        graph_readability_message(small, threshold=0)


def test_mermaid_mode_requires_current_graph_but_whole_does_not(
    tmp_path: Path,
) -> None:
    path = tmp_path / "script.py"
    write_python(path, "def main():\n    pass\n")
    analysis = analyze_python_file_context(path)
    graph = DependencyGraph((GraphNode("main", "main()", path),), ())

    assert "main()" in render_mermaid_export("calls", analysis, graph)
    assert "script" in render_mermaid_export("whole", analysis)
    with pytest.raises(ValueError, match="No current flow"):
        render_mermaid_export("flow", analysis)
