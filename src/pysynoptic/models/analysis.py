"""Models returned by the static analysis engine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pysynoptic.models.imports import ImportReference
from pysynoptic.models.symbols import CallableSymbol, CallReference


@dataclass(frozen=True, slots=True)
class FileAnalysis:
    """Structural information collected statically from one Python file."""

    path: Path
    module_name: str
    functions: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    imports: tuple[str, ...] = ()
    syntax_error: str | None = None
    import_references: tuple[ImportReference, ...] = ()
    callable_symbols: tuple[CallableSymbol, ...] = ()
    call_references: tuple[CallReference, ...] = ()
