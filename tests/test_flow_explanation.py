from __future__ import annotations

import builtins
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from pysynoptic import analyze_callable_flow
from pysynoptic.analyzer import analyze_python_file_context
from pysynoptic.insights import (
    FlowExplanationReliability,
    analyze_insights,
    explain_callable_flow,
)
from pysynoptic.models import CallableFlowGraph, FlowEdge, FlowNode


def explain_source(
    tmp_path: Path,
    source: str,
    qualified_name: str = "run",
    *,
    with_insights: bool = False,
):
    path = tmp_path / "sample.py"
    path.write_text(source, encoding="utf-8")
    analysis = analyze_python_file_context(path)
    symbol = next(
        item
        for file_analysis in analysis.file_analyses
        for item in file_analysis.callable_symbols
        if item.qualified_name == qualified_name
    )
    flow = analyze_callable_flow(path, symbol)
    insights = analyze_insights(analysis) if with_insights else None
    return flow, explain_callable_flow(flow, insights)


def flatten(steps):
    return tuple(
        step for parent in steps for step in (parent, *flatten(parent.child_steps))
    )


def texts(explanation) -> tuple[str, ...]:
    return tuple(step.text for step in flatten(explanation.steps))


def test_simple_return_explains_expression_without_evaluation(tmp_path: Path) -> None:
    _, explanation = explain_source(tmp_path, "def run(a, b):\n    return a + b\n")

    assert explanation.summary == "Return the result of a + b."
    assert explanation.steps[0].text == "Return the result of a + b."
    assert explanation.outcomes[0].kind == "return"


def test_sequential_statements_keep_source_order(tmp_path: Path) -> None:
    _, explanation = explain_source(
        tmp_path,
        "def run():\n    value = prepare()\n    save(value)\n    return value\n",
    )

    assert texts(explanation) == (
        "Set value from prepare().",
        "Call save().",
        "Return value.",
    )
    assert tuple(step.order for step in explanation.steps) == (1, 2, 3)


def test_if_records_true_path(tmp_path: Path) -> None:
    _, explanation = explain_source(
        tmp_path,
        "def run(enabled):\n    if enabled:\n        prepare()\n    return 0\n",
    )

    decision = explanation.decisions[0]
    assert decision.condition == "enabled"
    assert [step.text for step in decision.true_path] == ["Call prepare()."]
    assert decision.false_path == ()
    assert "If enabled is true" in texts(explanation)[0]


def test_if_else_keeps_branches_distinct(tmp_path: Path) -> None:
    _, explanation = explain_source(
        tmp_path,
        (
            "def run(enabled):\n"
            "    if enabled:\n        prepare()\n"
            "    else:\n        skip()\n"
            "    return 0\n"
        ),
    )

    decision = explanation.decisions[0]
    assert [step.text for step in decision.true_path] == ["Call prepare()."]
    assert [step.text for step in decision.false_path] == ["Call skip()."]
    assert "Otherwise" in texts(explanation)[0]


def test_if_elif_else_preserves_nested_false_decision(tmp_path: Path) -> None:
    _, explanation = explain_source(
        tmp_path,
        (
            "def run(value):\n"
            "    if value == 1:\n        first()\n"
            "    elif value == 2:\n        second()\n"
            "    else:\n        other()\n"
        ),
    )

    assert len(explanation.decisions) == 2
    outer = explanation.decisions[0]
    assert outer.false_path[0].kind == "decision"
    assert explanation.decisions[1].condition == "value == 2"


def test_for_loop_has_nested_body_steps(tmp_path: Path) -> None:
    _, explanation = explain_source(
        tmp_path,
        "def run(items):\n    for item in items:\n        consume(item)\n",
    )

    loop = explanation.loops[0]
    assert explanation.steps[0].text == "Process each item."
    assert [step.text for step in loop.body_steps] == ["Call consume()."]


def test_while_loop_does_not_predict_iteration_count(tmp_path: Path) -> None:
    _, explanation = explain_source(
        tmp_path,
        "def run(pending):\n    while pending:\n        consume()\n",
    )

    assert explanation.steps[0].text == "Repeat while pending."
    assert "times" not in explanation.summary.casefold()


def test_nested_loops_remain_hierarchical(tmp_path: Path) -> None:
    _, explanation = explain_source(
        tmp_path,
        (
            "def run(rows, columns):\n"
            "    for row in rows:\n"
            "        for column in columns:\n"
            "            save(row, column)\n"
        ),
    )

    assert len(explanation.steps) == 1
    assert explanation.steps[0].kind == "loop"
    nested = next(
        step for step in explanation.steps[0].child_steps if step.kind == "loop"
    )
    assert nested.text == "Process each column."
    assert nested.child_steps[0].text == "Call save()."


def test_break_is_retained_inside_its_condition(tmp_path: Path) -> None:
    _, explanation = explain_source(
        tmp_path,
        (
            "def run(items):\n"
            "    for item in items:\n"
            "        if stop(item):\n            break\n"
        ),
    )

    assert "Stop processing the loop." in texts(explanation)
    decision = explanation.decisions[0]
    assert decision.true_path[0].kind == "break"


