from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Event
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest

from pysynoptic.gui.analysis_runner import AnalysisRunner
from pysynoptic.gui.app import APPLICATION_TAB_ORDER, PySynopticApp
from pysynoptic.gui.controller import ApplicationController
from pysynoptic.gui.insights import (
    InsightCatalog,
    InsightSelection,
    InsightsPanel,
    evidence_lines,
    present_insight,
)
from pysynoptic.gui.project_tree import ProjectTreeNode, build_project_tree
from pysynoptic.gui.state import ApplicationState
from pysynoptic.insights import (
    CallableInsight,
    ClassInsight,
    EvidenceCategory,
    EvidenceStrength,
    InsightAnalysis,
    InsightConfidence,
    InsightEvidence,
    InsightInput,
    InsightRole,
    ModuleInsight,
    PurposeSource,
)


def insight_evidence() -> tuple[InsightEvidence, ...]:
    return (
        InsightEvidence(
            EvidenceCategory.NAMING,
            "name_token:render",
            'Callable name contains token "render"',
            EvidenceStrength.SUPPORTING,
        ),
        InsightEvidence(
            EvidenceCategory.SIGNATURE,
            "return_annotation",
            'Return annotation is "str"',
            EvidenceStrength.STRONG,
            reference="str",
        ),
    )


def callable_insight(**changes) -> CallableInsight:
    values = {
        "identity": "sample::render_markdown",
        "display_name": "render_markdown()",
        "module": "sample",
        "path": Path("sample.py"),
        "symbol_id": "sample.py::render_markdown@1:0",
        "qualified_name": "render_markdown",
        "kind": "function",
        "is_async": False,
        "source_line": 1,
        "role": InsightRole.RENDERER,
        "secondary_roles": (),
        "purpose": "Render Markdown output.",
        "purpose_source": PurposeSource.ROLE_TEMPLATE,
        "confidence": InsightConfidence.MEDIUM,
        "responsibilities": ("Call default_remediation()",),
        "inputs": (InsightInput("risks", "positional", "list[Risk]"),),
        "outputs": ("str",),
        "side_effects": (),
        "callers": ("sample::main",),
        "callees": ("sample::default_remediation",),
        "evidence": insight_evidence(),
        "supporting_evidence": insight_evidence(),
    }
    values.update(changes)
    return CallableInsight(**values)


def module_insight(**changes) -> ModuleInsight:
    values = {
        "identity": "sample",
        "display_name": "sample",
        "path": Path("sample.py"),
        "role": InsightRole.UNKNOWN,
        "secondary_roles": (),
        "purpose": "Sample module declarations.",
        "purpose_source": PurposeSource.DOCSTRING,
        "confidence": InsightConfidence.UNKNOWN,
        "responsibilities": ("Define 2 functions", "Define 1 class"),
        "evidence": insight_evidence(),
    }
    values.update(changes)
    return ModuleInsight(**values)


def class_insight(**changes) -> ClassInsight:
    values = {
        "identity": "sample::Record",
        "display_name": "Record",
        "module": "sample",
        "path": Path("sample.py"),
        "qualified_name": "Record",
        "role": InsightRole.MODEL,
        "secondary_roles": (),
        "purpose": "Represent record data.",
        "purpose_source": PurposeSource.STRUCTURE,
        "confidence": InsightConfidence.HIGH,
        "responsibilities": ("Declare 2 fields",),
        "evidence": insight_evidence(),
        "is_dataclass": True,
        "field_count": 2,
        "method_count": 1,
    }
    values.update(changes)
    return ClassInsight(**values)


def insight_analysis(*callables: CallableInsight) -> InsightAnalysis:
    return InsightAnalysis(
        modules=(module_insight(),),
        classes=(class_insight(),),
        callables=callables or (callable_insight(),),
    )


def descendant(node: ProjectTreeNode, label: str) -> ProjectTreeNode:
    if node.label == label:
        return node
    for child in node.children:
        try:
            return descendant(child, label)
        except LookupError:
            pass
    raise LookupError(label)


