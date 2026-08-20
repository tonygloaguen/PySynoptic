"""Static analysis of individual Python source files."""

from __future__ import annotations

import ast
from pathlib import Path

from pysynoptic.models import FileAnalysis


def _import_names(node: ast.Import | ast.ImportFrom) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)

    module = f"{'.' * node.level}{node.module or ''}"
    separator = "" if module.endswith(".") else "."
    return tuple(f"{module}{separator}{alias.name}" for alias in node.names)


def _syntax_error_message(error: SyntaxError) -> str:
    location = f"line {error.lineno}"
    if error.offset is not None:
        location += f", column {error.offset}"
    return f"{error.msg} ({location})"


def analyze_python_file(path: Path) -> FileAnalysis:
    """Analyze top-level declarations in a Python file without executing it.

    The source is read as UTF-8 and passed directly to :func:`ast.parse`. Missing
    files raise :class:`FileNotFoundError`, invalid extensions raise
    :class:`ValueError`, and syntax errors are returned in the analysis model.
    """
    if path.suffix != ".py":
        raise ValueError(f"expected a .py file: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Python file not found: {path}")

    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        return FileAnalysis(
            path=path,
            module_name=path.stem,
            syntax_error=_syntax_error_message(error),
        )

    functions: list[str] = []
    classes: list[str] = []
    imports: list[str] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.extend(_import_names(node))

    return FileAnalysis(
        path=path,
        module_name=path.stem,
        functions=tuple(functions),
        classes=tuple(classes),
        imports=tuple(imports),
    )