def test_continue_is_retained_inside_its_condition(tmp_path: Path) -> None:
    _, explanation = explain_source(
        tmp_path,
        (
            "def run(items):\n"
            "    for item in items:\n"
            "        if skip(item):\n            continue\n"
            "        save(item)\n"
        ),
    )

    assert "Continue with the next item." in texts(explanation)
    assert explanation.decisions[0].true_path[0].kind == "continue"


def test_try_except_lists_visible_handler_types(tmp_path: Path) -> None:
    _, explanation = explain_source(
        tmp_path,
        (
            "def run():\n"
            "    try:\n        parse()\n"
            "    except ValueError:\n        recover()\n"
            "    except OSError:\n        recover_io()\n"
        ),
    )

    exception = explanation.exceptions[0]
    assert exception.handlers == ("ValueError", "OSError")
    assert "handle ValueError and OSError separately" in explanation.steps[0].text


def test_try_except_finally_keeps_finalization_path(tmp_path: Path) -> None:
    _, explanation = explain_source(
        tmp_path,
        (
            "def run():\n"
            "    try:\n        parse()\n"
            "    except ValueError:\n        recover()\n"
            "    finally:\n        cleanup()\n"
        ),
    )

    exception = explanation.exceptions[0]
    assert exception.finally_summary == "Call cleanup()."
    assert "always execute the finalization path" in explanation.steps[0].text


def test_raise_preserves_visible_exception_type(tmp_path: Path) -> None:
    _, explanation = explain_source(
        tmp_path, "def run():\n    raise ValueError('bad')\n"
    )

    assert explanation.outcomes[0].kind == "raise"
    assert explanation.outcomes[0].text == "Raise ValueError."


def test_multiple_returns_remain_distinct_outcomes(tmp_path: Path) -> None:
    _, explanation = explain_source(
        tmp_path,
        (
            "def run(error, result):\n"
            "    if error:\n        return None\n"
            "    return result\n"
        ),
    )

    assert [outcome.text for outcome in explanation.outcomes] == [
        "Return None.",
        "Return result.",
    ]


def test_resolved_internal_call_reuses_existing_purpose(tmp_path: Path) -> None:
    _, explanation = explain_source(
        tmp_path,
        (
            "def parse_input():\n"
            '    """Parse the configured input."""\n'
            "    return {}\n\n"
            "def run():\n    parse_input()\n"
        ),
        with_insights=True,
    )

    assert "Parse the configured input." in texts(explanation)
    assert "Call parse_input()." not in texts(explanation)


def test_resolved_call_without_purpose_uses_call_fallback(tmp_path: Path) -> None:
    _, explanation = explain_source(
        tmp_path,
        "def helper():\n    pass\n\ndef run():\n    helper()\n",
        with_insights=True,
    )

    assert texts(explanation) == ("Call helper().",)


def test_unresolved_call_uses_visible_static_name(tmp_path: Path) -> None:
    _, explanation = explain_source(tmp_path, "def run():\n    external_call()\n")

    assert texts(explanation) == ("Call external_call().",)


def test_repeated_append_node_is_compacted_once(tmp_path: Path) -> None:
    flow, explanation = explain_source(
        tmp_path,
        (
            "def run():\n"
            "    lines = []\n"
            "    lines.append('a')\n"
            "    lines.append('b')\n"
            "    lines.extend(['c'])\n"
            "    return lines\n"
        ),
    )

    compacted_node = next(node for node in flow.nodes if "(3 steps)" in node.label)
    step = next(step for step in explanation.steps if step.kind == "sequence")
    assert step.text == "Build the output text."
    assert step.source_node_ids == (compacted_node.node_id,)


def test_already_compacted_build_output_node_is_respected() -> None:
    flow = CallableFlowGraph(
        symbol_id="sample.py::run@1:0",
        path=Path("sample.py"),
        name="run",
        qualified_name="run",
        line=1,
        nodes=(
            FlowNode("entry", "START run()", "entry", 1, 0, "run"),
            FlowNode(
                "build",
                "Build lines output (47 steps)",
                "call",
                2,
                4,
                "lines.append('a')\nlines.append('b')",
            ),
            FlowNode("return", "return lines", "return", 3, 4, "return lines"),
            FlowNode("exit", "EXIT", "exit", 1, 0, "Function exit"),
        ),
        edges=(
            FlowEdge("entry", "build", "next", "next"),
            FlowEdge("build", "return", "next", "next"),
            FlowEdge("return", "exit", "return", "return"),
        ),
    )

    explanation = explain_callable_flow(flow)

    assert explanation.steps[0].text == "Build the output text."
    assert explanation.steps[0].source_node_ids == ("build",)


