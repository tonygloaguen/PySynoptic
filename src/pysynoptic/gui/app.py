"""ttkbootstrap desktop application for PySynoptic."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

import ttkbootstrap as ttk

from pysynoptic.graph import layout_dependency_graph
from pysynoptic.gui.controller import ApplicationController
from pysynoptic.gui.graph_canvas import DependencyGraphCanvas
from pysynoptic.gui.state import ApplicationState
from pysynoptic.models import ProjectAnalysis


class PySynopticApp(ttk.Window):
    """Main desktop window for selecting, analyzing, and exporting projects."""

    def __init__(self, controller: ApplicationController | None = None) -> None:
        super().__init__(themename="flatly")
        self.controller = controller or ApplicationController()
        self.state = ApplicationState()
        self._graph_analysis: ProjectAnalysis | None = None
        self._tree_graph_nodes: dict[str, str] = {}

        self.title("PySynoptic")
        self.geometry("1180x760")
        self.minsize(900, 600)

        self._build_toolbar()
        self._build_workspace()
        self._build_status_bar()
        self._render_state()

    def _build_toolbar(self) -> None:
        toolbar = ttk.Frame(self, padding=(12, 10))
        toolbar.pack(fill="x")

        ttk.Button(
            toolbar,
            text="Open Python File",
            command=self.open_python_file,
            bootstyle="secondary",
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            toolbar,
            text="Open Project",
            command=self.open_project,
            bootstyle="secondary",
        ).pack(side="left", padx=(0, 8))
        self.analyze_button = ttk.Button(
            toolbar,
            text="Analyze",
            command=self.analyze_selected,
            bootstyle="primary",
        )
        self.analyze_button.pack(side="left", padx=(8, 8))
        self.export_button = ttk.Button(
            toolbar,
            text="Export Mermaid",
            command=self.export_mermaid,
            bootstyle="success",
        )
        self.export_button.pack(side="right")

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
        self._add_graph_tab()
        self.dependencies_text = self._add_text_tab("Dependencies")
        self.mermaid_text = self._add_text_tab("Mermaid", fixed_width=True)

    def _add_graph_tab(self) -> None:
        self.graph_panel = ttk.Frame(self.notebook, padding=8)
        self.graph_canvas = DependencyGraphCanvas(self.graph_panel)
        self.graph_canvas.pack(fill="both", expand=True)
        self.notebook.add(self.graph_panel, text="Graph")

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
        self.state = self.controller.select_path(path)
        self._render_state()
        self._show_state_error()

    def analyze_selected(self) -> None:
        """Analyze the current selection synchronously and refresh all views."""
        self.state = self.controller.analyze(self.state)
        self._render_state()
        self._show_state_error()

    def export_mermaid(self) -> None:
        """Prompt for a destination and export the current project graph."""
        output = filedialog.asksaveasfilename(
            parent=self,
            title="Export Mermaid graph",
            defaultextension=".mmd",
            filetypes=(("Mermaid files", "*.mmd"), ("All files", "*.*")),
        )
        if not output:
            return
        try:
            output_path = self.controller.export_mermaid(self.state, Path(output))
        except (OSError, ValueError) as error:
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
        self.status_variable.set(self.state.status_message)
        self.analyze_button.configure(
            state="normal" if self.state.target_kind else "disabled"
        )
        self.export_button.configure(
            state="normal" if self.state.project_analysis else "disabled"
        )
        self._render_tree()
        self._render_graph()
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
            self.project_tree.insert("", "end", text=selected_path.name)
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

    def _render_graph(self) -> None:
        analysis = self.state.project_analysis
        if analysis is None:
            if self._graph_analysis is not None:
                self.graph_canvas.clear()
                self._graph_analysis = None
            return
        if analysis is self._graph_analysis:
            return
        self.graph_canvas.set_layout(layout_dependency_graph(analysis))
        self._graph_analysis = analysis

    def _navigate_tree_to_graph(self, _event: object) -> None:
        selected = self.project_tree.selection()
        if not selected:
            return
        node_id = self._tree_graph_nodes.get(selected[0])
        if node_id is None:
            return
        if self.graph_canvas.select_node(node_id, center=True):
            self.notebook.select(self.graph_panel)

    def _overview_content(self) -> str:
        if self.state.file_analysis is not None:
            analysis = self.state.file_analysis
            lines = [
                "Python file",
                "",
                f"Path: {analysis.path}",
                f"Module: {analysis.module_name}",
                f"Functions: {len(analysis.functions)}",
                f"Classes: {len(analysis.classes)}",
                f"Imports: {len(analysis.import_references)}",
            ]
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
