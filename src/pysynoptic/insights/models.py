"""Immutable models for deterministic static facts and future insights."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from pysynoptic.models.symbols import CallableKind

ArgumentKind: TypeAlias = Literal[
    "keyword_only",
    "positional",
    "positional_only",
    "vararg",
    "varkw",
]
OperationCategory: TypeAlias = Literal[
    "environment",
    "io",
    "logging",
    "network",
    "process",
]
InsightConfidence: TypeAlias = Literal["high", "medium", "unknown"]


@dataclass(frozen=True, slots=True)
class ParameterFacts:
    """One syntactically declared callable parameter."""

    name: str
    kind: ArgumentKind
    annotation: str | None = None
    default: str | None = None


@dataclass(frozen=True, slots=True)
class StaticOperation:
    """One operation observed in source, without claiming its runtime effect."""

    category: OperationCategory
    operation: str
    expression: str
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class CallableFacts:
    """Objective static facts collected for one declared callable.

    Structural counts recursively cover the callable body, excluding its
    docstring and the bodies of nested functions, lambdas, and classes. A nested
    declaration itself remains one statement in its parent. Branches count
    ``if``, conditional expressions, and ``match`` constructs; loops count
    explicit ``for``, ``async for``, and ``while`` statements. Try blocks,
    exception handlers, returns, and raises count their corresponding AST nodes.
    """

    module: str
    path: Path
    symbol_id: str
    name: str
    qualified_name: str
    display_name: str
    kind: CallableKind
    is_async: bool
    source_line: int
    positional_only_args: tuple[ParameterFacts, ...] = ()
    arguments: tuple[ParameterFacts, ...] = ()
    keyword_only_args: tuple[ParameterFacts, ...] = ()
    vararg: ParameterFacts | None = None
    varkw: ParameterFacts | None = None
    return_annotation: str | None = None
    decorators: tuple[str, ...] = ()
    has_docstring: bool = False
    docstring: str | None = None
    docstring_summary: str | None = None
    statement_count: int = 0
    branch_count: int = 0
    loop_count: int = 0
    try_block_count: int = 0
    except_handler_count: int = 0
    return_statement_count: int = 0
    raise_statement_count: int = 0
    resolved_callees: tuple[str, ...] = ()
    resolved_callers: tuple[str, ...] = ()
    ambiguous_call_count: int = 0
    unresolved_call_count: int = 0
    dynamic_call_count: int = 0
    has_explicit_return: bool = False
    returns_value: bool = False
    returns_none_explicitly: bool = False
    multiple_return_paths: bool = False
    raised_exceptions: tuple[str, ...] = ()
    caught_exceptions: tuple[str, ...] = ()
    io_operations: tuple[StaticOperation, ...] = ()
    process_operations: tuple[StaticOperation, ...] = ()
    environment_operations: tuple[StaticOperation, ...] = ()
    network_operations: tuple[StaticOperation, ...] = ()
    logging_operations: tuple[StaticOperation, ...] = ()


@dataclass(frozen=True, slots=True)
class ClassFacts:
    """Objective static facts collected for one class declaration."""

    module: str
    path: Path
    name: str
    qualified_name: str
    source_line: int
    has_docstring: bool = False
    docstring: str | None = None
    docstring_summary: str | None = None
    decorators: tuple[str, ...] = ()
    base_classes: tuple[str, ...] = ()
    methods: tuple[str, ...] = ()
    async_methods: tuple[str, ...] = ()
    class_variables: tuple[str, ...] = ()
    is_dataclass: bool = False
    method_count: int = 0


@dataclass(frozen=True, slots=True)
class ModuleFacts:
    """Objective static facts collected for one project-aware module."""

    module: str
    path: Path
    has_docstring: bool = False
    docstring: str | None = None
    docstring_summary: str | None = None
    imports: tuple[str, ...] = ()
    resolved_internal_dependencies: tuple[str, ...] = ()
    external_import_names: tuple[str, ...] = ()
    functions: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    module_level_callables: tuple[str, ...] = ()
    callable_facts: tuple[CallableFacts, ...] = ()
    class_facts: tuple[ClassFacts, ...] = ()
    module_level_executable_statement_count: int = 0
    module_level_calls: tuple[str, ...] = ()
    io_operations: tuple[StaticOperation, ...] = ()
    process_operations: tuple[StaticOperation, ...] = ()
    environment_operations: tuple[StaticOperation, ...] = ()
    network_operations: tuple[StaticOperation, ...] = ()
    logging_operations: tuple[StaticOperation, ...] = ()


@dataclass(frozen=True, slots=True)
class InsightEvidence:
    """One future human-readable claim linked to an objective static fact."""

    fact: str
    detail: str
    source_line: int | None = None


@dataclass(frozen=True, slots=True)
class ModuleInsight:
    """Future classified presentation for a module; not produced yet."""

    module: str
    path: Path
    purpose: str
    role: str
    responsibilities: tuple[str, ...]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    side_effects: tuple[str, ...]
    evidence: tuple[InsightEvidence, ...]
    confidence: InsightConfidence


@dataclass(frozen=True, slots=True)
class ClassInsight:
    """Future classified presentation for a class; not produced yet."""

    module: str
    path: Path
    qualified_name: str
    purpose: str
    role: str
    responsibilities: tuple[str, ...]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    side_effects: tuple[str, ...]
    evidence: tuple[InsightEvidence, ...]
    confidence: InsightConfidence


@dataclass(frozen=True, slots=True)
class CallableInsight:
    """Future classified presentation for a callable; not produced yet."""

    module: str
    path: Path
    qualified_name: str
    purpose: str
    role: str
    responsibilities: tuple[str, ...]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    side_effects: tuple[str, ...]
    evidence: tuple[InsightEvidence, ...]
    confidence: InsightConfidence
