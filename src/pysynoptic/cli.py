"""Command-line interface for PySynoptic."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from pysynoptic.analyzer import analyze_project, analyze_python_file
from pysynoptic.models import FileAnalysis, ProjectAnalysis


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pysynoptic",
        description="Statically inspect a Python source file or project directory.",
    )
    parser.add_argument("path", type=Path, help="Python file or project to analyze")
    return parser


def _format_items(label: str, items: tuple[str, ...]) -> str:
    value = ", ".join(items) if items else "(none)"
    return f"{label}: {value}"


def format_analysis(analysis: FileAnalysis) -> str:
    """Format a file analysis for display in a terminal."""
    lines = [
        f"File: {analysis.path}",
        f"Module: {analysis.module_name}",
        _format_items("Functions", analysis.functions),
        _format_items("Classes", analysis.classes),
        _format_items("Imports", analysis.imports),
    ]
    if analysis.syntax_error is not None:
        lines.append(f"Syntax error: {analysis.syntax_error}")
    return "\n".join(lines)


def _relative_path(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def format_project_analysis(analysis: ProjectAnalysis) -> str:
    """Format a project analysis for display in a terminal."""
    function_count = sum(len(item.functions) for item in analysis.file_analyses)
    class_count = sum(len(item.classes) for item in analysis.file_analyses)
    syntax_error_count = sum(
        item.syntax_error is not None for item in analysis.file_analyses
    )
    project_name = analysis.root_path.resolve().name or str(analysis.root_path)
    lines = [
        f"Project: {project_name}",
        f"Python files: {len(analysis.python_files)}",
        f"Resources: {len(analysis.resources)}",
        f"Functions: {function_count}",
        f"Classes: {class_count}",
        f"Syntax errors: {syntax_error_count}",
        "",
        "Files:",
    ]

    analyses_by_path = {item.path: item for item in analysis.file_analyses}
    if not analysis.python_files:
        lines.append("- (none)")
    for python_file in analysis.python_files:
        relative_path = _relative_path(python_file, analysis.root_path)
        file_analysis = analyses_by_path.get(python_file)
        if file_analysis is None:
            lines.append(f"- {relative_path}: analysis unavailable")
        elif file_analysis.syntax_error is not None:
            lines.append(f"- {relative_path}: syntax error")
        else:
            lines.append(
                f"- {relative_path}: {len(file_analysis.functions)} functions, "
                f"{len(file_analysis.classes)} classes"
            )

    if analysis.errors:
        lines.extend(("", "Errors:"))
        for error in analysis.errors:
            relative_path = _relative_path(error.path, analysis.root_path)
            lines.append(f"- {relative_path}: {error.message}")

    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the PySynoptic command-line interface."""
    args = _build_parser().parse_args(argv)

    try:
        if args.path.is_dir():
            project_analysis = analyze_project(args.path)
            print(format_project_analysis(project_analysis))
            has_syntax_errors = any(
                item.syntax_error is not None for item in project_analysis.file_analyses
            )
            return 1 if has_syntax_errors or project_analysis.errors else 0
        if args.path.is_file():
            analysis = analyze_python_file(args.path)
            print(format_analysis(analysis))
            return 1 if analysis.syntax_error is not None else 0
        if not args.path.exists():
            raise FileNotFoundError(f"Path not found: {args.path}")
        raise ValueError(f"Expected a Python file or project directory: {args.path}")
    except (OSError, ValueError) as error:
        print(f"Error: {error}")
        return 2
