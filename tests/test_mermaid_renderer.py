from pathlib import Path

import pytest

from pysynoptic import analyze_project
from pysynoptic.graph import DependencyGraph, GraphEdge, GraphNode
from pysynoptic.models import ModuleIdentity, ProjectAnalysis
from pysynoptic.renderers import render_graph_mermaid, render_mermaid, write_mermaid


def write_python(path: Path, source: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def sample_analysis(tmp_path: Path) -> ProjectAnalysis:
    write_python(
        tmp_path / "package" / "__init__.py",
        "from package import service\n",
    )
    write_python(tmp_path / "package" / "service.py", "value = 1\n")
    return analyze_project(tmp_path)


def test_renders_exact_deterministic_mermaid_text(tmp_path: Path) -> None:
    analysis = sample_analysis(tmp_path)

    rendered = render_mermaid(analysis)

    assert rendered == (
        "flowchart LR\n"
        '  subgraph package_package["package"]\n'
        '    module_package["package"]\n'
        '    module_package_service["package.service"]\n'
        "  end\n"
        "  module_package -->|imports| module_package_service\n"
    )


def test_supports_direction_and_disabled_grouping(tmp_path: Path) -> None:
    analysis = sample_analysis(tmp_path)

    rendered = render_mermaid(
        analysis,
        direction="TD",
        group_by_package=False,
    )

    assert "flowchart TD\n" in rendered
    assert "subgraph" not in rendered
    assert '  module_package["package"]\n' in rendered


def test_renders_isolated_modules(tmp_path: Path) -> None:
    write_python(tmp_path / "standalone.py")

    rendered = render_mermaid(analyze_project(tmp_path))

    assert rendered == 'flowchart LR\n  module_standalone["standalone"]\n'


def test_node_identifiers_remain_unique_after_sanitizing(tmp_path: Path) -> None:
    first = ModuleIdentity(tmp_path / "first.py", "package-name", tmp_path)
    second = ModuleIdentity(tmp_path / "second.py", "package_name", tmp_path)
    analysis = ProjectAnalysis(
        root_path=tmp_path,
        module_identities=(first, second),
    )

    rendered = render_mermaid(analysis)
    node_lines = [line for line in rendered.splitlines() if '["package' in line]

    assert len(node_lines) == 2
    assert node_lines[0].split("[")[0] != node_lines[1].split("[")[0]


def test_rendering_is_repeatable_and_uses_only_analysis_model(tmp_path: Path) -> None:
    missing_source = tmp_path / "missing.py"
    identity = ModuleIdentity(missing_source, "missing", tmp_path)
    analysis = ProjectAnalysis(
        root_path=tmp_path,
        module_identities=(identity,),
    )

    first = render_mermaid(analysis)
    second = render_mermaid(analysis)

    assert first == second == 'flowchart LR\n  module_missing["missing"]\n'
    assert not missing_source.exists()


def test_writes_identical_mermaid_output_repeatedly(tmp_path: Path) -> None:
    analysis = sample_analysis(tmp_path)
    output_path = tmp_path / "docs" / "dependencies.mmd"

    returned_path = write_mermaid(analysis, output_path)
    first = output_path.read_text(encoding="utf-8")
    write_mermaid(analysis, output_path)
    second = output_path.read_text(encoding="utf-8")

    assert returned_path == output_path
    assert first == second == render_mermaid(analysis)


def test_rejects_unsupported_direction(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported Mermaid direction"):
        render_mermaid(ProjectAnalysis(root_path=tmp_path), direction="XX")  # type: ignore[arg-type]


def test_renders_current_graph_with_short_nodes_and_labeled_edges(
    tmp_path: Path,
) -> None:
    graph = DependencyGraph(
        nodes=(
            GraphNode("long::caller", "caller()", tmp_path / "file.py"),
            GraphNode("long::callee", "callee()", tmp_path / "file.py"),
        ),
        edges=(GraphEdge("long::caller", "long::callee", "calls"),),
    )

    rendered = render_graph_mermaid(graph)

    assert rendered.startswith("flowchart TD\n")
    assert '["caller()"]' in rendered
    assert '["callee()"]' in rendered
    assert "-->|calls|" in rendered
    assert "long::" not in rendered
