from __future__ import annotations

import socket
import threading
from dataclasses import replace
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest

from pysynoptic import (
    analyze_callable_flow,
    analyze_project,
    analyze_python_file_context,
)
from pysynoptic.gui.app import PySynopticApp
from pysynoptic.gui.flow import FlowPanel
from pysynoptic.gui.flow_explanations import FlowExplanationCache
from pysynoptic.gui.graph_canvas import DependencyGraphCanvas
from pysynoptic.gui.insights import (
    InsightSelection,
    flow_step_presentations,
    flow_summary_text,
    present_insight,
)
from pysynoptic.gui.project_tree import plan_callable_navigation
from pysynoptic.gui.state import ApplicationState
from pysynoptic.insights import (
    FlowExplanationReliability,
    analyze_insights,
)
from pysynoptic.models import FlowNode

_SAMPLE_SOURCE = """
def add(a, b):
    return a + b

def choose(enabled):
    if enabled:
        prepare()
    else:
        skip()
    return 0

def nested(rows, columns):
    for row in rows:
        for column in columns:
            save(row, column)

def guarded():
    try:
        parse()
    except ValueError:
        recover()
    return None

def opaque():
    pass
"""


def sample_workspace(tmp_path: Path):
    path = tmp_path / "sample.py"
    path.write_text(_SAMPLE_SOURCE, encoding="utf-8")
    analysis = analyze_python_file_context(path)
    insights = analyze_insights(analysis)
    cache = FlowExplanationCache()
    cache.set_analysis(analysis, insights)
    identities = {item.symbol.name: item for item in analysis.callable_identities}
    callable_insights = {item.qualified_name: item for item in insights.callables}
    return path, analysis, insights, cache, identities, callable_insights


def explanation_for(tmp_path: Path, name: str):
    *_, cache, identities, _callable_insights = sample_workspace(tmp_path)
    result = cache.get(identities[name].symbol.symbol_id)
    assert result is not None
    return result.explanation


def test_how_it_works_is_available_for_callable_presentation(tmp_path: Path) -> None:
    *_, cache, identities, callable_insights = sample_workspace(tmp_path)
    identity = identities["add"]
    result = cache.get(identity.symbol.symbol_id)
    assert result is not None

    presentation = present_insight(
        InsightSelection("callable", callable_insights["add"].identity),
        callable_insights["add"],
        result.explanation,
    )

    assert presentation.flow_explanation is result.explanation


def test_how_it_works_preserves_exact_summary(tmp_path: Path) -> None:
    explanation = explanation_for(tmp_path, "add")

    assert flow_summary_text(explanation) == explanation.summary
    assert flow_summary_text(explanation) == "Return the result of a + b."


def test_flow_reliability_high_is_preserved(tmp_path: Path) -> None:
    explanation = explanation_for(tmp_path, "add")

    assert explanation.reliability is FlowExplanationReliability.HIGH


def test_flow_reliability_medium_is_presentable(tmp_path: Path) -> None:
    explanation = replace(
        explanation_for(tmp_path, "add"),
        reliability=FlowExplanationReliability.MEDIUM,
    )

    assert explanation.reliability.value.upper() == "MEDIUM"


def test_flow_reliability_unknown_is_preserved(tmp_path: Path) -> None:
    explanation = explanation_for(tmp_path, "opaque")

    assert explanation.reliability is FlowExplanationReliability.UNKNOWN
    assert explanation.summary is None


def test_missing_summary_uses_only_approved_fallback(tmp_path: Path) -> None:
    explanation = explanation_for(tmp_path, "opaque")

    assert flow_summary_text(explanation) == ("No reliable flow explanation available.")
    assert flow_summary_text(None) == "No reliable flow explanation available."


def test_key_steps_keep_root_order(tmp_path: Path) -> None:
    rows = flow_step_presentations(explanation_for(tmp_path, "choose").steps)
    roots = tuple(row for row in rows if row.depth == 0)

    assert tuple(row.marker for row in roots) == ("1.", "2.")
    assert roots[-1].text == "Return 0."


def test_key_steps_keep_nested_loop_hierarchy(tmp_path: Path) -> None:
    rows = flow_step_presentations(explanation_for(tmp_path, "nested").steps)

    assert tuple((row.depth, row.marker) for row in rows) == (
        (0, "1."),
        (1, "•"),
        (2, "•"),
    )
    assert rows[1].text == "Process each column."


