"""Structured metadata for statically discovered Python imports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

ImportKind: TypeAlias = Literal["from", "import"]


@dataclass(frozen=True, slots=True)
class ImportReference:
    """One imported name extracted directly from an AST import node."""

    kind: ImportKind
    module: str | None
    imported_name: str | None
    alias: str | None
    level: int
    line: int
    column: int
