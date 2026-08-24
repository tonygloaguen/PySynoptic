from __future__ import annotations

from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, call

from pysynoptic import analyze_project, analyze_python_file_context
from pysynoptic.graph import GraphNode
from pysynoptic.gui.app import PySynopticApp
from pysynoptic.gui.call_graph import ContextualCallGraphPanel
from pysynoptic.gui.project_tree import (
    ProjectTreeNode,
    build_project_tree,
    callable_relation_context,
    callable_selector_options,
    plan_callable_navigation,
)


def write_python(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def child(node: ProjectTreeNode, label: str) -> ProjectTreeNode:
    return next(item for item in node.children if item.label == label)


def descendant(node: ProjectTreeNode, label: str) -> ProjectTreeNode:
    if node.label == label:
        return node
    return next(
        result
        for item in node.children
        if (result := _descendant_or_none(item, label)) is not None
    )


def _descendant_or_none(node: ProjectTreeNode, label: str) -> ProjectTreeNode | None:
    if node.label == label:
        return node
    return next(
        (
            result
            for item in node.children
            if (result := _descendant_or_none(item, label)) is not None
        ),
        None,
    )


def test_standalone_tree_groups_classes_methods_and_functions(tmp_path: Path) -> None:
    path = write_python(
        tmp_path / "standalone.py",
        (
            "class Risk:\n"
            "    def score(self):\n        return 1\n"
            "class Remediation:\n"
            "    def render(self):\n        return None\n"
            "def helper():\n    return None\n"
            "def main():\n"
            "    def nested():\n        return None\n"
            "    return nested()\n"
        ),
    )
    analysis = analyze_python_file_context(path)

    tree = build_project_tree(path, "file", analysis)

    assert tree.label == "standalone.py"
    assert [item.label for item in tree.children] == ["Classes", "Functions"]
    classes = child(tree, "Classes")
    assert [item.label for item in classes.children] == ["Remediation", "Risk"]
    assert [item.label for item in child(classes, "Risk").children] == ["score()"]
    functions = child(tree, "Functions")
    assert [item.label for item in functions.children] == ["helper()", "main()"]
    assert [item.label for item in child(functions, "main()").children] == ["nested()"]
    assert descendant(tree, "render()").symbol_id is not None
    assert descendant(tree, "main()").symbol_id is not None


def test_project_tree_preserves_paths_and_adds_callables_below_files(
    tmp_path: Path,
) -> None:
    path = write_python(
        tmp_path / "src" / "package" / "analyzer" / "project.py",
        "def analyze_project():\n    return None\n",
    )
    analysis = analyze_project(tmp_path)

    tree = build_project_tree(tmp_path, "project", analysis)

    project_file = descendant(tree, "project.py")
    assert project_file.path == path
    assert child(child(project_file, "Functions"), "analyze_project()").symbol_id
    assert descendant(tree, "src").kind == "directory"
    assert descendant(tree, "package").kind == "directory"


def test_selector_uses_short_labels_and_disambiguates_modules(tmp_path: Path) -> None:
    single = write_python(
        tmp_path / "single.py",
        (
            "class Runner:\n"
            "    async def run(self):\n        pass\n"
            "def main():\n    pass\n"
        ),
    )
    single_analysis = analyze_python_file_context(single)

    assert [option.label for option in callable_selector_options(single_analysis)] == [
        "main()",
        "Runner.run()",
    ]

    project = tmp_path / "project"
    write_python(project / "alpha.py", "def main():\n    pass\n")
    write_python(project / "beta.py", "def main():\n    pass\n")
    labels = [
        option.label for option in callable_selector_options(analyze_project(project))
    ]
    assert labels == ["main() — alpha", "main() — beta"]


def test_flow_relation_context_uses_only_resolved_dependencies(
    tmp_path: Path,
) -> None:
    path = write_python(
        tmp_path / "pipeline.py",
        (
            "def helper():\n    return None\n"
            "def main():\n    helper()\n    missing()\n"
            "main()\n"
        ),
    )
    analysis = analyze_python_file_context(path)
    identities = {item.symbol.name: item for item in analysis.callable_identities}

    main_context = callable_relation_context(
        analysis, identities["main"].symbol.symbol_id
    )
    helper_context = callable_relation_context(
        analysis, identities["helper"].symbol.symbol_id
    )

    assert [item.label for item in main_context.incoming] == ["<module>"]
    assert [item.label for item in main_context.outgoing] == ["helper()"]
    assert [item.label for item in helper_context.incoming] == ["main()"]
    assert all(item.label != "missing()" for item in main_context.outgoing)


def test_calls_to_flow_navigation_preserves_exact_callable() -> None:
    plan = plan_callable_navigation(
        "callable-id",
        source="flow",
        render_flow=True,
    )

    assert plan.symbol_id == "callable-id"
    assert plan.update_calls is True
    assert plan.update_flow is False
    assert plan.render_flow is True


def test_flow_to_calls_navigation_preserves_exact_callable() -> None:
    plan = plan_callable_navigation(
        "callable-id",
        source="calls",
        render_flow=False,
    )

    assert plan.symbol_id == "callable-id"
    assert plan.update_calls is False
    assert plan.update_flow is True
    assert plan.render_flow is False


def test_double_clicking_call_node_opens_exact_flow() -> None:
    panel = SimpleNamespace(
        select_root=Mock(return_value=True),
        _open_selected_flow=Mock(),
    )
    node = GraphNode("callable-id", "target()", Path("target.py"))

    ContextualCallGraphPanel._activate_node(panel, node)

    panel.select_root.assert_called_once_with("callable-id")
    panel._open_selected_flow.assert_called_once_with()


def test_app_synchronizes_calls_to_flow_and_back_without_tk() -> None:
    flow = SimpleNamespace(
        select_callable=Mock(return_value=True),
        render_selected=Mock(return_value=True),
    )
    calls = SimpleNamespace(select_root=Mock(return_value=True))
    insights = SimpleNamespace(
        select_callable=Mock(return_value=False),
        selection=None,
    )
    notebook = SimpleNamespace(select=Mock())
    app = SimpleNamespace(
        flow_panel=flow,
        call_graph_panel=calls,
        insights_panel=insights,
        state=SimpleNamespace(),
        notebook=notebook,
        _syncing_callable_selection=False,
        _selected_callable_id=None,
        _highlight_callable_in_tree=Mock(),
    )
    app._synchronize_callable = MethodType(PySynopticApp._synchronize_callable, app)
    app._select_callable_insight = MethodType(
        PySynopticApp._select_callable_insight, app
    )

    PySynopticApp._open_flow(app, "first-id")
    PySynopticApp._open_calls(app, "second-id")

    assert app._selected_callable_id == "second-id"
    flow.select_callable.assert_any_call("first-id", notify=False)
    flow.select_callable.assert_any_call(
        "second-id",
        render=False,
        notify=False,
    )
    calls.select_root.assert_any_call("first-id", notify=False)
    calls.select_root.assert_any_call("second-id", notify=False)
    assert notebook.select.call_args_list[-2:] == [call(flow), call(calls)]