def wait_for_result(runner: AnalysisRunner) -> ApplicationState:
    pause = Event()
    for _ in range(5000):
        result = runner.poll_latest()
        if result is not None:
            return result
        pause.wait(0.001)
    pytest.fail("background Insights analysis did not complete")


def test_insights_tab_exists_in_expected_order() -> None:
    assert APPLICATION_TAB_ORDER == (
        "Overview",
        "Architecture",
        "Calls",
        "Flow",
        "Insights",
        "Dependencies",
        "Mermaid",
    )


def test_catalog_selects_callable_by_stable_identity() -> None:
    expected = callable_insight()
    catalog = InsightCatalog(insight_analysis(expected))

    assert catalog.find(InsightSelection("callable", expected.identity)) is expected


def test_catalog_selects_module_by_stable_identity() -> None:
    analysis = insight_analysis()

    assert (
        InsightCatalog(analysis).find(InsightSelection("module", "sample"))
        is (analysis.modules[0])
    )


def test_catalog_selects_class_by_stable_identity() -> None:
    analysis = insight_analysis()

    assert (
        InsightCatalog(analysis).find(InsightSelection("class", "sample::Record"))
        is analysis.classes[0]
    )


def test_catalog_maps_existing_callable_symbol_id() -> None:
    expected = callable_insight()

    assert (
        InsightCatalog(insight_analysis(expected)).callable_for_symbol(
            expected.symbol_id
        )
        is expected
    )


def test_tree_exposes_module_class_and_callable_insight_keys(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "class Record:\n    def method(self):\n        return None\n"
        "def render_markdown():\n    return ''\n",
        encoding="utf-8",
    )
    state = ApplicationController().analyze(ApplicationController().select_path(source))

    tree = build_project_tree(source, "file", state.project_analysis)

    assert tree.insight_kind == "module"
    assert tree.insight_identity == "sample"
    assert descendant(tree, "Record").insight_identity == "sample::Record"
    assert descendant(tree, "method()").insight_kind == "callable"
    assert descendant(tree, "render_markdown()").insight_identity == (
        "sample::render_markdown"
    )


def synchronized_app() -> SimpleNamespace:
    selection = InsightSelection("callable", "sample::target")
    insights = SimpleNamespace(
        select_callable=Mock(return_value=True),
        selection=selection,
    )
    app = SimpleNamespace(
        flow_panel=SimpleNamespace(
            select_callable=Mock(return_value=True),
            render_selected=Mock(return_value=True),
        ),
        call_graph_panel=SimpleNamespace(select_root=Mock(return_value=True)),
        insights_panel=insights,
        state=ApplicationState(),
        _syncing_callable_selection=False,
        _selected_callable_id=None,
        _highlight_callable_in_tree=Mock(),
    )
    app._select_callable_insight = MethodType(
        PySynopticApp._select_callable_insight, app
    )
    return app


def test_calls_selection_synchronizes_insights() -> None:
    app = synchronized_app()

    PySynopticApp._synchronize_callable(
        app,
        "symbol-id",
        source="calls",
        render_flow=False,
    )

    app.insights_panel.select_callable.assert_called_once_with("symbol-id")
    assert app.state.selected_insight_identity == "sample::target"


def test_flow_selection_synchronizes_insights() -> None:
    app = synchronized_app()

    PySynopticApp._synchronize_callable(
        app,
        "symbol-id",
        source="flow",
        render_flow=True,
    )

    app.insights_panel.select_callable.assert_called_once_with("symbol-id")
    assert app.state.selected_insight_kind == "callable"


def test_tree_class_selection_opens_insights() -> None:
    panel = object()
    app = SimpleNamespace(
        _syncing_tree_selection=False,
        project_tree=SimpleNamespace(selection=Mock(return_value=("item",))),
        _pending_tree_selection=None,
        _tree_callable_nodes={},
        _tree_insight_nodes={"item": ("class", "sample::Record")},
        _tree_graph_nodes={},
        _select_insight=Mock(return_value=True),
        notebook=SimpleNamespace(select=Mock()),
        insights_panel=panel,
    )

    PySynopticApp._navigate_tree_to_graph(app, None)

    app._select_insight.assert_called_once_with("class", "sample::Record")
    app.notebook.select.assert_called_once_with(panel)


