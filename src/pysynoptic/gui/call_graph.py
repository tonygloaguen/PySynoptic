"""Contextual call-graph controls backed by the native graph Canvas."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import ttkbootstrap as ttk

from pysynoptic.graph import (
    CallGraphDirection,
    CallGraphRoot,
    ContextualCallGraph,
    build_contextual_call_graph,
    call_graph_roots,
    callable_details,
    layout_graph,
    search_call_graph_roots,
)
from pysynoptic.graph.layout import GraphNode
from pysynoptic.gui.graph_canvas import DependencyGraphCanvas
from pysynoptic.gui.graph_helpers import (
    DEFAULT_CALL_DEPTH,
    empty_outgoing_suggestion,
)
from pysynoptic.models import ProjectAnalysis

_DIRECTIONS: dict[str, CallGraphDirection] = {
    "Outgoing": "outgoing",
    "Incoming": "incoming",
    "Both": "both",
}


class ContextualCallGraphPanel(ttk.Frame):
    """Search and navigate bounded static call relationships."""

    def __init__(
        self,
        master: Any,
        *,
        on_open_flow: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master)
        self._analysis: ProjectAnalysis | None = None
        self._roots: tuple[CallGraphRoot, ...] = ()
        self._filtered_roots: tuple[CallGraphRoot, ...] = ()
        self._selected_root: CallGraphRoot | None = None
        self.current_result: ContextualCallGraph | None = None
        self._on_open_flow = on_open_flow
        self._detail_links: dict[str, str] = {}

        controls = ttk.Frame(self)
        controls.pack(fill="x", pady=(0, 8))

        ttk.Label(controls, text="Search").pack(side="left")
        self.search_variable = ttk.StringVar()
        self.search_box = ttk.Combobox(
            controls,
            textvariable=self.search_variable,
            width=58,
        )
        self.search_box.pack(side="left", fill="x", expand=True, padx=(6, 12))
        self.search_box.bind("<KeyRelease>", self._on_search_key)
        self.search_box.bind("<<ComboboxSelected>>", self._on_search_selected)
        self.search_box.bind("<Return>", self._select_first_match)

        ttk.Label(controls, text="Direction").pack(side="left")
        self.direction_variable = ttk.StringVar(value="Both")
        direction_box = ttk.Combobox(
            controls,
            textvariable=self.direction_variable,
            values=tuple(_DIRECTIONS),
            state="readonly",
            width=10,
        )
        direction_box.pack(side="left", padx=(6, 12))
        direction_box.bind("<<ComboboxSelected>>", self._rebuild_event)

        ttk.Label(controls, text="Depth").pack(side="left")
        self.depth_variable = ttk.StringVar(value=str(DEFAULT_CALL_DEPTH))
        depth_box = ttk.Combobox(
            controls,
            textvariable=self.depth_variable,
            values=("1", "2", "3"),
            state="readonly",
            width=3,
        )
        depth_box.pack(side="left", padx=(6, 0))
        depth_box.bind("<<ComboboxSelected>>", self._rebuild_event)

        diagnostics = ttk.Labelframe(self, text="Diagnostics", padding=(9, 5))
        diagnostics.pack(fill="x", pady=(0, 8))
        self.root_diagnostics_variable = ttk.StringVar(value="No root selected")
        self.call_diagnostics_variable = ttk.StringVar(value="")
        ttk.Label(
            diagnostics,
            textvariable=self.root_diagnostics_variable,
            anchor="w",
        ).pack(fill="x")
        ttk.Label(
            diagnostics,
            textvariable=self.call_diagnostics_variable,
            anchor="w",
        ).pack(fill="x")

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)
        graph_panel = ttk.Frame(body)
        details_panel = ttk.Labelframe(body, text="Callable details", padding=10)
        body.add(graph_panel, weight=4)
        body.add(details_panel, weight=1)
        self.canvas = DependencyGraphCanvas(
            graph_panel,
            on_select=self._show_node_details,
            on_activate=self._activate_node,
            node_label="callables",
            edge_label="calls",
            empty_message="Select a module or callable to display its call context.",
        )
        self.canvas.pack(fill="both", expand=True)
        self.details_variable = ttk.StringVar(value="Select a callable.")
        ttk.Label(
            details_panel,
            textvariable=self.details_variable,
            justify="left",
            anchor="nw",
            wraplength=280,
        ).pack(fill="x")
        self.details_tree = ttk.Treeview(details_panel, show="tree", height=10)
        self.details_tree.pack(fill="both", expand=True, pady=(8, 8))
        self.details_tree.bind("<Double-Button-1>", self._activate_detail_link)
        actions = ttk.Frame(details_panel)
        actions.pack(fill="x")
        ttk.Button(
            actions,
            text="Show Incoming",
            command=lambda: self.set_direction("incoming"),
        ).pack(side="left")
        ttk.Button(
            actions, text="Show Both", command=lambda: self.set_direction("both")
        ).pack(side="left", padx=(5, 0))
        self.flow_button = ttk.Button(
            actions, text="Open Flow", command=self._open_selected_flow
        )
        self.flow_button.pack(side="right")
        ttk.Label(
            self,
            text="Legend: → calls · double-click a node to make it the focus",
            bootstyle="secondary",
        ).pack(fill="x", pady=(6, 0))

    @property
    def selected_root(self) -> CallGraphRoot | None:
        """Return the current module or callable root."""
        return self._selected_root

    def set_analysis(self, analysis: ProjectAnalysis | None) -> None:
        """Replace the analyzed project and reset contextual navigation."""
        if analysis is self._analysis:
            return
        self._analysis = analysis
        self._roots = call_graph_roots(analysis) if analysis is not None else ()
        self._filtered_roots = self._roots
        self._selected_root = None
        self.current_result = None
        self.search_variable.set("")
        self.search_box.configure(values=self._option_labels(self._roots))
        self.canvas.clear()
        self.root_diagnostics_variable.set(
            f"{len(self._roots)} searchable roots"
            if self._roots
            else "No project analysis"
        )
        self.call_diagnostics_variable.set("")
        self.details_variable.set("Select a callable to inspect its neighborhood.")
        self.details_tree.delete(*self.details_tree.get_children())
        if analysis is not None and len(analysis.module_identities) == 1:
            candidates = [
                root
                for root in self._roots
                if root.kind == "callable" and root.label.endswith("::main")
            ]
            if not candidates:
                candidates = [root for root in self._roots if root.kind == "callable"]
            if candidates:
                self.select_root(candidates[0].root_id)

    def search(self, query: str) -> tuple[CallGraphRoot, ...]:
        """Filter root choices and return the matching model objects."""
        self.search_variable.set(query)
        if self._analysis is None:
            self._filtered_roots = ()
        else:
            self._filtered_roots = search_call_graph_roots(self._analysis, query)
        self.search_box.configure(values=self._option_labels(self._filtered_roots))
        return self._filtered_roots

    def select_root(self, root_id: str) -> bool:
        """Select a searchable root by stable node identifier and rebuild."""
        root = next((item for item in self._roots if item.root_id == root_id), None)
        if root is None:
            return False
        self._selected_root = root
        self.direction_variable.set("Both")
        self.depth_variable.set("1")
        self.search_variable.set(root.label)
        self._rebuild()
        return True

    def set_direction(self, direction: CallGraphDirection) -> None:
        """Change traversal direction and rebuild the current context."""
        label = next(
            (label for label, value in _DIRECTIONS.items() if value == direction),
            None,
        )
        if label is None:
            raise ValueError(f"Unsupported call graph direction: {direction}")
        self.direction_variable.set(label)
        self._rebuild()

    def set_depth(self, depth: int) -> None:
        """Change traversal depth and rebuild the current context."""
        if depth not in {1, 2, 3}:
            raise ValueError("Call graph depth must be 1, 2, or 3")
        self.depth_variable.set(str(depth))
        self._rebuild()

    @staticmethod
    def _option_labels(roots: tuple[CallGraphRoot, ...]) -> tuple[str, ...]:
        return tuple(root.label for root in roots)

    def _on_search_key(self, _event: object) -> None:
        self.search(self.search_variable.get())

    def _on_search_selected(self, _event: object) -> None:
        selected = self.search_variable.get()
        root = next(
            (root for root in self._filtered_roots if root.label == selected),
            None,
        )
        if root is not None:
            self.select_root(root.root_id)

    def _select_first_match(self, _event: object) -> None:
        matches = self.search(self.search_variable.get())
        if matches:
            self.select_root(matches[0].root_id)

    def _rebuild_event(self, _event: object) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        if self._analysis is None or self._selected_root is None:
            return
        result = build_contextual_call_graph(
            self._analysis,
            self._selected_root,
            direction=_DIRECTIONS[self.direction_variable.get()],
            depth=int(self.depth_variable.get()),
        )
        self.current_result = result
        self.canvas.set_layout(layout_graph(result.graph))
        for root_node_id in result.root_node_ids:
            if self.canvas.select_node(root_node_id):
                break
        diagnostics = result.diagnostics
        self.root_diagnostics_variable.set(
            f"{result.root.kind.title()}: {result.root.label} · "
            f"{diagnostics.visible_node_count} visible nodes · "
            f"{diagnostics.visible_edge_count} visible calls"
        )
        self.call_diagnostics_variable.set(
            f"Outgoing {diagnostics.outgoing_count} · "
            f"Incoming {diagnostics.incoming_count} · "
            f"Resolved {diagnostics.resolved_count} · "
            f"Ambiguous {diagnostics.ambiguous_count} · "
            f"Unresolved {diagnostics.unresolved_count} · "
            f"Dynamic {diagnostics.dynamic_count}"
        )
        if result.root.kind == "callable":
            self._render_details(result.root.root_id)
        elif not result.graph.edges:
            self.details_variable.set(
                "This module has no resolved calls in the selected context."
            )

    def current_graph(self):
        """Return the current logical call graph for export."""
        return self.current_result.graph if self.current_result is not None else None

    def _render_details(self, node_id: str) -> None:
        if self._analysis is None:
            return
        details = callable_details(self._analysis, node_id)
        if details is None:
            return
        parent = details.lexical_parent or "—"
        message = "\n".join(
            (
                details.kind.title(),
                f"{details.name}()",
                "",
                "Qualified name",
                details.qualified_name,
                "",
                "Module",
                details.module,
                "",
                "Source",
                f"{details.path}:{details.line}",
                "",
                f"Lexical parent: {parent}",
                f"Resolved references: {details.resolved_count}",
                f"Ambiguous: {details.ambiguous_count}",
                f"Unresolved: {details.unresolved_count}",
                f"Dynamic: {details.dynamic_count}",
            )
        )
        suggestion = empty_outgoing_suggestion(
            len(details.incoming), _DIRECTIONS[self.direction_variable.get()]
        )
        if not details.outgoing and suggestion:
            message += f"\n\n{suggestion}"
        self.details_variable.set(message)
        self.details_tree.delete(*self.details_tree.get_children())
        self._detail_links.clear()
        incoming_root = self.details_tree.insert(
            "", "end", text=f"Called by ({len(details.incoming)})", open=True
        )
        outgoing_root = self.details_tree.insert(
            "", "end", text=f"Calls ({len(details.outgoing)})", open=True
        )
        for target_id, label in details.incoming:
            item = self.details_tree.insert(
                incoming_root, "end", text=f"← {self._relationship_label(label)}"
            )
            self._detail_links[item] = target_id
        for target_id, label in details.outgoing:
            item = self.details_tree.insert(
                outgoing_root, "end", text=f"→ {self._relationship_label(label)}"
            )
            self._detail_links[item] = target_id

    @staticmethod
    def _relationship_label(qualified_name: str) -> str:
        local_name = qualified_name.partition("::")[2] or qualified_name
        return local_name if local_name == "<module>" else f"{local_name}()"

    def _show_node_details(self, node: GraphNode) -> None:
        self._render_details(node.node_id)

    def _activate_detail_link(self, _event: object) -> None:
        selected = self.details_tree.selection()
        if selected and selected[0] in self._detail_links:
            self.select_root(self._detail_links[selected[0]])

    def _open_selected_flow(self) -> None:
        root = self._selected_root
        if root is not None and root.kind == "callable" and self._on_open_flow:
            self._on_open_flow(root.root_id)

    def _activate_node(self, node: GraphNode) -> None:
        self.select_root(node.node_id)
