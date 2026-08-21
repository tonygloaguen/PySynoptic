from pathlib import Path

import pytest

from pysynoptic import analyze_callable_flow, analyze_python_file
from pysynoptic.graph import build_function_flow_graph, layout_vertical_graph


def analyze_source(tmp_path: Path, source: str):
    path = tmp_path / "pipeline.py"
    path.write_text(source, encoding="utf-8")
    return path, analyze_python_file(path)


def flow_named(path: Path, analysis, qualified_name: str):
    symbol = next(
        symbol
        for symbol in analysis.callable_symbols
        if symbol.qualified_name == qualified_name
    )
    return analyze_callable_flow(path, symbol)


def test_builds_straight_line_calls_and_return(tmp_path: Path) -> None:
    path, analysis = analyze_source(
        tmp_path,
        "def main():\n    parse_arguments()\n    render_markdown()\n    return 0\n",
    )

    flow = flow_named(path, analysis, "main")
    labels = {node.label for node in flow.nodes}
    kinds = {node.kind for node in flow.nodes}

    assert labels == {
        "START main()",
        "parse_arguments()",
        "render_markdown()",
        "return 0",
        "EXIT",
    }
    assert {"entry", "call", "return", "exit"} <= kinds
    assert {edge.kind for edge in flow.edges} == {"next", "return"}


def test_labels_if_branches_and_loop_back_edge(tmp_path: Path) -> None:
    path, analysis = analyze_source(
        tmp_path,
        (
            "def process(items, enabled):\n"
            "    if enabled:\n        prepare()\n"
            "    else:\n        skip()\n"
            "    for item in items:\n        save(item)\n"
            "    return items\n"
        ),
    )

    flow = flow_named(path, analysis, "process")
    edge_kinds = {edge.kind for edge in flow.edges}

    assert {"true", "false", "loop", "exit-loop", "return"} <= edge_kinds
    graph = build_function_flow_graph(flow)
    layout = layout_vertical_graph(graph)
    assert layout.cyclic_component_count == 1


def test_represents_try_except_finally_raise_and_return(tmp_path: Path) -> None:
    path, analysis = analyze_source(
        tmp_path,
        (
            "def parse(path):\n"
            "    try:\n        root = ET.parse(path)\n"
            "    except ET.ParseError:\n        raise SystemExit(1)\n"
            "    finally:\n        cleanup()\n"
            "    return root\n"
        ),
    )

    flow = flow_named(path, analysis, "parse")
    kinds = {node.kind for node in flow.nodes}
    edge_labels = {edge.label for edge in flow.edges}

    assert {"try", "except", "finally", "raise", "return"} <= kinds
    assert {"try", "except", "finally", "handle", "raise", "return"} <= edge_labels


def test_break_and_continue_use_structural_loop_edges(tmp_path: Path) -> None:
    path, analysis = analyze_source(
        tmp_path,
        (
            "def run(items):\n"
            "    while items:\n"
            "        if skip(items):\n            continue\n"
            "        if stop(items):\n            break\n"
            "        consume(items)\n"
            "    return None\n"
        ),
    )

    flow = flow_named(path, analysis, "run")

    assert {"break", "continue"} <= {node.kind for node in flow.nodes}
    assert {"break", "continue"} <= {edge.kind for edge in flow.edges}


def test_builds_targeted_flows_for_method_and_nested_function(tmp_path: Path) -> None:
    path, analysis = analyze_source(
        tmp_path,
        (
            "class Parser:\n"
            "    def parse(self):\n"
            "        def normalize():\n            return 1\n"
            "        return normalize()\n"
        ),
    )

    method = flow_named(path, analysis, "Parser.parse")
    nested = flow_named(path, analysis, "Parser.parse.<locals>.normalize")

    assert method.qualified_name == "Parser.parse"
    assert nested.qualified_name == "Parser.parse.<locals>.normalize"
    assert method.symbol_id != nested.symbol_id


