"""Focused internal-module architecture panel."""

from __future__ import annotations

from typing import Any

import ttkbootstrap as ttk

from pysynoptic.graph import (
    ArchitectureDirection,
    ArchitectureRoot,
    ContextualArchitectureGraph,
    architecture_roots,
    build_contextual_architecture_graph,
    build_cycle_architecture_graph,
    build_dependency_graph,
    graph_readability_message,
    layout_graph,
    module_details,
    search_architecture_roots,
)
from pysynoptic.graph.layout import GraphNode
from pysynoptic.gui.graph_canvas import DependencyGraphCanvas
from pysynoptic.models import ProjectAnalysis

_DIRECTIONS: dict[str, ArchitectureDirection] = {
    "Both": "both",
    "Outgoing": "outgoing",
    "Incoming": "incoming",
}


class ArchitecturePanel(ttk.Frame):
    """Navigate a bounded module-import neighborhood."""

    def __init__(self, master: Any) -> None:
        super().__init__(master)
        self._analysis: ProjectAnalysis | None = None
        self._roots: tuple[ArchitectureRoot, ...] = ()
        self._filtered: tuple[ArchitectureRoot, ...] = ()
        self._selected: ArchitectureRoot | None = None
        self._current_graph = None
        self.current_result: ContextualArchitectureGraph | None = None

        controls = ttk.Frame(self)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Label(controls, text="Module").pack(side="left")
        self.search_variable = ttk.StringVar()
        self.search_box = ttk.Combobox(controls, textvariable=self.search_variable)
        self.search_box.pack(side="left", fill="x", expand=True, padx=(6, 12))
        self.search_box.bind("<KeyRelease>", self._search_event)
        self.search_box.bind("<<ComboboxSelected>>", self._select_event)
        self.search_box.bind("<Return>", self._first_event)

        ttk.Label(controls, text="Direction").pack(side="left")
        self.direction_variable = ttk.StringVar(value="Both")
        direction = ttk.Combobox(
            controls,
            textvariable=self.direction_variable,
            values=tuple(_DIRECTIONS),
            state="readonly",
            width=10,
        )
        direction.pack(side="left", padx=(6, 12))
        direction.bind("<<ComboboxSelected>>", self._rebuild_event)
        ttk.Label(controls, text="Depth").pack(side="left")
        self.depth_variable = ttk.StringVar(value="1")
        depth = ttk.Combobox(
            controls,
            textvariable=self.depth_variable,
            values=("1", "2", "3"),
            state="readonly",
            width=3,
        )
        depth.pack(side="left", padx=(6, 12))
        depth.bind("<<ComboboxSelected>>", self._rebuild_event)
        ttk.Button(controls, text="Cycles", command=self.show_cycles).pack(side="left")
        ttk.Button(
            controls, text="Whole project", command=self.show_whole_project
        ).pack(side="left", padx=(6, 0))

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)
        graph = ttk.Frame(body)
        details = ttk.Labelframe(body, text="Module details", padding=10)
        body.add(graph, weight=4)
        body.add(details, weight=1)
        self.canvas = DependencyGraphCanvas(
            graph,
            on_select=self._show_node_details,
            on_activate=self._activate_node,
            empty_message="Select a module to explore its internal imports.",
        )
        self.canvas.pack(fill="both", expand=True)
        self.details_variable = ttk.StringVar(value="Select a module.")
        ttk.Label(
            details,
            textvariable=self.details_variable,
            justify="left",
            anchor="nw",
            wraplength=260,
        ).pack(fill="both", expand=True)
        ttk.Label(
            self,
            text="Legend: → imports · orange module = dependency cycle",
            bootstyle="secondary",
        ).pack(fill="x", pady=(6, 0))

    def set_analysis(self, analysis: ProjectAnalysis | None) -> None:
        """Replace analysis and choose a useful first module."""
        if analysis is self._analysis:
            return
        self._analysis = analysis
        self._roots = architecture_roots(analysis) if analysis else ()
        self._filtered = self._roots
        self.search_box.configure(values=tuple(root.label for root in self._roots))
        self.canvas.clear()
        self.current_result = None
        self._current_graph = None
        self._selected = None
        if len(self._roots) == 1:
            self.select_root(self._roots[0].root_id)
        else:
            self.search_variable.set("")
            self.details_variable.set(
                f"{len(self._roots)} internal modules. Select one to focus."
                if self._roots
                else "Analyze a Python file or project."
            )

    def search(self, query: str) -> tuple[ArchitectureRoot, ...]:
        self.search_variable.set(query)
        self._filtered = (
            search_architecture_roots(self._analysis, query)
            if self._analysis is not None
            else ()
        )
        self.search_box.configure(values=tuple(root.label for root in self._filtered))
        return self._filtered

    def select_root(self, root_id: str) -> bool:
        root = next((item for item in self._roots if item.root_id == root_id), None)
        if root is None:
            return False
        self._selected = root
        self.direction_variable.set("Both")
        self.depth_variable.set("1")
        self.search_variable.set(root.label)
        self._rebuild()
        return True

    def show_cycles(self) -> None:
        if self._analysis is None:
            return
        graph = build_cycle_architecture_graph(self._analysis)
        self.current_result = None
        self._current_graph = graph
        self.canvas.set_layout(layout_graph(graph))
        self.details_variable.set(
            "Cycle-only view. Orange modules belong to a cyclic strongly connected "
            "component. Select a module for membership details."
        )

    def show_whole_project(self) -> None:
        if self._analysis is None:
            return
        graph = build_dependency_graph(
            self._analysis.module_identities, self._analysis.dependencies
        )
        self.current_result = None
        self._current_graph = graph
        self.canvas.set_layout(layout_graph(graph))
        warning = graph_readability_message(graph)
        self.details_variable.set(
            warning
            or (
                f"{len(graph.nodes)} modules · {len(graph.edges)} imports · "
                "advanced view"
            )
        )

    def current_graph(self):
        """Return the logical graph currently represented when available."""
        return self._current_graph

    def _rebuild(self) -> None:
        if self._analysis is None or self._selected is None:
            return
        self.current_result = build_contextual_architecture_graph(
            self._analysis,
            self._selected,
            direction=_DIRECTIONS[self.direction_variable.get()],
            depth=int(self.depth_variable.get()),
        )
        self._current_graph = self.current_result.graph
        self.canvas.set_layout(layout_graph(self.current_result.graph))
        self.canvas.select_node(self._selected.root_id)
        self._set_details(self._selected.root_id)

    def _set_details(self, node_id: str) -> None:
        if self._analysis is None:
            return
        details = module_details(self._analysis, node_id)
        if details is None:
            return
        cycle = (
            f"Cycle #{details.cycle_number}: {', '.join(details.cycle_modules)}"
            if details.cycle_number
            else "No dependency cycle"
        )
        self.details_variable.set(
            "\n".join(
                (
                    "Module",
                    details.module,
                    "",
                    "Source",
                    str(details.path),
                    "",
                    f"Internal dependencies ({len(details.dependencies)})",
                    *(f"→ {item}" for item in details.dependencies),
                    "",
                    f"Imported by ({len(details.imported_by)})",
                    *(f"← {item}" for item in details.imported_by),
                    "",
                    f"External imports: {len(details.external_imports)}",
                    f"Unresolved imports: {len(details.unresolved_imports)}",
                    f"Functions: {len(details.functions)}",
                    f"Classes: {len(details.classes)}",
                    cycle,
                )
            )
        )

    def _show_node_details(self, node: GraphNode) -> None:
        self._set_details(node.node_id)

    def _activate_node(self, node: GraphNode) -> None:
        self.select_root(node.node_id)

    def _search_event(self, _event: object) -> None:
        self.search(self.search_variable.get())

    def _select_event(self, _event: object) -> None:
        label = self.search_variable.get()
        root = next((item for item in self._filtered if item.label == label), None)
        if root:
            self.select_root(root.root_id)

    def _first_event(self, _event: object) -> None:
        matches = self.search(self.search_variable.get())
        if matches:
            self.select_root(matches[0].root_id)

    def _rebuild_event(self, _event: object) -> None:
        self._rebuild()