def test_tree_module_selection_keeps_architecture_navigation() -> None:
    architecture = SimpleNamespace(select_root=Mock(return_value=True))
    app = SimpleNamespace(
        _syncing_tree_selection=False,
        project_tree=SimpleNamespace(selection=Mock(return_value=("item",))),
        _pending_tree_selection=None,
        _tree_callable_nodes={},
        _tree_insight_nodes={"item": ("module", "sample")},
        _tree_graph_nodes={"item": "/sample.py"},
        _select_insight=Mock(return_value=True),
        notebook=SimpleNamespace(select=Mock()),
        architecture_panel=architecture,
    )

    PySynopticApp._navigate_tree_to_graph(app, None)

    app._select_insight.assert_called_once_with("module", "sample")
    architecture.select_root.assert_called_once_with("/sample.py")


def test_insights_show_in_calls_uses_current_symbol() -> None:
    callback = Mock()
    panel = SimpleNamespace(
        selected_callable_symbol_id="symbol-id",
        _on_show_calls=callback,
    )

    InsightsPanel._show_calls(panel)

    callback.assert_called_once_with("symbol-id")


def test_insights_open_flow_uses_current_symbol() -> None:
    callback = Mock()
    panel = SimpleNamespace(
        selected_callable_symbol_id="symbol-id",
        _on_open_flow=callback,
    )

    InsightsPanel._open_flow(panel)

    callback.assert_called_once_with("symbol-id")


def test_high_confidence_display_is_explanatory() -> None:
    item = class_insight()
    presentation = present_insight(InsightSelection("class", item.identity), item)

    assert presentation.confidence == "HIGH"
    assert presentation.confidence_description == ("Multiple converging static signals")


def test_medium_confidence_display_is_not_alarmist() -> None:
    item = callable_insight()
    presentation = present_insight(InsightSelection("callable", item.identity), item)

    assert presentation.confidence == "MEDIUM"
    assert presentation.confidence_description == (
        "Useful static evidence, with limitations"
    )


def test_unknown_display_remains_structurally_useful() -> None:
    item = callable_insight(
        role=InsightRole.UNKNOWN,
        confidence=InsightConfidence.UNKNOWN,
        purpose=None,
        purpose_source=PurposeSource.NONE,
    )
    presentation = present_insight(InsightSelection("callable", item.identity), item)

    assert presentation.role == "UNKNOWN"
    assert presentation.purpose == "No reliable purpose identified."
    assert next(
        section for section in presentation.sections if section.title == "Inputs"
    )


@pytest.mark.parametrize(
    ("source", "label"),
    [
        (PurposeSource.DOCSTRING, "Declared by docstring"),
        (PurposeSource.ROLE_TEMPLATE, "Statically inferred"),
        (PurposeSource.STRUCTURE, "Structural summary"),
        (PurposeSource.NONE, "No reliable purpose identified"),
    ],
)
def test_purpose_source_display(source: PurposeSource, label: str) -> None:
    item = callable_insight(purpose_source=source)

    assert (
        present_insight(
            InsightSelection("callable", item.identity), item
        ).purpose_source
        == label
    )


def test_callable_inputs_distinguish_receiver() -> None:
    item = callable_insight(
        kind="method",
        inputs=(
            InsightInput("self", "positional"),
            InsightInput("path", "positional", "Path"),
        ),
    )
    presentation = present_insight(InsightSelection("callable", item.identity), item)
    sections = {section.title: section.items for section in presentation.sections}

    assert sections["Receiver"] == ("self",)
    assert sections["Inputs"] == ("path\n  Type: Path",)


def test_outputs_and_side_effects_preserve_engine_text() -> None:
    item = callable_insight(
        outputs=("ProjectAnalysis",),
        side_effects=(
            "Contains Path.read_text() call",
            "Contains raise syntax for ValueError",
        ),
    )
    presentation = present_insight(InsightSelection("callable", item.identity), item)
    sections = {section.title: section.items for section in presentation.sections}

    assert sections["Outputs"] == ("ProjectAnalysis",)
    assert sections["Side effects"] == item.side_effects


