"""Pure-Python layout for project dependency graphs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pysynoptic.models import ModuleDependency, ModuleIdentity, ProjectAnalysis

_HORIZONTAL_GAP = 110.0
_VERTICAL_GAP = 34.0
_MARGIN = 60.0
_NODE_HEIGHT = 44.0
_MIN_NODE_WIDTH = 132.0
_MAX_NODE_WIDTH = 280.0


@dataclass(frozen=True, slots=True)
class GraphNode:
    """One module in a renderer-independent dependency graph."""

    node_id: str
    label: str
    path: Path


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """One directed dependency between graph node identifiers."""

    source_id: str
    target_id: str


@dataclass(frozen=True, slots=True)
class DependencyGraph:
    """Immutable logical dependency graph before layout."""

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]


@dataclass(frozen=True, slots=True)
class PositionedNode:
    """A graph node assigned to a layer and world-space rectangle."""

    node: GraphNode
    x: float
    y: float
    width: float
    height: float
    layer: int
    component: int


@dataclass(frozen=True, slots=True)
class GraphLayout:
    """Complete deterministic layout consumed by a graphical renderer."""

    nodes: tuple[PositionedNode, ...]
    edges: tuple[GraphEdge, ...]
    components: tuple[tuple[str, ...], ...]
    layer_count: int
    width: float
    height: float

    @property
    def cyclic_component_count(self) -> int:
        """Return the number of SCCs containing a cycle."""
        edge_pairs = {(edge.source_id, edge.target_id) for edge in self.edges}
        return sum(
            len(component) > 1 or (component[0], component[0]) in edge_pairs
            for component in self.components
        )


def _node_sort_key(node: GraphNode) -> tuple[str, str, str]:
    return (node.label.casefold(), node.label, node.path.as_posix())


def build_dependency_graph(
    identities: Iterable[ModuleIdentity],
    dependencies: Iterable[ModuleDependency],
) -> DependencyGraph:
    """Convert analysis models to a stable logical graph."""
    nodes = tuple(
        sorted(
            (
                GraphNode(
                    node_id=identity.path.as_posix(),
                    label=identity.dotted_name,
                    path=identity.path,
                )
                for identity in identities
            ),
            key=_node_sort_key,
        )
    )
    known_ids = {node.node_id for node in nodes}
    edges = {
        GraphEdge(
            source_id=dependency.source.path.as_posix(),
            target_id=dependency.target.path.as_posix(),
        )
        for dependency in dependencies
        if dependency.source.path.as_posix() in known_ids
        and dependency.target.path.as_posix() in known_ids
    }
    return DependencyGraph(
        nodes=nodes,
        edges=tuple(sorted(edges, key=lambda edge: (edge.source_id, edge.target_id))),
    )


def strongly_connected_components(
    graph: DependencyGraph,
) -> tuple[tuple[str, ...], ...]:
    """Return deterministic SCCs using iterative Kosaraju traversal."""
    node_ids = tuple(node.node_id for node in graph.nodes)
    sort_keys = {node.node_id: _node_sort_key(node) for node in graph.nodes}
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    reverse: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in graph.edges:
        adjacency[edge.source_id].append(edge.target_id)
        reverse[edge.target_id].append(edge.source_id)
    for neighbors in (*adjacency.values(), *reverse.values()):
        neighbors.sort(key=sort_keys.__getitem__)

    visited: set[str] = set()
    finish_order: list[str] = []
    for start in node_ids:
        if start in visited:
            continue
        visited.add(start)
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            node_id, expanded = stack.pop()
            if expanded:
                finish_order.append(node_id)
                continue
            stack.append((node_id, True))
            for neighbor in reversed(adjacency[node_id]):
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append((neighbor, False))

    components: list[tuple[str, ...]] = []
    assigned: set[str] = set()
    for start in reversed(finish_order):
        if start in assigned:
            continue
        assigned.add(start)
        members: list[str] = []
        stack = [start]
        while stack:
            node_id = stack.pop()
            members.append(node_id)
            for neighbor in reversed(reverse[node_id]):
                if neighbor not in assigned:
                    assigned.add(neighbor)
                    stack.append(neighbor)
        components.append(tuple(sorted(members, key=sort_keys.__getitem__)))
    return tuple(components)


def _component_layers(
    graph: DependencyGraph,
    components: tuple[tuple[str, ...], ...],
    sort_keys: dict[str, tuple[str, str, str]],
) -> tuple[dict[int, int], dict[int, set[int]], dict[int, set[int]]]:
    component_by_node = {
        node_id: index
        for index, component in enumerate(components)
        for node_id in component
    }
    successors: dict[int, set[int]] = {index: set() for index in range(len(components))}
    predecessors: dict[int, set[int]] = {
        index: set() for index in range(len(components))
    }
    for edge in graph.edges:
        source = component_by_node[edge.source_id]
        target = component_by_node[edge.target_id]
        if source == target:
            continue
        successors[source].add(target)
        predecessors[target].add(source)

    def component_key(index: int) -> tuple[str, str, str]:
        return min(sort_keys[node_id] for node_id in components[index])

    indegrees = {index: len(predecessors[index]) for index in successors}
    available = sorted(
        (index for index, degree in indegrees.items() if degree == 0),
        key=component_key,
    )
    layers = {index: 0 for index in successors}
    while available:
        component = available.pop(0)
        for target in sorted(successors[component], key=component_key):
            layers[target] = max(layers[target], layers[component] + 1)
            indegrees[target] -= 1
            if indegrees[target] == 0:
                available.append(target)
                available.sort(key=component_key)
    return layers, predecessors, successors


def _ordered_layers(
    components: tuple[tuple[str, ...], ...],
    component_layers: dict[int, int],
    predecessors: dict[int, set[int]],
    successors: dict[int, set[int]],
    sort_keys: dict[str, tuple[str, str, str]],
) -> list[list[int]]:
    layer_count = max(component_layers.values(), default=-1) + 1
    layers: list[list[int]] = [[] for _ in range(layer_count)]
    component_keys = {
        index: min(sort_keys[node_id] for node_id in component)
        for index, component in enumerate(components)
    }
    for component, layer in component_layers.items():
        layers[layer].append(component)
    for layer in layers:
        layer.sort(key=component_keys.__getitem__)

    positions = {
        component: index for layer in layers for index, component in enumerate(layer)
    }
    for layer_index in range(1, len(layers)):
        layers[layer_index].sort(
            key=lambda component: (
                sum(positions[item] for item in predecessors[component])
                / len(predecessors[component])
                if predecessors[component]
                else float("inf"),
                component_keys[component],
            )
        )
        positions.update(
            {component: index for index, component in enumerate(layers[layer_index])}
        )
    for layer_index in range(len(layers) - 2, -1, -1):
        layers[layer_index].sort(
            key=lambda component: (
                sum(positions[item] for item in successors[component])
                / len(successors[component])
                if successors[component]
                else float("inf"),
                component_keys[component],
            )
        )
        positions.update(
            {component: index for index, component in enumerate(layers[layer_index])}
        )
    return layers


def _node_width(label: str) -> float:
    return max(_MIN_NODE_WIDTH, min(_MAX_NODE_WIDTH, 30.0 + len(label) * 7.2))


def layout_graph(graph: DependencyGraph) -> GraphLayout:
    """Position any renderer-independent directed graph deterministically."""
    if not graph.nodes:
        return GraphLayout((), graph.edges, (), 0, 0.0, 0.0)

    nodes_by_id = {node.node_id: node for node in graph.nodes}
    sort_keys = {node.node_id: _node_sort_key(node) for node in graph.nodes}
    components = strongly_connected_components(graph)
    component_layers, predecessors, successors = _component_layers(
        graph, components, sort_keys
    )
    ordered_layers = _ordered_layers(
        components,
        component_layers,
        predecessors,
        successors,
        sort_keys,
    )

    node_ids_by_layer: list[list[str]] = []
    component_by_node: dict[str, int] = {}
    for component_index, component in enumerate(components):
        component_by_node.update({node_id: component_index for node_id in component})
    for layer in ordered_layers:
        node_ids_by_layer.append(
            [node_id for component in layer for node_id in components[component]]
        )

    layer_widths = [
        max(_node_width(nodes_by_id[node_id].label) for node_id in node_ids)
        for node_ids in node_ids_by_layer
    ]
    layer_heights = [
        len(node_ids) * _NODE_HEIGHT + max(0, len(node_ids) - 1) * _VERTICAL_GAP
        for node_ids in node_ids_by_layer
    ]
    content_height = max(layer_heights)
    x_positions: list[float] = []
    x = _MARGIN
    for layer_width in layer_widths:
        x_positions.append(x)
        x += layer_width + _HORIZONTAL_GAP

    positioned: list[PositionedNode] = []
    for layer_index, node_ids in enumerate(node_ids_by_layer):
        y = _MARGIN + (content_height - layer_heights[layer_index]) / 2
        for node_id in node_ids:
            node = nodes_by_id[node_id]
            positioned.append(
                PositionedNode(
                    node=node,
                    x=x_positions[layer_index],
                    y=y,
                    width=_node_width(node.label),
                    height=_NODE_HEIGHT,
                    layer=layer_index,
                    component=component_by_node[node_id],
                )
            )
            y += _NODE_HEIGHT + _VERTICAL_GAP

    width = x - _HORIZONTAL_GAP + _MARGIN
    height = content_height + 2 * _MARGIN
    positioned.sort(key=lambda item: _node_sort_key(item.node))
    return GraphLayout(
        nodes=tuple(positioned),
        edges=graph.edges,
        components=components,
        layer_count=len(ordered_layers),
        width=width,
        height=height,
    )


def layout_dependency_graph(analysis: ProjectAnalysis) -> GraphLayout:
    """Build and position every project module for Canvas rendering."""
    graph = build_dependency_graph(analysis.module_identities, analysis.dependencies)
    return layout_graph(graph)
