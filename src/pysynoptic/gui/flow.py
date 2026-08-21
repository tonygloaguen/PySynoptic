"""On-demand intra-callable control-flow panel."""

from __future__ import annotations

from typing import Any

import ttkbootstrap as ttk

from pysynoptic.analyzer import analyze_callable_flow
from pysynoptic.graph import (
    DependencyGraph,
    GraphNode,
    build_function_flow_graph,
    layout_vertical_graph,
)
from pysynoptic.gui.graph_canvas import DependencyGraphCanvas
from pysynoptic.gui.graph_helpers import default_flow_callable, search_flow_callables
from pysynoptic.models import (
    CallableFlowGraph,
    CallableIdentity,
    FlowNode,
    ProjectAnalysis,
)


class FlowPanel(ttk.Frame):
    """Select a callable and display its structural AST control flow."""

    def __init__(self, master: Any) -> None:
        super().__init__(master)
        self._analysis: ProjectAnalysis | None = None
        self._identities: tuple[CallableIdentity, ...] = ()
        self._filtered: tuple[CallableIdentity, ...] = ()
        self._selected: CallableIdentity | None = None
        self._nodes: dict[str, FlowNode] = {}
        self.current_flow: CallableFlowGraph | None = None
        self._current_graph: DependencyGraph | None = None

        controls = ttk.Frame(self)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Label(controls, text="Function / method").pack(side="left")
        self.search_variable = ttk.StringVar()
        self.search_box = ttk.Combobox(controls, textvariable=self.search_variable)
        self.search_box.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.search_box.bind("<KeyRelease>", self._search_event)
        self.search_box.bind("<<ComboboxSelected>>", self._select_event)
        self.search_box.bind("<Return>", self._first_event)

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)
        graph = ttk.Frame(body)
        details = ttk.Labelframe(body, text="Flow step details", padding=10)
        body.add(graph, weight=4)
        body.add(details, weight=1)
        self.canvas = DependencyGraphCanvas(
            graph,
            on_select=self._show_node,
            node_label="steps",
            edge_label="transitions",
            empty_message="Select a function or method to build its static flow.",
            minimum_fit_scale=0.65,
            mute_unselected=False,
        )
        self.canvas.pack(fill="both", expand=True)
        self.details_variable = ttk.StringVar(value="Select a callable.")
        ttk.Label(
            details,
            textvariable=self.details_variable,
            justify="left",
            anchor="nw",
            wraplength=280,
        ).pack(fill="both", expand=True)
        ttk.Label(
            self,
            text=(
                "Legend: next · true/false · loop/done · except/finally · "
                "return/break/continue"
            ),
            bootstyle="secondary",
        ).pack(fill="x", pady=(6, 0))

    def set_analysis(self, analysis: ProjectAnalysis | None) -> None:
        """Replace the analysis without eagerly constructing any CFG."""
        if analysis is self._analysis:
            return
        self._analysis = analysis
        self._identities = search_flow_callables(analysis, "") if analysis else ()
        self._filtered = self._identities
        self.search_box.configure(
            values=tuple(item.qualified_name for item in self._identities)
        )
        self._selected = None
        self.current_flow = None
        self._current_graph = None
        self.canvas.clear()
        self.details_variable.set(
            f"{len(self._identities)} callables available. Select one to build flow."
            if self._identities
            else "No callable is available."
        )
        if analysis is not None:
            preferred = default_flow_callable(analysis)
            if preferred is not None:
                self.select_callable(preferred.symbol.symbol_id)

    def search(self, query: str) -> tuple[CallableIdentity, ...]:
        """Filter callable choices by qualified name."""
        self._filtered = (
            search_flow_callables(self._analysis, query)
            if self._analysis is not None
            else ()
        )
        self.search_box.configure(
            values=tuple(item.qualified_name for item in self._filtered)
        )
        return self._filtered

    def select_callable(self, symbol_id: str) -> bool:
        """Build and display a callable flow by stable symbol ID."""
        identity = next(
            (item for item in self._identities if item.symbol.symbol_id == symbol_id),
            None,
        )
        if identity is None:
            return False
        self._selected = identity
        self.search_variable.set(identity.qualified_name)
        try:
            flow = analyze_callable_flow(identity.module.path, identity.symbol)
        except (OSError, SyntaxError, ValueError) as error:
            self.canvas.clear()
            self.details_variable.set(f"Flow analysis failed: {error}")
            return False
        self.current_flow = flow
        self._nodes = {node.node_id: node for node in flow.nodes}
        self._current_graph = build_function_flow_graph(flow)
        self.canvas.set_layout(layout_vertical_graph(self._current_graph))
        self.details_variable.set(self._flow_overview(flow))
        return True

    def current_graph(self) -> DependencyGraph | None:
        """Return the current logical CFG for Mermaid export."""
        return self._current_graph

    def _show_node(self, node: GraphNode) -> None:
        flow_node = self._nodes.get(node.node_id)
        if flow_node:
            self._show_flow_node(flow_node)

    def _show_flow_node(self, node: FlowNode) -> None:
        resolved = self._resolved_targets(node)
        self.details_variable.set(
            "\n".join(
                (
                    "Type",
                    node.kind,
                    "",
                    "Summary",
                    node.label,
                    "",
                    "Source",
                    f"{self.current_flow.path if self.current_flow else ''}:"
                    f"{node.line}:{node.column}",
                    "",
                    "Static detail",
                    node.detail,
                    "",
                    "Resolved call target(s)",
                    *(resolved or ("—",)),
                )
            )
        )

    def _resolved_targets(self, node: FlowNode) -> tuple[str, ...]:
        if self._analysis is None or self._selected is None or node.kind != "call":
            return ()
        return tuple(
            sorted(
                {
                    target.qualified_name
                    for resolution in self._analysis.call_resolutions
                    if resolution.reference.caller_symbol_id
                    == self._selected.symbol.symbol_id
                    and resolution.reference.line == node.line
                    and resolution.status == "resolved"
                    for target in resolution.targets
                }
            )
        )

    @staticmethod
    def _flow_overview(flow: CallableFlowGraph) -> str:
        structural_kinds = {
            "break",
            "continue",
            "except",
            "finally",
            "if",
            "loop",
            "raise",
            "return",
            "try",
        }
        structural = [
            node
            for node in sorted(flow.nodes, key=lambda item: (item.line, item.column))
            if node.kind in structural_kinds
        ]
        if not any(node.kind in {"if", "loop", "try"} for node in structural):
            structural = [
                node
                for node in sorted(
                    flow.nodes, key=lambda item: (item.line, item.column)
                )
                if node.kind in {"call", "return"}
            ]
        section_label = (
            "Structure"
            if any(node.kind in {"if", "loop", "try"} for node in structural)
            else "Pipeline"
        )
        summary = [
            "Function flow",
            f"{flow.name}()",
            "",
            "Source",
            f"{flow.path}:{flow.line}",
            "",
            f"Steps: {len(flow.nodes)}",
            f"Branches: {sum(node.kind == 'if' for node in flow.nodes)}",
            f"Loops: {sum(node.kind == 'loop' for node in flow.nodes)}",
            f"Exception handlers: {sum(node.kind == 'except' for node in flow.nodes)}",
            "",
            section_label,
        ]
        summary.extend(f"→ {node.label}" for node in structural[:14])
        if len(structural) > 14:
            summary.append(f"… {len(structural) - 14} more steps")
        summary.extend(("", "Click a graph step for source and resolution details."))
        return "\n".join(summary)

    def _search_event(self, _event: object) -> None:
        self.search(self.search_variable.get())

    def _select_event(self, _event: object) -> None:
        label = self.search_variable.get()
        identity = next(
            (item for item in self._filtered if item.qualified_name == label), None
        )
        if identity:
            self.select_callable(identity.symbol.symbol_id)

    def _first_event(self, _event: object) -> None:
        matches = self.search(self.search_variable.get())
        if matches:
            self.select_callable(matches[0].symbol.symbol_id)
