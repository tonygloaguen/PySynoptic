"""Static analysis of individual Python source files."""

from __future__ import annotations

import ast
from pathlib import Path

from pysynoptic.models import FileAnalysis, ImportReference


def _import_references(
    node: ast.Import | ast.ImportFrom,
) -> tuple[ImportReference, ...]:
    if isinstance(node, ast.Import):
        return tuple(
            ImportReference(
                kind="import",
                module=alias.name,
                imported_name=None,
                alias=alias.asname,
                level=0,
                line=node.lineno,
                column=node.col_offset,
            )
            for alias in node.names
        )

    return tuple(
        ImportReference(
            kind="from",
            module=node.module,
            imported_name=alias.name,
            alias=alias.asname,
            level=node.level,
            line=node.lineno,
            column=node.col_offset,
        )
        for alias in node.names
    )


def _legacy_import_name(reference: ImportReference) -> str:
    if reference.kind == "import":
        return reference.module or ""

    module = f"{'.' * reference.level}{reference.module or ''}"
    separator = "" if module.endswith(".") else "."
    return f"{module}{separator}{reference.imported_name}"


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
    import_references: list[ImportReference] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)

    import_nodes = sorted(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ),
        key=lambda node: (node.lineno, node.col_offset),
    )
    for node in import_nodes:
        references = _import_references(node)
        import_references.extend(references)
        imports.extend(_legacy_import_name(reference) for reference in references)

    return FileAnalysis(
        path=path,
        module_name=path.stem,
        functions=tuple(functions),
        classes=tuple(classes),
        imports=tuple(imports),
        import_references=tuple(import_references),
    )
