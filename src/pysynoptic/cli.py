"""Command-line interface for PySynoptic."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from pysynoptic.analyzer import analyze_python_file
from pysynoptic.models import FileAnalysis


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pysynoptic",
        description="Inspect the top-level structure of a Python source file.",
    )
    parser.add_argument("path", type=Path, help="Python file to analyze")
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


def main(argv: Sequence[str] | None = None) -> int:
    """Run the PySynoptic command-line interface."""
    args = _build_parser().parse_args(argv)

    try:
        analysis = analyze_python_file(args.path)
    except (OSError, ValueError) as error:
        print(f"Error: {error}")
        return 2

    print(format_analysis(analysis))
    return 1 if analysis.syntax_error is not None else 0