def test_callers_and_callees_are_presented_without_module_prefix() -> None:
    item = callable_insight(
        callers=("sample::main",),
        callees=("sample::parse", "sample::render"),
    )
    presentation = present_insight(InsightSelection("callable", item.identity), item)
    sections = {section.title: section.items for section in presentation.sections}

    assert sections["Called by"] == ("main",)
    assert sections["Calls"] == ("parse", "render")


def test_evidence_count_and_exact_content_are_preserved() -> None:
    item = callable_insight()
    presentation = present_insight(InsightSelection("callable", item.identity), item)

    assert len(presentation.evidence) == 2
    assert evidence_lines(presentation.evidence) == (
        "Naming",
        '[SUPPORTING] Callable name contains token "render"',
        "",
        "Signature",
        '[STRONG] Return annotation is "str"',
    )


def test_selection_changes_reuse_prebuilt_insight_objects() -> None:
    first = callable_insight()
    second = callable_insight(
        identity="sample::other",
        symbol_id="sample.py::other@2:0",
        qualified_name="other",
        display_name="other()",
    )
    catalog = InsightCatalog(insight_analysis(first, second))

    assert catalog.find(InsightSelection("callable", first.identity)) is first
    assert catalog.find(InsightSelection("callable", second.identity)) is second
    assert catalog.find(InsightSelection("callable", first.identity)) is first


def test_standalone_analysis_populates_insights_on_worker(tmp_path: Path) -> None:
    source = tmp_path / "standalone.py"
    source.write_text("def main():\n    return 0\n", encoding="utf-8")
    controller = ApplicationController()
    runner = AnalysisRunner(controller.analyze)

    runner.submit(controller.select_path(source))
    result = wait_for_result(runner)

    assert result.insight_analysis is not None
    assert result.insight_analysis.callables[0].identity == "standalone::main"
    runner.shutdown(wait=True)


def test_project_analysis_populates_insights(tmp_path: Path) -> None:
    (tmp_path / "first.py").write_text("def first():\n    pass\n", encoding="utf-8")
    (tmp_path / "second.py").write_text("def second():\n    pass\n", encoding="utf-8")
    controller = ApplicationController()

    result = controller.analyze(controller.select_path(tmp_path))

    assert result.insight_analysis is not None
    assert tuple(item.identity for item in result.insight_analysis.modules) == (
        "first",
        "second",
    )


def test_insights_are_built_once_per_controller_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "sample.py"
    source.write_text("def run():\n    pass\n", encoding="utf-8")
    completed = insight_analysis()
    analyze = Mock(return_value=completed)
    monkeypatch.setattr("pysynoptic.gui.controller.analyze_insights", analyze)
    controller = ApplicationController()

    result = controller.analyze(controller.select_path(source))

    assert result.insight_analysis is completed
    analyze.assert_called_once_with(result.project_analysis)


def test_stale_generation_cannot_overwrite_newer_insights() -> None:
    releases = {"old": Event(), "new": Event()}
    started = {"old": Event(), "new": Event()}

    def analyze(state: ApplicationState) -> ApplicationState:
        name = state.selected_path.name
        started[name].set()
        releases[name].wait()
        insight = InsightAnalysis(
            modules=(module_insight(identity=name, display_name=name),),
            classes=(),
            callables=(),
        )
        return replace(state, insight_analysis=insight)

    runner = AnalysisRunner(analyze)
    runner.submit(ApplicationState(selected_path=Path("/old"), target_kind="project"))
    assert started["old"].wait(5)
    runner.submit(ApplicationState(selected_path=Path("/new"), target_kind="project"))
    assert started["new"].wait(5)
    releases["old"].set()
    releases["new"].set()

    result = wait_for_result(runner)

    assert result.insight_analysis.modules[0].identity == "new"
    runner.shutdown(wait=True)


def test_clean_shutdown_rejects_new_insight_work() -> None:
    runner = AnalysisRunner(lambda state: state)

    runner.shutdown()

    assert runner.closed
    with pytest.raises(RuntimeError, match="closed"):
        runner.submit(ApplicationState())
