"""Deterministic Mermaid rendering for project module dependencies."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal, TypeAlias

from pysynoptic.graph.layout import DependencyGraph
from pysynoptic.models import ModuleIdentity, ProjectAnalysis

MermaidDirection: TypeAlias = Literal["BT", "LR", "RL", "TB", "TD"]
MermaidExportMode: TypeAlias = Literal["architecture", "calls", "flow", "whole"]
_DIRECTIONS = frozenset({"BT", "LR", "RL", "TB", "TD"})
_UNSAFE_IDENTIFIER = re.compile(r"[^A-Za-z0-9_]")


def _relative_path(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def _identity_sort_key(identity: ModuleIdentity, root: Path) -> tuple[str, ...]:
    return (
        identity.dotted_name.casefold(),
        identity.dotted_name,
        _relative_path(identity.path, root).as_posix(),
    )


def _identifier(prefix: str, label: str) -> str:
    sanitized = _UNSAFE_IDENTIFIER.sub("_", label).strip("_") or "root"
    return f"{prefix}_{sanitized}"


def _node_identifiers(
    identities: tuple[ModuleIdentity, ...], root: Path
) -> dict[Path, str]:
    bases: dict[str, list[ModuleIdentity]] = {}
    for identity in identities:
        base = _identifier("module", identity.dotted_name)
        bases.setdefault(base, []).append(identity)

    identifiers = {}
    for base, matching_identities in bases.items():
        if len(matching_identities) == 1:
            identifiers[matching_identities[0].path] = base
            continue
        for identity in matching_identities:
            relative_path = _relative_path(identity.path, root).as_posix()
            suffix = hashlib.sha256(relative_path.encode()).hexdigest()[:10]
            identifiers[identity.path] = f"{base}_{suffix}"
    return identifiers


def _escape_label(label: str) -> str:
    return label.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def render_mermaid(
    analysis: ProjectAnalysis,
    *,
    direction: MermaidDirection = "LR",
    group_by_package: bool = True,
) -> str:
    """Render a project dependency graph as deterministic Mermaid text."""
    if direction not in _DIRECTIONS:
        raise ValueError(f"Unsupported Mermaid direction: {direction}")

    identities = tuple(
        sorted(
            analysis.module_identities,
            key=lambda identity: _identity_sort_key(identity, analysis.root_path),
        )
    )
    node_ids = _node_identifiers(identities, analysis.root_path)
    groups: dict[str, list[ModuleIdentity]] = {}
    for identity in identities:
        group = identity.dotted_name.partition(".")[0]
        groups.setdefault(group, []).append(identity)

    lines = [f"flowchart {direction}"]
    for group_name in sorted(groups, key=lambda name: (name.casefold(), name)):
        group = groups[group_name]
        use_subgraph = group_by_package and len(group) > 1
        if use_subgraph:
            group_id = _identifier("package", group_name)
            lines.append(f'  subgraph {group_id}["{_escape_label(group_name)}"]')
        indentation = "    " if use_subgraph else "  "
        for identity in group:
            node_id = node_ids[identity.path]
            label = _escape_label(identity.dotted_name)
            lines.append(f'{indentation}{node_id}["{label}"]')
        if use_subgraph:
            lines.append("  end")

    dependencies = sorted(
        analysis.dependencies,
        key=lambda dependency: (
            _identity_sort_key(dependency.source, analysis.root_path),
            _identity_sort_key(dependency.target, analysis.root_path),
        ),
    )
    for dependency in dependencies:
        lines.append(
            f"  {node_ids[dependency.source.path]} -->|imports| "
            f"{node_ids[dependency.target.path]}"
        )
    return "\n".join(lines) + "\n"


def render_graph_mermaid(
    graph: DependencyGraph,
    *,
    direction: MermaidDirection = "TD",
) -> str:
    """Render the current renderer-independent graph with labeled edges."""
    if direction not in _DIRECTIONS:
        raise ValueError(f"Unsupported Mermaid direction: {direction}")
    identifiers = {
        node.node_id: f"node_{hashlib.sha256(node.node_id.encode()).hexdigest()[:12]}"
        for node in graph.nodes
    }
    lines = [f"flowchart {direction}"]
    for node in sorted(
        graph.nodes, key=lambda item: (item.label.casefold(), item.label, item.node_id)
    ):
        lines.append(f'  {identifiers[node.node_id]}["{_escape_label(node.label)}"]')
    for edge in sorted(
        graph.edges,
        key=lambda item: (item.source_id, item.target_id, item.label),
    ):
        label = _escape_label(edge.label or "relates")
        lines.append(
            f"  {identifiers[edge.source_id]} -->|{label}| "
            f"{identifiers[edge.target_id]}"
        )
    return "\n".join(lines) + "\n"


def render_mermaid_export(
    mode: MermaidExportMode,
    analysis: ProjectAnalysis,
    current_graph: DependencyGraph | None = None,
) -> str:
    """Render one explicit GUI export mode without depending on Tk widgets."""
    if mode == "whole":
        return render_mermaid(analysis)
    if mode not in {"architecture", "calls", "flow"}:
        raise ValueError(f"Unsupported Mermaid export mode: {mode}")
    if current_graph is None:
        raise ValueError(f"No current {mode} graph to export")
    return render_graph_mermaid(current_graph)


def write_mermaid(
    analysis: ProjectAnalysis,
    output_path: Path,
    *,
    direction: MermaidDirection = "LR",
    group_by_package: bool = True,
) -> Path:
    """Write a deterministic Mermaid graph and return its output path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_mermaid(
            analysis,
            direction=direction,
            group_by_package=group_by_package,
        ),
        encoding="utf-8",
    )
    return output_path
