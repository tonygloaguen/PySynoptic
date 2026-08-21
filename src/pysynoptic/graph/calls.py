"""Pure contextual graphs built from conservative static call dependencies."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from pysynoptic.graph.layout import DependencyGraph, GraphEdge, GraphNode
from pysynoptic.models import ProjectAnalysis

CallGraphDirection: TypeAlias = Literal["outgoing", "incoming", "both"]
CallGraphRootKind: TypeAlias = Literal["module", "callable"]


@dataclass(frozen=True, slots=True)
class CallGraphRoot:
    """A searchable module or callable entry point for a contextual graph."""

    root_id: str
    kind: CallGraphRootKind
    label: str
    path: Path


@dataclass(frozen=True, slots=True)
class CallGraphDiagnostics:
    """Direct call and resolution counts for the selected root."""

    outgoing_count: int
    incoming_count: int
    resolved_count: int
    ambiguous_count: int
    unresolved_count: int
    dynamic_count: int
    visible_node_count: int
    visible_edge_count: int


@dataclass(frozen=True, slots=True)
class ContextualCallGraph:
    """A bounded call subgraph plus root-specific diagnostics."""

    root: CallGraphRoot
    direction: CallGraphDirection
    depth: int
    graph: DependencyGraph
    root_node_ids: tuple[str, ...]
    diagnostics: CallGraphDiagnostics


def _module_node_id(path: Path) -> str:
    return f"module:{path.as_posix()}"


def call_graph_roots(analysis: ProjectAnalysis) -> tuple[CallGraphRoot, ...]:
    """Return deterministic searchable module and callable graph roots."""
    modules = (
        CallGraphRoot(
            root_id=_module_node_id(identity.path),
            kind="module",
            label=identity.dotted_name,
            path=identity.path,
        )
        for identity in analysis.module_identities
    )
    callables = (
        CallGraphRoot(
            root_id=identity.symbol.symbol_id,
            kind="callable",
            label=identity.qualified_name,
            path=identity.module.path,
        )
        for identity in analysis.callable_identities
    )
    return tuple(
        sorted(
            (*modules, *callables),
            key=lambda root: (
                root.label.casefold(),
                root.label,
                root.kind,
                root.root_id,
            ),
        )
    )


def search_call_graph_roots(
    analysis: ProjectAnalysis,
    query: str,
) -> tuple[CallGraphRoot, ...]:
    """Find graph roots using a case-insensitive label substring."""
    normalized = query.strip().casefold()
    roots = call_graph_roots(analysis)
    if not normalized:
        return roots
    return tuple(root for root in roots if normalized in root.label.casefold())


def _logical_call_graph(analysis: ProjectAnalysis) -> DependencyGraph:
    callable_nodes = (
        GraphNode(
            node_id=identity.symbol.symbol_id,
            label=identity.qualified_name,
            path=identity.module.path,
        )
        for identity in analysis.callable_identities
    )
    module_nodes = (
        GraphNode(
            node_id=_module_node_id(identity.path),
            label=f"{identity.dotted_name}::<module>",
            path=identity.path,
        )
        for identity in analysis.module_identities
    )
    nodes = tuple(
        sorted(
            (*callable_nodes, *module_nodes),
            key=lambda node: (node.label.casefold(), node.label, node.node_id),
        )
    )
    known_ids = {node.node_id for node in nodes}
    edges = {
        GraphEdge(
            source_id=(
                dependency.source_callable.symbol.symbol_id
                if dependency.source_callable is not None
                else _module_node_id(dependency.source_module.path)
            ),
            target_id=dependency.target.symbol.symbol_id,
        )
        for dependency in analysis.call_dependencies
    }
    return DependencyGraph(
        nodes=nodes,
        edges=tuple(
            sorted(
                (
                    edge
                    for edge in edges
                    if edge.source_id in known_ids and edge.target_id in known_ids
                ),
                key=lambda edge: (edge.source_id, edge.target_id),
            )
        ),
    )


def _root_node_ids(
    analysis: ProjectAnalysis,
    root: CallGraphRoot,
) -> tuple[str, ...]:
    if root.kind == "callable":
        return (root.root_id,)
    callable_ids = (
        identity.symbol.symbol_id
        for identity in analysis.callable_identities
        if identity.module.path == root.path
    )
    return (_module_node_id(root.path), *sorted(callable_ids))


def _context_edges(
    graph: DependencyGraph,
    seeds: tuple[str, ...],
    direction: CallGraphDirection,
    depth: int,
) -> tuple[set[str], set[GraphEdge]]:
    outgoing: dict[str, list[GraphEdge]] = {node.node_id: [] for node in graph.nodes}
    incoming: dict[str, list[GraphEdge]] = {node.node_id: [] for node in graph.nodes}
    for edge in graph.edges:
        outgoing[edge.source_id].append(edge)
        incoming[edge.target_id].append(edge)

    visible = set(seeds)
    traversed: set[GraphEdge] = set()
    queue = deque((seed, 0) for seed in seeds)
    expanded: set[tuple[str, int]] = set()
    while queue:
        node_id, distance = queue.popleft()
        if distance >= depth or (node_id, distance) in expanded:
            continue
        expanded.add((node_id, distance))
        candidates: list[tuple[GraphEdge, str]] = []
        if direction in {"outgoing", "both"}:
            candidates.extend((edge, edge.target_id) for edge in outgoing[node_id])
        if direction in {"incoming", "both"}:
            candidates.extend((edge, edge.source_id) for edge in incoming[node_id])
        for edge, neighbor in candidates:
            traversed.add(edge)
            visible.add(neighbor)
            queue.append((neighbor, distance + 1))
    return visible, traversed


def _diagnostics(
    analysis: ProjectAnalysis,
    seeds: tuple[str, ...],
    graph: DependencyGraph,
) -> CallGraphDiagnostics:
    seed_set = set(seeds)
    outgoing_count = sum(edge.source_id in seed_set for edge in graph.edges)
    incoming_count = sum(edge.target_id in seed_set for edge in graph.edges)
    statuses = {
        status: 0 for status in ("resolved", "ambiguous", "unresolved", "dynamic")
    }
    for resolution in analysis.call_resolutions:
        source_id = resolution.reference.caller_symbol_id or _module_node_id(
            resolution.source.path
        )
        if source_id in seed_set:
            statuses[resolution.status] += 1
    return CallGraphDiagnostics(
        outgoing_count=outgoing_count,
        incoming_count=incoming_count,
        resolved_count=statuses["resolved"],
        ambiguous_count=statuses["ambiguous"],
        unresolved_count=statuses["unresolved"],
        dynamic_count=statuses["dynamic"],
        visible_node_count=0,
        visible_edge_count=0,
    )


def build_contextual_call_graph(
    analysis: ProjectAnalysis,
    root: CallGraphRoot,
    *,
    direction: CallGraphDirection = "outgoing",
    depth: int = 1,
) -> ContextualCallGraph:
    """Build a one-to-three-hop call graph around a module or callable root."""
    if direction not in {"outgoing", "incoming", "both"}:
        raise ValueError(f"Unsupported call graph direction: {direction}")
    if depth not in {1, 2, 3}:
        raise ValueError("Call graph depth must be 1, 2, or 3")
    roots_by_id = {item.root_id: item for item in call_graph_roots(analysis)}
    if roots_by_id.get(root.root_id) != root:
        raise ValueError("Call graph root does not belong to this analysis")

    logical_graph = _logical_call_graph(analysis)
    seeds = _root_node_ids(analysis, root)
    visible_ids, visible_edges = _context_edges(
        logical_graph,
        seeds,
        direction,
        depth,
    )
    context = DependencyGraph(
        nodes=tuple(
            node for node in logical_graph.nodes if node.node_id in visible_ids
        ),
        edges=tuple(edge for edge in logical_graph.edges if edge in visible_edges),
    )
    diagnostics = _diagnostics(analysis, seeds, logical_graph)
    diagnostics = CallGraphDiagnostics(
        outgoing_count=diagnostics.outgoing_count,
        incoming_count=diagnostics.incoming_count,
        resolved_count=diagnostics.resolved_count,
        ambiguous_count=diagnostics.ambiguous_count,
        unresolved_count=diagnostics.unresolved_count,
        dynamic_count=diagnostics.dynamic_count,
        visible_node_count=len(context.nodes),
        visible_edge_count=len(context.edges),
    )
    return ContextualCallGraph(
        root=root,
        direction=direction,
        depth=depth,
        graph=context,
        root_node_ids=seeds,
        diagnostics=diagnostics,
    )