def test_models_are_immutable_and_exactly_deterministic(tmp_path: Path) -> None:
    flow, first = explain_source(
        tmp_path, "def run(items):\n    for item in items:\n        save(item)\n"
    )
    second = explain_callable_flow(flow)

    assert first == second
    with pytest.raises(FrozenInstanceError):
        first.summary = "changed"


def test_reversed_internal_order_does_not_change_explanation(tmp_path: Path) -> None:
    flow, expected = explain_source(
        tmp_path,
        (
            "def run(items, enabled):\n"
            "    if enabled:\n        prepare()\n"
            "    for item in items:\n        save(item)\n"
            "    return items\n"
        ),
    )
    reversed_flow = replace(
        flow,
        nodes=tuple(reversed(flow.nodes)),
        edges=tuple(reversed(flow.edges)),
    )

    assert explain_callable_flow(reversed_flow) == expected


def test_every_structured_phrase_is_traceable_to_existing_nodes(tmp_path: Path) -> None:
    flow, explanation = explain_source(
        tmp_path,
        (
            "def run(items):\n"
            "    for item in items:\n"
            "        if item:\n            save(item)\n"
            "    return items\n"
        ),
    )
    valid_ids = {node.node_id for node in flow.nodes}

    assert explanation.supporting_node_ids
    assert set(explanation.supporting_node_ids) <= valid_ids
    for step in flatten(explanation.steps):
        assert step.source_node_ids
        assert set(step.source_node_ids) <= valid_ids
    for decision in explanation.decisions:
        assert set(decision.source_node_ids) <= valid_ids
    for loop in explanation.loops:
        assert set(loop.source_node_ids) <= valid_ids


def test_explanation_does_not_read_or_execute_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "executed"
    flow, _ = explain_source(
        tmp_path,
        f"def run():\n    Path({str(marker)!r}).write_text('bad')\n",
    )

    def forbidden_read(*_args, **_kwargs):
        raise AssertionError("Flow explanation read source")

    monkeypatch.setattr(Path, "read_text", forbidden_read)
    explain_callable_flow(flow)

    assert not marker.exists()


def test_explanation_performs_no_runtime_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flow, _ = explain_source(tmp_path, "def run():\n    return 1\n")

    def forbidden_import(*_args, **_kwargs):
        raise AssertionError("Flow explanation imported a runtime module")

    monkeypatch.setattr(builtins, "__import__", forbidden_import)
    explanation = explain_callable_flow(flow)

    assert explanation.summary == "Return 1."


def test_minimal_opaque_function_prefers_unknown(tmp_path: Path) -> None:
    _, explanation = explain_source(tmp_path, "def run():\n    pass\n")

    assert explanation.summary is None
    assert explanation.steps == ()
    assert explanation.reliability is FlowExplanationReliability.UNKNOWN


def test_complex_realistic_flow_is_compact_and_structured(tmp_path: Path) -> None:
    _, explanation = explain_source(
        tmp_path,
        (
            "def render(items, enabled):\n"
            "    lines = []\n"
            "    try:\n"
            "        for item in items:\n"
            "            if enabled and item:\n"
            "                lines.append(format_item(item))\n"
            "            else:\n"
            "                continue\n"
            "    except ValueError:\n"
            "        lines.append('error')\n"
            "    finally:\n"
            "        finalize()\n"
            "    return '\\n'.join(lines)\n"
        ),
        "render",
    )

    assert len(explanation.steps) <= 10
    assert explanation.loops
    assert explanation.decisions
    assert explanation.exceptions[0].handlers == ("ValueError",)
    assert explanation.exceptions[0].finally_summary == "Call finalize()."
    assert explanation.outcomes[-1].text == (
        "Join lines and return the resulting text."
    )
    assert explanation.summary and len(explanation.summary) <= 500


def test_cyclic_branch_reconstruction_remains_finite() -> None:
    flow = CallableFlowGraph(
        symbol_id="sample.py::run@1:0",
        path=Path("sample.py"),
        name="run",
        qualified_name="run",
        line=1,
        nodes=(
            FlowNode("entry", "START run()", "entry", 1, 0, "run"),
            FlowNode("decision", "if pending", "if", 2, 4, "if pending"),
            FlowNode("work", "consume()", "call", 3, 8, "consume()"),
            FlowNode("return", "return result", "return", 4, 4, "return result"),
            FlowNode("exit", "EXIT", "exit", 1, 0, "Function exit"),
        ),
        edges=(
            FlowEdge("entry", "decision", "next", "next"),
            FlowEdge("decision", "work", "true", "yes"),
            FlowEdge("decision", "return", "false", "no"),
            FlowEdge("work", "decision", "next", "next"),
            FlowEdge("return", "exit", "return", "return"),
        ),
    )

    explanation = explain_callable_flow(flow)

    assert explanation.decisions[0].true_path[0].text == "Call consume()."
    assert len(explanation.steps) == 2
    assert len(explanation.supporting_node_ids) == len(
        set(explanation.supporting_node_ids)
    )
