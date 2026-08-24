"""On-demand intra-callable control-flow panel."""

from __future__ import annotations

from collections.abc import Callable
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
from pysynoptic.gui.project_tree import (
    CallableOption,
    callable_kind_label,
    callable_relation_context,
    callable_selector_options,
    callable_short_label,
)
from pysynoptic.models import (
    CallableFlowGraph,
    CallableIdentity,
    FlowNode,
    ProjectAnalysis,
)


class FlowPanel(ttk.Frame):
    """Select a callable and display its structural AST control flow."""

    def __init__(
        self,
        master: Any,
        *,
        on_show_calls: Callable[[str], None] | None = None,
        on_callable_selected: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master)
        self._analysis: ProjectAnalysis | None = None
        self._identities: tuple[CallableIdentity, ...] = ()
        self._filtered: tuple[CallableIdentity, ...] = ()
        self._selected: CallableIdentity | None = None
        self._nodes: dict[str, FlowNode] = {}
        self.current_flow: CallableFlowGraph | None = None
        self._current_graph: DependencyGraph | None = None
        self._options: tuple[CallableOption, ...] = ()
        self._on_show_calls = on_show_calls
        self._on_callable_selected = on_callable_selected
        self._relation_links: dict[str, str] = {}

        controls = ttk.Frame(self)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Label(controls, text="Function / method").pack(side="left")
        self.search_variable = ttk.StringVar()
        self.search_box = ttk.Combobox(controls, textvariable=self.search_variable)
        self.search_box.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.search_box.bind("<KeyRelease>", self._search_event)
        self.search_box.bind("<<ComboboxSelected>>", self._select_event)
        self.search_box.bind("<Return>", self._first_event)

        header = ttk.Labelframe(self, text="Selected callable", padding=(10, 7))
        header.pack(fill="x", pady=(0, 8))
        identity_panel = ttk.Frame(header)
        identity_panel.pack(side="left", fill="both", expand=True)
        self.header_title_variable = ttk.StringVar(value="Flow of: —")
        ttk.Label(
            identity_panel,
            textvariable=self.header_title_variable,
            font=("TkDefaultFont", 13, "bold"),
            anchor="w",
        ).pack(fill="x")
        self.header_metadata_variable = ttk.StringVar(
            value="Select a function or method."
        )
        ttk.Label(
            identity_panel,
            textvariable=self.header_metadata_variable,
            justify="left",
            anchor="nw",
            wraplength=540,
        ).pack(fill="x", pady=(3, 0))
        relation_panel = ttk.Frame(header)
        relation_panel.pack(side="right", fill="y", padx=(10, 0))
        self.relation_tree = ttk.Treeview(
            relation_panel,
            show="tree",
            height=4,
        )
        self.relation_tree.pack(fill="both", expand=True)
        self.relation_tree.bind("<Double-Button-1>", self._activate_relation)
        self.show_calls_button = ttk.Button(
            relation_panel,
            text="Show in Calls",
            command=self._show_in_calls,
            state="disabled",
        )
        self.show_calls_button.pack(fill="x", pady=(5, 0))

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
        self._options = callable_selector_options(analysis) if analysis else ()
        self.search_box.configure(values=tuple(item.label for item in self._options))
        self._selected = None
        self.current_flow = None
        self._current_graph = None
        self.canvas.clear()
        self.header_title_variable.set("Flow of: —")
        self.header_metadata_variable.set("Select a function or method.")
        self.relation_tree.delete(*self.relation_tree.get_children())
        self._relation_links.clear()
        self.show_calls_button.configure(state="disabled")
        self.details_variable.set(
            f"{len(self._identities)} callables available. Select one to build flow."
            if self._identities
            else "No callable is available."
        )
        if analysis is not None:
            preferred = default_flow_callable(analysis)
            if preferred is not None:
                self.select_callable(preferred.symbol.symbol_id, notify=False)

    def search(self, query: str) -> tuple[CallableIdentity, ...]:
        """Filter callable choices by qualified name."""
        self._filtered = (
            search_flow_callables(self._analysis, query)
            if self._analysis is not None
            else ()
        )
        filtered_ids = {item.symbol.symbol_id for item in self._filtered}
        self.search_box.configure(
            values=tuple(
                option.label
                for option in self._options
                if option.symbol_id in filtered_ids
            )
        )
        return self._filtered

    @property
    def selected_symbol_id(self) -> str | None:
        """Return the stable ID of the callable represented by Flow."""
        return self._selected.symbol.symbol_id if self._selected is not None else None

    def select_callable(
        self,
        symbol_id: str,
        *,
        render: bool = True,
        notify: bool = True,
    ) -> bool:
        """Build and display a callable flow by stable symbol ID."""
        identity = next(
            (item for item in self._identities if item.symbol.symbol_id == symbol_id),
            None,
        )
        if identity is None:
            return False
        changed = self.selected_symbol_id != symbol_id
        self._selected = identity
        option = next(
            (item for item in self._options if item.symbol_id == symbol_id), None
        )
        self.search_variable.set(
            option.label if option is not None else callable_short_label(identity)
        )
        self._render_callable_header(identity)
        if notify and self._on_callable_selected is not None:
            self._on_callable_selected(symbol_id)
        if not render:
            if changed:
                self.current_flow = None
                self._current_graph = None
                self._nodes.clear()
                self.canvas.clear()
                self.details_variable.set(
                    "Flow is ready to build for the selected callable."
                )
            return True
        if (
            self.current_flow is not None
            and self.current_flow.symbol_id == symbol_id
            and self._current_graph is not None
        ):
            return True
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

    def render_selected(self) -> bool:
        """Render the prepared callable when the Flow tab becomes active."""
        return bool(
            self._selected
            and self.select_callable(
                self._selected.symbol.symbol_id,
                render=True,
                notify=False,
            )
        )

    def current_graph(self) -> DependencyGraph | None:
        """Return the current logical CFG for Mermaid export."""
        return self._current_graph

    def _render_callable_header(self, identity: CallableIdentity) -> None:
        self.header_title_variable.set(f"Flow of: {callable_short_label(identity)}")
        self.header_metadata_variable.set(
            "\n".join(
                (
                    f"Module/File: {identity.module.dotted_name}  ›  "
                    f"{identity.module.path.name}",
                    f"Kind: {callable_kind_label(identity)} · "
                    f"Source: line {identity.symbol.line}",
                    f"Qualified: {identity.qualified_name}",
                )
            )
        )
        self.relation_tree.delete(*self.relation_tree.get_children())
        self._relation_links.clear()
        if self._analysis is None:
            return
        context = callable_relation_context(
            self._analysis,
            identity.symbol.symbol_id,
        )
        incoming = self.relation_tree.insert(
            "", "end", text=f"Called by ({len(context.incoming)})", open=True
        )
        outgoing = self.relation_tree.insert(
            "", "end", text=f"Calls ({len(context.outgoing)})", open=True
        )
        if not context.incoming:
            self.relation_tree.insert(incoming, "end", text="—")
        for relation in context.incoming:
            item = self.relation_tree.insert(
                incoming,
                "end",
                text=f"← {relation.label}",
            )
            if relation.symbol_id is not None:
                self._relation_links[item] = relation.symbol_id
        if not context.outgoing:
            self.relation_tree.insert(outgoing, "end", text="—")
        for relation in context.outgoing:
            item = self.relation_tree.insert(
                outgoing,
                "end",
                text=f"→ {relation.label}",
            )
            if relation.symbol_id is not None:
                self._relation_links[item] = relation.symbol_id
        self.show_calls_button.configure(
            state="normal" if self._on_show_calls is not None else "disabled"
        )

    def _activate_relation(self, _event: object) -> None:
        selected = self.relation_tree.selection()
        if selected and selected[0] in self._relation_links:
            self.select_callable(self._relation_links[selected[0]])

    def _show_in_calls(self) -> None:
        if self._selected is not None and self._on_show_calls is not None:
            self._on_show_calls(self._selected.symbol.symbol_id)

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
        option = next((item for item in self._options if item.label == label), None)
        if option:
            self.select_callable(option.symbol_id)

    def _first_event(self, _event: object) -> None:
        matches = self.search(self.search_variable.get())
        if matches:
            self.select_callable(matches[0].symbol.symbol_id)
