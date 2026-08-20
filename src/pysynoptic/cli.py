"""Command-line interface for PySynoptic."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from pysynoptic.analyzer import analyze_project, analyze_python_file
from pysynoptic.models import FileAnalysis, ProjectAnalysis
from pysynoptic.renderers import render_mermaid, write_mermaid


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pysynoptic",
        description="Statically inspect a Python source file or project directory.",
    )
    parser.add_argument("path", type=Path, help="Python file or project to analyze")
    parser.add_argument(
        "--format",
        choices=("mermaid", "text"),
        default="text",
        help="Output format for the analysis (default: text)",
    )
    parser.add_argument("-o", "--output", type=Path, help="Write output to a file")
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
        f"Dependencies: {len(analysis.dependencies)}",
        "",
        "Files:",
    ]

    analyses_by_path = {item.path: item for item in analysis.file_analyses}
    if not analysis.module_identities:
        lines.append("- (none)")
    for module_identity in analysis.module_identities:
        relative_path = _relative_path(module_identity.path, analysis.root_path)
        file_analysis = analyses_by_path.get(module_identity.path)
        if file_analysis is None:
            status = " [analysis unavailable]"
        elif file_analysis.syntax_error is not None:
            status = " [syntax error]"
        else:
            status = ""
        lines.append(f"- {module_identity.dotted_name}{status}")
        lines.append(f"  {relative_path}")

    if analysis.dependencies:
        lines.extend(("", "Dependencies:"))
        for dependency in analysis.dependencies:
            lines.append(
                f"- {dependency.source.dotted_name} -> {dependency.target.dotted_name}"
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
            if args.format == "mermaid":
                if args.output is None:
                    print(render_mermaid(project_analysis), end="")
                else:
                    write_mermaid(project_analysis, args.output)
                    print(f"Wrote Mermaid graph to {args.output}")
            else:
                output = format_project_analysis(project_analysis)
                if args.output is None:
                    print(output)
                else:
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(f"{output}\n", encoding="utf-8")
                    print(f"Wrote analysis to {args.output}")
            has_syntax_errors = any(
                item.syntax_error is not None for item in project_analysis.file_analyses
            )
            return 1 if has_syntax_errors or project_analysis.errors else 0
        if args.path.is_file():
            if args.format == "mermaid":
                raise ValueError("Mermaid output requires a project directory")
            analysis = analyze_python_file(args.path)
            output = format_analysis(analysis)
            if args.output is None:
                print(output)
            else:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(f"{output}\n", encoding="utf-8")
                print(f"Wrote analysis to {args.output}")
            return 1 if analysis.syntax_error is not None else 0
        if not args.path.exists():
            raise FileNotFoundError(f"Path not found: {args.path}")
        raise ValueError(f"Expected a Python file or project directory: {args.path}")
    except (OSError, ValueError) as error:
        print(f"Error: {error}")
        return 2