def test_shortens_labels_preserves_details_locations_and_is_deterministic(
    tmp_path: Path,
) -> None:
    path, analysis = analyze_source(
        tmp_path,
        "def run():\n    extremely_long_function_name_that_does_not_fit_in_a_box()\n",
    )
    symbol = analysis.callable_symbols[0]

    first = analyze_callable_flow(path, symbol)
    second = analyze_callable_flow(path, symbol)
    call = next(node for node in first.nodes if node.kind == "call")

    assert first == second
    assert len(call.label) <= 48
    assert call.label.endswith("…")
    assert call.line == 2
    assert "extremely_long_function_name" in call.detail


def test_flow_never_executes_analyzed_source(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    path, analysis = analyze_source(
        tmp_path,
        f"def run():\n    open({str(marker)!r}, 'w').write('bad')\n",
    )

    analyze_callable_flow(path, analysis.callable_symbols[0])

    assert not marker.exists()


def test_rejects_symbol_not_present_in_source(tmp_path: Path) -> None:
    path, analysis = analyze_source(tmp_path, "def before():\n    pass\n")
    symbol = analysis.callable_symbols[0]
    path.write_text("def after():\n    pass\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Callable source not found"):
        analyze_callable_flow(path, symbol)


def test_empty_function_and_if_without_else_rejoin_exit(tmp_path: Path) -> None:
    path, analysis = analyze_source(
        tmp_path,
        "def empty():\n    pass\ndef choose(flag):\n    if flag:\n        return 1\n",
    )

    empty = flow_named(path, analysis, "empty")
    choose = flow_named(path, analysis, "choose")

    assert {node.label for node in empty.nodes} == {"START empty()", "pass", "EXIT"}
    assert {"true", "false", "return"} <= {edge.kind for edge in choose.edges}
    return_id = next(node.node_id for node in choose.nodes if node.kind == "return")
    assert all(
        edge.kind == "return" for edge in choose.edges if edge.source_id == return_id
    )


def test_async_for_nested_loops_and_multiple_except_branches(tmp_path: Path) -> None:
    path, analysis = analyze_source(
        tmp_path,
        (
            "async def consume(stream, rows):\n"
            "    try:\n"
            "        async for item in stream:\n"
            "            for row in rows:\n"
            "                if row:\n                    save(item, row)\n"
            "    except ValueError:\n        recover()\n"
            "    except TypeError:\n        recover_type()\n"
            "    return None\n"
        ),
    )

    flow = flow_named(path, analysis, "consume")

    assert sum(node.kind == "loop" for node in flow.nodes) == 2
    assert sum(node.kind == "except" for node in flow.nodes) == 2
    assert sum(edge.kind == "loop" for edge in flow.edges) == 2
    assert sum(edge.kind == "except" for edge in flow.edges) == 2


def test_compacts_repeated_output_calls_without_losing_details(tmp_path: Path) -> None:
    path, analysis = analyze_source(
        tmp_path,
        (
            "def report():\n"
            "    lines = []\n"
            "    lines.append('title')\n"
            "    lines.extend(['body'])\n"
            "    lines.append('footer')\n"
            "    print('one')\n"
            "    print('two')\n"
            "    return lines\n"
        ),
    )

    flow = flow_named(path, analysis, "report")
    output = next(node for node in flow.nodes if node.label.startswith("Build lines"))

    assert output.label == "Build lines output (3 steps)"
    assert "lines.append('title')" in output.detail
    assert "lines.extend(['body'])" in output.detail
    assert any(node.label == "Print 2 messages" for node in flow.nodes)


def test_flow_layout_uses_source_order_instead_of_flattening_loop_scc(
    tmp_path: Path,
) -> None:
    path, analysis = analyze_source(
        tmp_path,
        "def run(items):\n    for item in items:\n        save(item)\n    return 0\n",
    )
    flow = flow_named(path, analysis, "run")

    layout = layout_vertical_graph(build_function_flow_graph(flow))
    positioned = {item.node.kind: item for item in layout.nodes}

    assert positioned["entry"].y < positioned["loop"].y
    assert positioned["loop"].y < positioned["call"].y
    assert positioned["call"].y < positioned["return"].y
    assert positioned["return"].y < positioned["exit"].y
    assert layout.width < 800