def test_standalone_file_cache_builds_one_explanation(tmp_path: Path) -> None:
    *_, cache, identities, _callable_insights = sample_workspace(tmp_path)

    assert cache.get(identities["guarded"].symbol.symbol_id) is not None
    assert cache.size == 1


def test_project_cache_resolves_callables_across_modules(tmp_path: Path) -> None:
    (tmp_path / "first.py").write_text("def first():\n    return 1\n")
    (tmp_path / "second.py").write_text("def second():\n    return 2\n")
    analysis = analyze_project(tmp_path)
    cache = FlowExplanationCache()
    cache.set_analysis(analysis, analyze_insights(analysis))

    symbol_ids = (item.symbol.symbol_id for item in analysis.callable_identities)
    results = tuple(cache.get(symbol_id) for symbol_id in symbol_ids)

    assert all(result is not None for result in results)
    assert cache.size == 2


def synchronized_app(explanation: object):
    selection = InsightSelection("callable", "sample::choose")
    insights_panel = SimpleNamespace(
        select_callable=Mock(return_value=True),
        selection=selection,
        flow_explanation=explanation,
    )
    app = SimpleNamespace(
        flow_panel=SimpleNamespace(
            select_callable=Mock(return_value=True),
            render_selected=Mock(return_value=True),
        ),
        call_graph_panel=SimpleNamespace(select_root=Mock(return_value=True)),
        insights_panel=insights_panel,
        state=ApplicationState(),
        _syncing_callable_selection=False,
        _selected_callable_id=None,
        _highlight_callable_in_tree=Mock(),
    )
    app._select_callable_insight = MethodType(
        PySynopticApp._select_callable_insight,
        app,
    )
    return app


def test_callable_selection_synchronizes_explanation_reference() -> None:
    explanation = object()
    app = synchronized_app(explanation)

    PySynopticApp._synchronize_callable(
        app,
        "symbol-id",
        source="tree",
        render_flow=False,
    )

    assert app.insights_panel.flow_explanation is explanation


def test_calls_to_insights_retains_cached_explanation() -> None:
    explanation = object()
    app = synchronized_app(explanation)

    PySynopticApp._synchronize_callable(
        app,
        "symbol-id",
        source="calls",
        render_flow=False,
    )

    assert app.insights_panel.flow_explanation is explanation
    app.insights_panel.select_callable.assert_called_once_with("symbol-id")


def test_flow_to_insights_opens_same_callable() -> None:
    insights = SimpleNamespace(selected_callable_symbol_id="symbol-id")
    notebook = SimpleNamespace(select=Mock())
    app = SimpleNamespace(
        insights_panel=insights,
        notebook=notebook,
        _synchronize_callable=Mock(),
    )

    PySynopticApp._open_insights(app, "symbol-id")

    app._synchronize_callable.assert_called_once_with(
        "symbol-id", source="flow", render_flow=False
    )
    notebook.select.assert_called_once_with(insights)


def test_key_step_opens_flow_for_exact_callable() -> None:
    flow = SimpleNamespace(
        selected_symbol_id="symbol-id",
        highlight_node_ids=Mock(return_value=("node-1",)),
    )
    notebook = SimpleNamespace(select=Mock())
    app = SimpleNamespace(
        flow_panel=flow,
        notebook=notebook,
        _synchronize_callable=Mock(),
    )

    PySynopticApp._open_flow_step(app, "symbol-id", ("node-1",))

    app._synchronize_callable.assert_called_once_with(
        "symbol-id", source="insights", render_flow=True
    )
    flow.highlight_node_ids.assert_called_once_with(("node-1",))
    notebook.select.assert_called_once_with(flow)


def test_flow_panel_highlights_correct_source_node_ids() -> None:
    node = FlowNode("node-1", "return 1", "return", 2, 4, "return 1")
    panel = SimpleNamespace(
        current_flow=object(),
        canvas=SimpleNamespace(highlight_node_ids=Mock(return_value=("node-1",))),
        _nodes={"node-1": node},
        _show_flow_node=Mock(),
    )

    highlighted = FlowPanel.highlight_node_ids(panel, ("node-1",))

    assert highlighted == ("node-1",)
    panel._show_flow_node.assert_called_once_with(node)


def test_canvas_highlights_multiple_nodes_without_fit() -> None:
    canvas = SimpleNamespace(
        _nodes={"one": object(), "two": object()},
        _highlighted_ids=set(),
        _selected_id=None,
        _draw=Mock(),
        _update_status=Mock(),
    )

    highlighted = DependencyGraphCanvas.highlight_node_ids(
        canvas,
        ("one", "two", "one"),
    )

    assert highlighted == ("one", "two")
    assert canvas._highlighted_ids == {"one", "two"}
    canvas._draw.assert_called_once_with()


