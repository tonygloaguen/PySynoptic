"""ttkbootstrap desktop application for PySynoptic."""

from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

import ttkbootstrap as ttk

from pysynoptic.graph import layout_dependency_graph
from pysynoptic.gui.analysis_runner import AnalysisRunner
from pysynoptic.gui.architecture import ArchitecturePanel
from pysynoptic.gui.call_graph import ContextualCallGraphPanel
from pysynoptic.gui.controller import ApplicationController
from pysynoptic.gui.flow import FlowPanel
from pysynoptic.gui.state import (
    ApplicationState,
    controls_for_state,
    mark_analysis_started,
)
from pysynoptic.renderers import render_mermaid_export


class PySynopticApp(ttk.Window):
    """Main desktop window for selecting, analyzing, and exporting projects."""

    def __init__(self, controller: ApplicationController | None = None) -> None:
        super().__init__(themename="flatly")
        self.controller = controller or ApplicationController()
        self.state = ApplicationState()
        self._tree_graph_nodes: dict[str, str] = {}
        self._analysis_runner = AnalysisRunner(self.controller.analyze)
        self._analysis_poll_id: str | None = None
        self._active_mermaid_mode = "architecture"

        self.title("PySynoptic")
        self.geometry("1180x760")
        self.minsize(900, 600)
        self.protocol("WM_DELETE_WINDOW", self._close_application)

        self._build_toolbar()
        self._build_workspace()
        self._build_status_bar()
        self._render_state()

    def _build_toolbar(self) -> None:
        toolbar = ttk.Frame(self, padding=(12, 10))
        toolbar.pack(fill="x")

        self.open_file_button = ttk.Button(
            toolbar,
            text="Open Python File",
            command=self.open_python_file,
            bootstyle="secondary",
        )
        self.open_file_button.pack(side="left", padx=(0, 8))
        self.open_project_button = ttk.Button(
            toolbar,
            text="Open Project",
            command=self.open_project,
            bootstyle="secondary",
        )
        self.open_project_button.pack(side="left", padx=(0, 8))
        self.analyze_button = ttk.Button(
            toolbar,
            text="Analyze",
            command=self.analyze_selected,
            bootstyle="primary",
        )
        self.analyze_button.pack(side="left", padx=(8, 8))
        self.explore_calls_button = ttk.Button(
            toolbar,
            text="Explore Calls",
            command=lambda: self.notebook.select(self.call_graph_panel),
            bootstyle="secondary-outline",
        )
        self.explore_calls_button.pack(side="left", padx=(0, 6))
        self.explore_flow_button = ttk.Button(
            toolbar,
            text="Explore Flow",
            command=lambda: self.notebook.select(self.flow_panel),
            bootstyle="secondary-outline",
        )
        self.explore_flow_button.pack(side="left")
        self.export_button = ttk.Menubutton(
            toolbar,
            text="Export Mermaid ▾",
            bootstyle="success",
        )
        self.export_button.pack(side="right")
        export_menu = tk.Menu(self.export_button, tearoff=False)
        export_menu.add_command(
            label="Current architecture view",
            command=lambda: self.export_mermaid("architecture"),
        )
        export_menu.add_command(
            label="Current call graph",
            command=lambda: self.export_mermaid("calls"),
        )
        export_menu.add_command(
            label="Current function flow",
            command=lambda: self.export_mermaid("flow"),
        )
        export_menu.add_separator()
        export_menu.add_command(
            label="Whole project architecture",
            command=lambda: self.export_mermaid("whole"),
        )
        self.export_button.configure(menu=export_menu)

    def _build_workspace(self) -> None:
        workspace = ttk.Panedwindow(self, orient="horizontal")
        workspace.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        tree_panel = ttk.Frame(workspace, padding=8)
        detail_panel = ttk.Frame(workspace, padding=8)
        workspace.add(tree_panel, weight=1)
        workspace.add(detail_panel, weight=3)

        ttk.Label(
            tree_panel,
            text="Project tree",
            font=("TkDefaultFont", 11, "bold"),
        ).pack(anchor="w", pady=(0, 6))
        self.project_tree = ttk.Treeview(tree_panel, show="tree")
        tree_scrollbar = ttk.Scrollbar(
            tree_panel,
            orient="vertical",
            command=self.project_tree.yview,
        )
        self.project_tree.configure(yscrollcommand=tree_scrollbar.set)
        self.project_tree.pack(side="left", fill="both", expand=True)
        tree_scrollbar.pack(side="right", fill="y")
        self.project_tree.bind("<<TreeviewSelect>>", self._navigate_tree_to_graph)

        self.notebook = ttk.Notebook(detail_panel)
        self.notebook.pack(fill="both", expand=True)
        self.overview_text = self._add_text_tab("Overview")
        self._add_architecture_tab()
        self._add_call_graph_tab()
        self._add_flow_tab()
        self.dependencies_text = self._add_text_tab("Dependencies")
        self.mermaid_text = self._add_text_tab("Mermaid", fixed_width=True)
        self.notebook.bind("<<NotebookTabChanged>>", self._notebook_changed)

    def _add_architecture_tab(self) -> None:
        self.architecture_panel = ArchitecturePanel(self.notebook)
        self.graph_panel = self.architecture_panel
        self.graph_canvas = self.architecture_panel.canvas
        self.notebook.add(self.architecture_panel, text="Architecture")

    def _add_call_graph_tab(self) -> None:
        self.call_graph_panel = ContextualCallGraphPanel(
            self.notebook, on_open_flow=self._open_flow
        )
        self.notebook.add(self.call_graph_panel, text="Calls")

    def _add_flow_tab(self) -> None:
        self.flow_panel = FlowPanel(self.notebook)
        self.notebook.add(self.flow_panel, text="Flow")

    def _add_text_tab(self, label: str, *, fixed_width: bool = False) -> ScrolledText:
        panel = ttk.Frame(self.notebook, padding=8)
        text = ScrolledText(
            panel,
            wrap="none" if fixed_width else "word",
            borderwidth=0,
            padx=10,
            pady=10,
            font="TkFixedFont" if fixed_width else "TkDefaultFont",
        )
        text.pack(fill="both", expand=True)
        text.configure(state="disabled")
        self.notebook.add(panel, text=label)
        return text

    def _build_status_bar(self) -> None:
        self.status_variable = ttk.StringVar(value=self.state.status_message)
        ttk.Label(
            self,
            textvariable=self.status_variable,
            anchor="w",
            padding=(12, 7),
            bootstyle="inverse-secondary",
        ).pack(fill="x", side="bottom")

    def open_python_file(self) -> None:
        """Prompt for a Python source file and select it."""
        selected = filedialog.askopenfilename(
            parent=self,
            title="Open Python file",
            filetypes=(("Python files", "*.py"), ("All files", "*.*")),
        )
        if selected:
            self._select_path(Path(selected))

    def open_project(self) -> None:
        """Prompt for a project directory and select it."""
        selected = filedialog.askdirectory(parent=self, title="Open project")
        if selected:
            self._select_path(Path(selected))

    def _select_path(self, path: Path) -> None:
        self._analysis_runner.invalidate()
        self.state = self.controller.select_path(path)
        self._render_state()
        self._show_state_error()

    def analyze_selected(self) -> None:
        """Submit the current selection for background static analysis."""
        if self.state.selected_path is None or self.state.target_kind is None:
            self.state = self.controller.analyze(self.state)
            self._render_state()
            self._show_state_error()
            return
        if self.state.is_analyzing:
            return

        request_state = replace(self.state, is_analyzing=False)
        self._analysis_runner.submit(request_state)
        self.state = mark_analysis_started(self.state)
        self._render_state()
        self._schedule_analysis_poll()

    def _schedule_analysis_poll(self) -> None:
        if self._analysis_poll_id is None:
            self._analysis_poll_id = self.after(25, self._poll_analysis)

    def _poll_analysis(self) -> None:
        self._analysis_poll_id = None
        completed = self._analysis_runner.poll_latest()
        if completed is not None:
            self.state = completed
            self._render_state()
            self._show_state_error()
        elif self.state.is_analyzing:
            self._schedule_analysis_poll()

    def _close_application(self) -> None:
        if self._analysis_poll_id is not None:
            self.after_cancel(self._analysis_poll_id)
            self._analysis_poll_id = None
        self._analysis_runner.shutdown()
        self.destroy()

    def export_mermaid(self, mode: str = "architecture") -> None:
        """Export one explicit current-view or whole-project Mermaid graph."""
        source = self._mermaid_for_mode(mode)
        if source is None:
            messagebox.showinfo(
                "PySynoptic",
                "Select and display that graph before exporting it.",
                parent=self,
            )
            return
        output = filedialog.asksaveasfilename(
            parent=self,
            title="Export Mermaid graph",
            defaultextension=".mmd",
            filetypes=(("Mermaid files", "*.mmd"), ("All files", "*.*")),
        )
        if not output:
            return
        try:
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(source, encoding="utf-8")
        except OSError as error:
            messagebox.showerror("PySynoptic", str(error), parent=self)
            self.status_variable.set(f"Export failed: {error}")
            return

        self.state = replace(
            self.state,
            status_message=f"Mermaid graph exported to {output_path}",
            error_message=None,
        )
        self._render_state()

    def _show_state_error(self) -> None:
        if self.state.error_message:
            messagebox.showerror(
                "PySynoptic",
                self.state.error_message,
                parent=self,
            )

    def _render_state(self) -> None:
        controls = controls_for_state(self.state)
        selection_state = "normal" if controls.can_select else "disabled"
        self.open_file_button.configure(state=selection_state)
        self.open_project_button.configure(state=selection_state)
        self.status_variable.set(self.state.status_message)
        self.analyze_button.configure(
            state="normal" if controls.can_analyze else "disabled"
        )
        self.export_button.configure(
            state="normal" if controls.can_export else "disabled"
        )
        explore_state = "normal" if self.state.project_analysis else "disabled"
        self.explore_calls_button.configure(state=explore_state)
        self.explore_flow_button.configure(state=explore_state)
        self._render_tree()
        self.architecture_panel.set_analysis(self.state.project_analysis)
        self.call_graph_panel.set_analysis(self.state.project_analysis)
        self.flow_panel.set_analysis(self.state.project_analysis)
        self._set_text(self.overview_text, self._overview_content())
        self._set_text(self.dependencies_text, self._dependencies_content())
        self._set_text(
            self.mermaid_text,
            self.state.mermaid_source or "Analyze a project to generate Mermaid.",
        )

    @staticmethod
    def _set_text(widget: ScrolledText, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    def _render_tree(self) -> None:
        self._tree_graph_nodes.clear()
        self.project_tree.delete(*self.project_tree.get_children())
        selected_path = self.state.selected_path
        if selected_path is None:
            self.project_tree.insert("", "end", text="No selection")
            return

        if self.state.target_kind == "file":
            item = self.project_tree.insert("", "end", text=selected_path.name)
            analysis = self.state.project_analysis
            if analysis and analysis.module_identities:
                self._tree_graph_nodes[item] = analysis.module_identities[
                    0
                ].path.as_posix()
            return

        root_id = self.project_tree.insert(
            "",
            "end",
            text=selected_path.name or str(selected_path),
            open=True,
        )
        analysis = self.state.project_analysis
        if analysis is None:
            return

        module_paths = {
            identity.path: identity.path.as_posix()
            for identity in analysis.module_identities
        }
        paths = list(analysis.python_files)
        paths.extend(resource.path for resource in analysis.resources)
        tree_items: dict[tuple[str, ...], str] = {(): root_id}
        for path in sorted(paths, key=lambda item: item.as_posix().casefold()):
            try:
                relative_path = path.relative_to(analysis.root_path)
            except ValueError:
                relative_path = path
            parent_key: tuple[str, ...] = ()
            for part in relative_path.parts:
                key = (*parent_key, part)
                if key not in tree_items:
                    tree_items[key] = self.project_tree.insert(
                        tree_items[parent_key],
                        "end",
                        text=part,
                    )
                parent_key = key
            node_id = module_paths.get(path)
            if node_id is not None:
                self._tree_graph_nodes[tree_items[parent_key]] = node_id

    def _navigate_tree_to_graph(self, _event: object) -> None:
        selected = self.project_tree.selection()
        if not selected:
            return
        node_id = self._tree_graph_nodes.get(selected[0])
        if node_id is None:
            return
        if self.architecture_panel.select_root(node_id):
            self.notebook.select(self.architecture_panel)

    def _open_flow(self, symbol_id: str) -> None:
        if self.flow_panel.select_callable(symbol_id):
            self.notebook.select(self.flow_panel)

    def _mermaid_for_mode(self, mode: str) -> str | None:
        analysis = self.state.project_analysis
        if analysis is None:
            return None
        if mode == "whole":
            return render_mermaid_export("whole", analysis)
        if mode == "architecture":
            graph = self.architecture_panel.current_graph()
        elif mode == "calls":
            graph = self.call_graph_panel.current_graph()
        elif mode == "flow":
            graph = self.flow_panel.current_graph()
        else:
            raise ValueError(f"Unsupported Mermaid export mode: {mode}")
        return (
            render_mermaid_export(mode, analysis, graph) if graph is not None else None
        )

    def _notebook_changed(self, _event: object) -> None:
        tab_name = self.notebook.tab(self.notebook.select(), "text")
        modes = {"Architecture": "architecture", "Calls": "calls", "Flow": "flow"}
        if tab_name in modes:
            self._active_mermaid_mode = modes[tab_name]
            return
        if tab_name == "Mermaid" and self.state.project_analysis is not None:
            source = self._mermaid_for_mode(self._active_mermaid_mode)
            self._set_text(
                self.mermaid_text,
                source or "Select a focused Architecture, Calls, or Flow graph first.",
            )

    def _overview_content(self) -> str:
        if self.state.file_analysis is not None:
            analysis = self.state.file_analysis
            method_count = sum(
                symbol.kind == "method" for symbol in analysis.callable_symbols
            )
            lines = [
                "Python file",
                "",
                f"Path: {analysis.path}",
                f"Module: {analysis.module_name}",
                f"Functions: {len(analysis.functions)}",
                f"Classes: {len(analysis.classes)}",
                f"Imports: {len(analysis.import_references)}",
                f"Methods: {method_count}",
                f"Call references: {len(analysis.call_references)}",
            ]
            project = self.state.project_analysis
            if project:
                statuses = {
                    status: sum(
                        resolution.status == status
                        for resolution in project.call_resolutions
                    )
                    for status in ("resolved", "ambiguous", "unresolved", "dynamic")
                }
                lines.extend(
                    (
                        f"Resolved calls: {statuses['resolved']}",
                        f"Ambiguous calls: {statuses['ambiguous']}",
                        f"Unresolved calls: {statuses['unresolved']}",
                        f"Dynamic calls: {statuses['dynamic']}",
                        "",
                        "Use Calls for caller/callee context and Flow for "
                        "intra-function structure.",
                    )
                )
            if analysis.syntax_error:
                lines.append(f"Syntax error: {analysis.syntax_error}")
            return "\n".join(lines)

        if self.state.project_analysis is not None:
            analysis = self.state.project_analysis
            function_count = sum(len(item.functions) for item in analysis.file_analyses)
            class_count = sum(len(item.classes) for item in analysis.file_analyses)
            syntax_error_count = sum(
                item.syntax_error is not None for item in analysis.file_analyses
            )
            cycle_count = layout_dependency_graph(analysis).cyclic_component_count
            return "\n".join(
                (
                    "Project overview",
                    "",
                    f"Project: {analysis.root_path.name or analysis.root_path}",
                    f"Root: {analysis.root_path}",
                    f"Python files: {len(analysis.python_files)}",
                    f"Resources: {len(analysis.resources)}",
                    f"Modules: {len(analysis.module_identities)}",
                    f"Functions: {function_count}",
                    f"Classes: {class_count}",
                    f"Dependencies: {len(analysis.dependencies)}",
                    f"Callable symbols: {len(analysis.callable_identities)}",
                    f"Resolved call dependencies: {len(analysis.call_dependencies)}",
                    f"Dependency cycles: {cycle_count}",
                    f"Syntax errors: {syntax_error_count}",
                    f"Analysis errors: {len(analysis.errors)}",
                )
            )

        if self.state.selected_path:
            return (
                f"Selected: {self.state.selected_path}\n\n"
                "Select Analyze to inspect this target statically."
            )
        return "Open a Python file or project to begin."

    def _dependencies_content(self) -> str:
        analysis = self.state.project_analysis
        if analysis is None:
            return "Analyze a project to list module dependencies."
        if not analysis.dependencies:
            return "No resolved internal module dependencies."
        return "\n".join(
            f"{dependency.source.dotted_name} -> {dependency.target.dotted_name}"
            for dependency in analysis.dependencies
        )


def main() -> None:
    """Launch the PySynoptic desktop application."""
    app = PySynopticApp()
    app.mainloop()
