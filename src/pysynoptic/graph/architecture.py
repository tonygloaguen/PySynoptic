"""Focused module-architecture graphs and cycle diagnostics."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from pysynoptic.graph.layout import (
    DependencyGraph,
    GraphEdge,
    GraphNode,
    build_dependency_graph,
    strongly_connected_components,
)
from pysynoptic.models import ModuleIdentity, ProjectAnalysis

ArchitectureDirection: TypeAlias = Literal["outgoing", "incoming", "both"]


@dataclass(frozen=True, slots=True)
class ArchitectureRoot:
    """A selectable internal module."""

    root_id: str
    label: str
    path: Path


@dataclass(frozen=True, slots=True)
class ModuleDetails:
    """Human-readable static facts for one module."""

    module: str
    path: Path
    dependencies: tuple[str, ...]
    imported_by: tuple[str, ...]
    external_imports: tuple[str, ...]
    unresolved_imports: tuple[str, ...]
    functions: tuple[str, ...]
    classes: tuple[str, ...]
    cycle_number: int | None
    cycle_modules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContextualArchitectureGraph:
    """A bounded module graph around one selected module."""

    root: ArchitectureRoot
    direction: ArchitectureDirection
    depth: int
    graph: DependencyGraph
    cycle_count: int
    cyclic_node_ids: frozenset[str]


def architecture_roots(analysis: ProjectAnalysis) -> tuple[ArchitectureRoot, ...]:
    """Return deterministic module choices."""
    return tuple(
        ArchitectureRoot(item.path.as_posix(), item.dotted_name, item.path)
        for item in sorted(
            analysis.module_identities,
            key=lambda item: (item.dotted_name.casefold(), item.dotted_name),
        )
    )


def search_architecture_roots(
    analysis: ProjectAnalysis, query: str
) -> tuple[ArchitectureRoot, ...]:
    """Find modules by case-insensitive substring."""
    normalized = query.strip().casefold()
    roots = architecture_roots(analysis)
    return tuple(root for root in roots if normalized in root.label.casefold())


def _cycle_data(
    graph: DependencyGraph,
) -> tuple[tuple[tuple[str, ...], ...], frozenset[str]]:
    edge_pairs = {(edge.source_id, edge.target_id) for edge in graph.edges}
    cycles = tuple(
        component
        for component in strongly_connected_components(graph)
        if len(component) > 1 or (component[0], component[0]) in edge_pairs
    )
    return cycles, frozenset(node for component in cycles for node in component)


def _focused(
    graph: DependencyGraph,
    root_id: str,
    direction: ArchitectureDirection,
    depth: int,
) -> DependencyGraph:
    outgoing: dict[str, list[GraphEdge]] = {node.node_id: [] for node in graph.nodes}
    incoming: dict[str, list[GraphEdge]] = {node.node_id: [] for node in graph.nodes}
    for edge in graph.edges:
        outgoing[edge.source_id].append(edge)
        incoming[edge.target_id].append(edge)
    visible = {root_id}
    visible_edges: set[GraphEdge] = set()
    queue = deque(((root_id, 0),))
    while queue:
        node_id, distance = queue.popleft()
        if distance >= depth:
            continue
        candidates: list[tuple[GraphEdge, str]] = []
        if direction in {"outgoing", "both"}:
            candidates.extend((edge, edge.target_id) for edge in outgoing[node_id])
        if direction in {"incoming", "both"}:
            candidates.extend((edge, edge.source_id) for edge in incoming[node_id])
        for edge, neighbor in candidates:
            visible_edges.add(edge)
            if neighbor not in visible:
                visible.add(neighbor)
                queue.append((neighbor, distance + 1))
    return DependencyGraph(
        tuple(node for node in graph.nodes if node.node_id in visible),
        tuple(edge for edge in graph.edges if edge in visible_edges),
    )


def build_contextual_architecture_graph(
    analysis: ProjectAnalysis,
    root: ArchitectureRoot,
    *,
    direction: ArchitectureDirection = "both",
    depth: int = 1,
) -> ContextualArchitectureGraph:
    """Build a one-to-three-hop internal-import neighborhood."""
    if direction not in {"outgoing", "incoming", "both"}:
        raise ValueError(f"Unsupported architecture direction: {direction}")
    if depth not in {1, 2, 3}:
        raise ValueError("Architecture depth must be 1, 2, or 3")
    if root not in architecture_roots(analysis):
        raise ValueError("Architecture root does not belong to this analysis")
    complete = build_dependency_graph(analysis.module_identities, analysis.dependencies)
    cycles, cyclic_ids = _cycle_data(complete)
    focused = _focused(complete, root.root_id, direction, depth)
    focused = DependencyGraph(
        tuple(
            GraphNode(node.node_id, node.label, node.path, node.node_id in cyclic_ids)
            for node in focused.nodes
        ),
        focused.edges,
    )
    return ContextualArchitectureGraph(
        root,
        direction,
        depth,
        focused,
        len(cycles),
        cyclic_ids,
    )


def build_cycle_architecture_graph(analysis: ProjectAnalysis) -> DependencyGraph:
    """Return only modules and edges participating in cyclic SCCs."""
    complete = build_dependency_graph(analysis.module_identities, analysis.dependencies)
    _, cyclic_ids = _cycle_data(complete)
    return DependencyGraph(
        tuple(
            GraphNode(node.node_id, node.label, node.path, True)
            for node in complete.nodes
            if node.node_id in cyclic_ids
        ),
        tuple(
            edge
            for edge in complete.edges
            if edge.source_id in cyclic_ids and edge.target_id in cyclic_ids
        ),
    )


def module_details(analysis: ProjectAnalysis, node_id: str) -> ModuleDetails | None:
    """Return static details and SCC membership for a module node."""
    identity = next(
        (
            item
            for item in analysis.module_identities
            if item.path.as_posix() == node_id
        ),
        None,
    )
    if identity is None:
        return None
    by_path: dict[Path, ModuleIdentity] = {
        item.path: item for item in analysis.module_identities
    }
    dependencies = tuple(
        sorted(
            dep.target.dotted_name
            for dep in analysis.dependencies
            if dep.source == identity
        )
    )
    imported_by = tuple(
        sorted(
            dep.source.dotted_name
            for dep in analysis.dependencies
            if dep.target == identity
        )
    )
    external = tuple(
        sorted(
            {
                resolution.absolute_name or resolution.reference.module or "<unknown>"
                for resolution in analysis.import_resolutions
                if resolution.source == identity and resolution.status == "external"
            }
        )
    )
    unresolved = tuple(
        sorted(
            {
                resolution.absolute_name or resolution.reference.module or "<unknown>"
                for resolution in analysis.import_resolutions
                if resolution.source == identity
                and resolution.status in {"ambiguous", "unresolved"}
            }
        )
    )
    file_analysis = next(
        (item for item in analysis.file_analyses if item.path == identity.path), None
    )
    complete = build_dependency_graph(analysis.module_identities, analysis.dependencies)
    cycles, _ = _cycle_data(complete)
    cycle_index = next(
        (index for index, component in enumerate(cycles, 1) if node_id in component),
        None,
    )
    cycle_modules: tuple[str, ...] = ()
    if cycle_index is not None:
        component = cycles[cycle_index - 1]
        cycle_modules = tuple(by_path[Path(item)].dotted_name for item in component)
    return ModuleDetails(
        identity.dotted_name,
        identity.path,
        dependencies,
        imported_by,
        external,
        unresolved,
        file_analysis.functions if file_analysis else (),
        file_analysis.classes if file_analysis else (),
        cycle_index,
        cycle_modules,
    )