def test_canvas_ignores_unknown_node_ids_safely() -> None:
    canvas = SimpleNamespace(
        _nodes={"known": object()},
        _highlighted_ids=set(),
        _selected_id=None,
        _draw=Mock(),
        _update_status=Mock(),
    )

    highlighted = DependencyGraphCanvas.highlight_node_ids(canvas, ("missing",))

    assert highlighted == ()
    canvas._draw.assert_not_called()


def test_cache_returns_same_prebuilt_result(tmp_path: Path) -> None:
    *_, cache, identities, _callable_insights = sample_workspace(tmp_path)
    symbol_id = identities["add"].symbol.symbol_id

    assert cache.get(symbol_id) is cache.get(symbol_id)


def test_cache_does_not_rebuild_same_callable(tmp_path: Path) -> None:
    path, analysis, insights, _cache, identities, _items = sample_workspace(tmp_path)
    build = Mock(
        side_effect=lambda identity: analyze_callable_flow(path, identity.symbol)
    )
    cache = FlowExplanationCache(build_flow=build)
    cache.set_analysis(analysis, insights)
    symbol_id = identities["add"].symbol.symbol_id

    cache.get(symbol_id)
    cache.get(symbol_id)

    build.assert_called_once()


def test_cache_resets_on_new_analysis(tmp_path: Path) -> None:
    *_, analysis, insights, cache, identities, _items = sample_workspace(tmp_path)
    symbol_id = identities["add"].symbol.symbol_id
    cache.get(symbol_id)
    replacement = analyze_python_file_context(tmp_path / "sample.py")

    generation = cache.set_analysis(replacement, analyze_insights(replacement))

    assert generation == 2
    assert cache.size == 0
    assert cache.peek(symbol_id) is None


def test_stale_generation_result_is_rejected(tmp_path: Path) -> None:
    path, analysis, insights, _cache, identities, _items = sample_workspace(tmp_path)
    newer_path = tmp_path / "newer.py"
    newer_path.write_text("def newer():\n    return 1\n", encoding="utf-8")
    newer = analyze_python_file_context(newer_path)
    cache: FlowExplanationCache

    def build(identity):
        cache.set_analysis(newer, analyze_insights(newer))
        return analyze_callable_flow(path, identity.symbol)

    cache = FlowExplanationCache(build_flow=build)
    cache.set_analysis(analysis, insights)

    assert cache.get(identities["add"].symbol.symbol_id) is None
    assert cache.size == 0


def test_lazy_cache_creates_no_background_thread(tmp_path: Path) -> None:
    before = {thread.ident for thread in threading.enumerate()}
    *_, cache, identities, _items = sample_workspace(tmp_path)

    cache.get(identities["choose"].symbol.symbol_id)

    assert {thread.ident for thread in threading.enumerate()} == before


def test_module_and_class_insights_remain_without_flow_content(tmp_path: Path) -> None:
    *_prefix, insights, _cache, _identities, _items = sample_workspace(tmp_path)
    module = insights.modules[0]

    presentation = present_insight(
        InsightSelection("module", module.identity),
        module,
    )

    assert presentation.flow_explanation is None
    assert presentation.purpose == module.purpose


def test_existing_calls_and_flow_navigation_plan_is_unchanged() -> None:
    calls = plan_callable_navigation("symbol", source="calls", render_flow=False)
    flow = plan_callable_navigation("symbol", source="flow", render_flow=True)

    assert (calls.update_calls, calls.update_flow, calls.render_flow) == (
        False,
        True,
        False,
    )
    assert (flow.update_calls, flow.update_flow, flow.render_flow) == (
        True,
        False,
        True,
    )


def test_lazy_flow_explanation_never_executes_source(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    path = tmp_path / "unsafe.py"
    path.write_text(
        f"Path({str(marker)!r}).write_text('bad')\ndef run():\n    return 1\n",
        encoding="utf-8",
    )
    analysis = analyze_python_file_context(path)
    cache = FlowExplanationCache()
    cache.set_analysis(analysis, analyze_insights(analysis))

    cache.get(analysis.callable_identities[0].symbol.symbol_id)

    assert not marker.exists()


def test_lazy_flow_explanation_makes_no_network_or_ai_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    *_, cache, identities, _items = sample_workspace(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "create_connection", forbidden)

    assert cache.get(identities["add"].symbol.symbol_id) is not None
