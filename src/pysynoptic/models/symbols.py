"""Callable symbols and unresolved static call references."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

CallableKind: TypeAlias = Literal["function", "method"]
CallKind: TypeAlias = Literal["attribute", "dynamic", "name"]
CallScopeKind: TypeAlias = Literal["callable", "class", "module"]


@dataclass(frozen=True, slots=True)
class CallableSymbol:
    """One statically declared synchronous or asynchronous callable."""

    symbol_id: str
    path: Path
    name: str
    qualified_name: str
    kind: CallableKind
    is_async: bool
    line: int
    column: int
    parent_symbol_id: str | None = None


@dataclass(frozen=True, slots=True)
class CallReference:
    """One unresolved call expression attributed to its lexical scope."""

    path: Path
    expression: str
    target: str | None
    kind: CallKind
    line: int
    column: int
    scope_kind: CallScopeKind
    scope_name: str
    caller_symbol_id: str | None = None
