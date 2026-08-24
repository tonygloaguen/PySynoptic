"""Headless-safe project-tree and callable presentation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypeAlias

from pysynoptic.models import CallableIdentity, ProjectAnalysis

ProjectTreeNodeKind: TypeAlias = Literal[
    "project",
    "directory",
    "file",
    "resource",
    "group",
    "class",
    "callable",
]
CallableSelectionSource: TypeAlias = Literal["tree", "calls", "flow"]


@dataclass(frozen=True, slots=True)
class ProjectTreeNode:
    """One GUI-neutral row in the project and callable hierarchy."""

    key: str
    label: str
    kind: ProjectTreeNodeKind
    path: Path | None = None
    module_node_id: str | None = None
    symbol_id: str | None = None
    children: tuple[ProjectTreeNode, ...] = ()


@dataclass(frozen=True, slots=True)
class CallableOption:
    """A concise selector label paired with an unambiguous symbol ID."""

    label: str
    symbol_id: str


@dataclass(frozen=True, slots=True)
class CallableRelation:
    """One statically proven incoming or outgoing callable relationship."""

    symbol_id: str | None
    label: str


@dataclass(frozen=True, slots=True)
class CallableRelationContext:
    """Resolved callers and callees for one selected callable."""

    incoming: tuple[CallableRelation, ...]
    outgoing: tuple[CallableRelation, ...]


@dataclass(frozen=True, slots=True)
class CallableNavigationPlan:
    """Headless-safe synchronization effects for one callable selection."""

    symbol_id: str
    update_calls: bool
    update_flow: bool
    render_flow: bool


def plan_callable_navigation(
    symbol_id: str,
    *,
    source: CallableSelectionSource,
    render_flow: bool,
) -> CallableNavigationPlan:
    """Describe how Calls and Flow must converge on one exact callable."""
    return CallableNavigationPlan(
        symbol_id=symbol_id,
        update_calls=source != "calls",
        update_flow=source != "flow",
        render_flow=render_flow,
    )


@dataclass(slots=True)
class _MutableTreeNode:
    key: str
    label: str
    kind: ProjectTreeNodeKind
    path: Path | None = None
    module_node_id: str | None = None
    symbol_id: str | None = None
    children: list[_MutableTreeNode] = field(default_factory=list)

    def freeze(self) -> ProjectTreeNode:
        return ProjectTreeNode(
            key=self.key,
            label=self.label,
            kind=self.kind,
            path=self.path,
            module_node_id=self.module_node_id,
            symbol_id=self.symbol_id,
            children=tuple(child.freeze() for child in self.children),
        )


def callable_short_label(identity: CallableIdentity) -> str:
    """Return a readable callable label without its module identity."""
    symbol = identity.symbol
    if symbol.kind == "method":
        parts = [
            part for part in symbol.qualified_name.split(".") if part != "<locals>"
        ]
        if len(parts) > 1:
            return f"{parts[-2]}.{symbol.name}()"
    if symbol.parent_symbol_id is not None:
        parts = [
            part for part in symbol.qualified_name.split(".") if part != "<locals>"
        ]
        if len(parts) > 1:
            return f"{parts[-2]}.{symbol.name}()"
    return f"{symbol.name}()"


def callable_kind_label(identity: CallableIdentity) -> str:
    """Return the selected callable kind in user-facing form."""
    base = "Method" if identity.symbol.kind == "method" else "Function"
    return f"Async {base.lower()}" if identity.symbol.is_async else base


def callable_selector_options(
    analysis: ProjectAnalysis,
) -> tuple[CallableOption, ...]:
    """Build short, deterministic and collision-safe selector options."""
    identities = sorted(
        analysis.callable_identities,
        key=lambda item: (
            callable_short_label(item).casefold(),
            item.module.dotted_name.casefold(),
            item.symbol.line,
            item.symbol.symbol_id,
        ),
    )
    base_labels = [callable_short_label(identity) for identity in identities]
    counts = {label: base_labels.count(label) for label in set(base_labels)}
    return tuple(
        CallableOption(
            label=(
                f"{label} — {identity.module.dotted_name}"
                if counts[label] > 1
                else label
            ),
            symbol_id=identity.symbol.symbol_id,
        )
        for identity, label in zip(identities, base_labels, strict=True)
    )


def callable_relation_context(
    analysis: ProjectAnalysis,
    symbol_id: str,
) -> CallableRelationContext:
    """Return only conservatively resolved relations for one callable."""
    identities = {
        identity.symbol.symbol_id: identity for identity in analysis.callable_identities
    }

    incoming: set[tuple[str | None, str]] = set()
    outgoing: set[tuple[str | None, str]] = set()
    for dependency in analysis.call_dependencies:
        source_id = (
            dependency.source_callable.symbol.symbol_id
            if dependency.source_callable is not None
            else None
        )
        target_id = dependency.target.symbol.symbol_id
        if target_id == symbol_id:
            label = (
                callable_short_label(dependency.source_callable)
                if dependency.source_callable is not None
                else (
                    "<module>"
                    if len(analysis.module_identities) == 1
                    else f"<{dependency.source_module.dotted_name} module>"
                )
            )
            incoming.add((source_id, label))
        if source_id == symbol_id:
            outgoing.add((target_id, callable_short_label(dependency.target)))

    def relations(items: set[tuple[str | None, str]]) -> tuple[CallableRelation, ...]:
        return tuple(
            CallableRelation(symbol_id=item_id, label=label)
            for item_id, label in sorted(
                items,
                key=lambda item: (
                    item[1].casefold(),
                    item[1],
                    item[0] or "",
                ),
            )
            if item_id is None or item_id in identities
        )

    return CallableRelationContext(
        incoming=relations(incoming),
        outgoing=relations(outgoing),
    )


def build_project_tree(
    selected_path: Path,
    target_kind: Literal["file", "project"],
    analysis: ProjectAnalysis | None,
) -> ProjectTreeNode:
    """Build the complete project/file/callable hierarchy without Tk."""
    if target_kind == "file":
        module_node_id = None
        if analysis is not None:
            identity = next(
                (
                    item
                    for item in analysis.module_identities
                    if item.path == selected_path
                ),
                analysis.module_identities[0] if analysis.module_identities else None,
            )
            module_node_id = identity.path.as_posix() if identity is not None else None
        root = _MutableTreeNode(
            key=f"file:{selected_path.as_posix()}",
            label=selected_path.name,
            kind="file",
            path=selected_path,
            module_node_id=module_node_id,
        )
        if analysis is not None:
            root.children.extend(_callable_groups(analysis, selected_path))
        return root.freeze()

    root = _MutableTreeNode(
        key=f"project:{selected_path.as_posix()}",
        label=selected_path.name or str(selected_path),
        kind="project",
        path=selected_path,
    )
    if analysis is None:
        return root.freeze()

    module_ids = {
        identity.path: identity.path.as_posix()
        for identity in analysis.module_identities
    }
    resource_paths = {resource.path for resource in analysis.resources}
    paths = sorted(
        (*analysis.python_files, *resource_paths),
        key=lambda path: path.as_posix().casefold(),
    )
    directory_nodes: dict[tuple[str, ...], _MutableTreeNode] = {(): root}
    for path in paths:
        try:
            parts = path.relative_to(analysis.root_path).parts
        except ValueError:
            parts = path.parts
        parent_key: tuple[str, ...] = ()
        for part in parts[:-1]:
            key = (*parent_key, part)
            if key not in directory_nodes:
                directory = _MutableTreeNode(
                    key=f"directory:{'/'.join(key)}",
                    label=part,
                    kind="directory",
                )
                directory_nodes[parent_key].children.append(directory)
                directory_nodes[key] = directory
            parent_key = key

        is_python = path in module_ids
        file_node = _MutableTreeNode(
            key=f"file:{path.as_posix()}",
            label=parts[-1] if parts else path.name,
            kind="file" if is_python else "resource",
            path=path,
            module_node_id=module_ids.get(path),
        )
        if is_python:
            file_node.children.extend(_callable_groups(analysis, path))
        directory_nodes[parent_key].children.append(file_node)
    return root.freeze()


def _callable_groups(
    analysis: ProjectAnalysis,
    path: Path,
) -> tuple[_MutableTreeNode, ...]:
    identities = tuple(
        sorted(
            (
                identity
                for identity in analysis.callable_identities
                if identity.module.path == path
            ),
            key=lambda item: (
                item.symbol.line,
                item.symbol.column,
                item.symbol.qualified_name,
            ),
        )
    )
    file_analysis = next(
        (item for item in analysis.file_analyses if item.path == path), None
    )
    declared_classes = set(file_analysis.classes if file_analysis is not None else ())
    declared_classes.update(
        identity.symbol.qualified_name.rsplit(".", 1)[0]
        for identity in identities
        if identity.symbol.kind == "method"
    )

    nodes_by_symbol: dict[str, _MutableTreeNode] = {
        identity.symbol.symbol_id: _MutableTreeNode(
            key=f"callable:{identity.symbol.symbol_id}",
            label=f"{identity.symbol.name}()",
            kind="callable",
            path=path,
            symbol_id=identity.symbol.symbol_id,
        )
        for identity in identities
    }
    top_level_functions: list[_MutableTreeNode] = []
    methods_by_class: dict[str, list[_MutableTreeNode]] = {
        name: [] for name in declared_classes
    }
    for identity in identities:
        symbol = identity.symbol
        node = nodes_by_symbol[symbol.symbol_id]
        if symbol.parent_symbol_id in nodes_by_symbol:
            nodes_by_symbol[symbol.parent_symbol_id].children.append(node)
        elif symbol.kind == "method":
            class_name = symbol.qualified_name.rsplit(".", 1)[0]
            methods_by_class.setdefault(class_name, []).append(node)
        else:
            top_level_functions.append(node)

    groups: list[_MutableTreeNode] = []
    if methods_by_class:
        classes = _MutableTreeNode(
            key=f"group:classes:{path.as_posix()}",
            label="Classes",
            kind="group",
        )
        for class_name in sorted(methods_by_class, key=str.casefold):
            class_node = _MutableTreeNode(
                key=f"class:{path.as_posix()}:{class_name}",
                label=class_name,
                kind="class",
                path=path,
            )
            class_node.children.extend(methods_by_class[class_name])
            classes.children.append(class_node)
        groups.append(classes)
    if top_level_functions:
        functions = _MutableTreeNode(
            key=f"group:functions:{path.as_posix()}",
            label="Functions",
            kind="group",
        )
        functions.children.extend(top_level_functions)
        groups.append(functions)
    return tuple(groups)
