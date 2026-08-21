"""GUI orchestration independent from desktop widgets."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from pysynoptic.analyzer import analyze_project, analyze_python_file_context
from pysynoptic.gui.state import ApplicationState
from pysynoptic.renderers import render_mermaid, write_mermaid


class ApplicationController:
    """Coordinate selection, static analysis, and Mermaid export."""

    def select_path(self, path: Path) -> ApplicationState:
        """Validate and select a Python file or project directory."""
        if path.is_dir():
            return ApplicationState(
                selected_path=path,
                target_kind="project",
                status_message=f"Project selected: {path}",
            )
        if path.is_file() and path.suffix == ".py":
            return ApplicationState(
                selected_path=path,
                target_kind="file",
                status_message=f"Python file selected: {path}",
            )
        if not path.exists():
            message = f"Path not found: {path}"
        elif path.is_file():
            message = f"Expected a .py file or project directory: {path}"
        else:
            message = f"Unsupported path: {path}"
        return ApplicationState(
            selected_path=path,
            status_message=message,
            error_message=message,
        )

    def analyze(self, state: ApplicationState) -> ApplicationState:
        """Analyze the currently selected target without executing source."""
        if state.selected_path is None or state.target_kind is None:
            message = "Choose a Python file or project before analyzing."
            return replace(
                state,
                is_analyzing=False,
                status_message=message,
                error_message=message,
            )

        try:
            if state.target_kind == "file":
                project_analysis = analyze_python_file_context(state.selected_path)
                analysis = project_analysis.file_analyses[0]
                has_syntax_error = analysis.syntax_error is not None
                status = (
                    "File analysis completed with a syntax error."
                    if has_syntax_error
                    else "File analysis complete."
                )
                return replace(
                    state,
                    file_analysis=analysis,
                    project_analysis=project_analysis,
                    mermaid_source=render_mermaid(project_analysis),
                    is_analyzing=False,
                    status_message=status,
                    error_message=None,
                )

            analysis = analyze_project(state.selected_path)
            syntax_error_count = sum(
                item.syntax_error is not None for item in analysis.file_analyses
            )
            warning_count = syntax_error_count + len(analysis.errors)
            status = (
                f"Project analysis complete with {warning_count} warning(s)."
                if warning_count
                else "Project analysis complete."
            )
            return replace(
                state,
                file_analysis=None,
                project_analysis=analysis,
                mermaid_source=render_mermaid(analysis),
                is_analyzing=False,
                status_message=status,
                error_message=None,
            )
        except (OSError, ValueError) as error:
            message = f"Analysis failed: {error}"
            return replace(
                state,
                is_analyzing=False,
                status_message=message,
                error_message=message,
            )

    def export_mermaid(self, state: ApplicationState, output_path: Path) -> Path:
        """Export the current project graph or raise a clear usage error."""
        if state.project_analysis is None:
            raise ValueError("Analyze a project before exporting Mermaid.")
        return write_mermaid(state.project_analysis, output_path)
