"""Models returned by the static analysis engine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FileAnalysis:
    """Top-level structural information collected from one Python file."""

    path: Path
    module_name: str
    functions: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    imports: tuple[str, ...] = ()
    syntax_error: str | None = None
