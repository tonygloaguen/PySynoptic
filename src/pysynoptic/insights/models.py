"""Immutable models for deterministic static facts and future insights."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
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


class EvidenceCategory(StrEnum):
    """Stable descriptive categories for fact-backed evidence."""

    NAMING = "naming"
    DOCSTRING = "docstring"
    SIGNATURE = "signature"
    CALL_RELATIONSHIP = "call_relationship"
    FILESYSTEM = "filesystem"
    PROCESS = "process"
    NETWORK = "network"
    ENVIRONMENT = "environment"
    LOGGING = "logging"
    CONTROL_FLOW = "control_flow"
    RETURNS = "returns"
    EXCEPTIONS = "exceptions"
    IMPORTS = "imports"
    CLASS_STRUCTURE = "class_structure"
    MODULE_STRUCTURE = "module_structure"


class EvidenceStrength(StrEnum):
    """Strength of the direct link between an Evidence and its source Fact."""

    STRONG = "strong"
    SUPPORTING = "supporting"


class InsightRole(StrEnum):
    """Controlled initial vocabulary for conservative static roles."""

    ORCHESTRATOR = "orchestrator"
    ANALYZER = "analyzer"
    PARSER = "parser"
    RENDERER = "renderer"
    EXPORTER = "exporter"
    LOADER = "loader"
    READER = "reader"
    WRITER = "writer"
    VALIDATOR = "validator"
    TRANSFORMER = "transformer"
    RESOLVER = "resolver"
    SCANNER = "scanner"
    GRAPH_BUILDER = "graph_builder"
    CONTROLLER = "controller"
    ADAPTER = "adapter"
    MODEL = "model"
    FACTORY = "factory"
    UTILITY = "utility"
    UNKNOWN = "unknown"


class InsightConfidence(StrEnum):
    """Quality of the static support behind an Insight, never a probability."""

    HIGH = "high"
    MEDIUM = "medium"
    UNKNOWN = "unknown"


class PurposeSource(StrEnum):
    """Provenance of a generated short purpose."""

    DOCSTRING = "docstring"
    ROLE_TEMPLATE = "role_template"
    STRUCTURE = "structure"
    NONE = "none"


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
    """One short deterministic reformulation of an objective static fact."""

    category: EvidenceCategory
    code: str
    description: str
    strength: EvidenceStrength
    reference: str | None = None
    source_line: int | None = None


@dataclass(frozen=True, slots=True)
class RoleSupport:
    """Evidence retained to explain one accepted role."""

    role: InsightRole
    evidence: tuple[InsightEvidence, ...]


@dataclass(frozen=True, slots=True)
class RoleClassification:
    """Conservative role selection without purpose or Insight confidence."""

    primary_role: InsightRole
    secondary_roles: tuple[InsightRole, ...] = ()
    supporting_evidence: tuple[InsightEvidence, ...] = ()
    secondary_support: tuple[RoleSupport, ...] = ()


@dataclass(frozen=True, slots=True)
class PurposeResult:
    """One short deterministic purpose and the Evidence supporting it."""

    text: str | None
    source: PurposeSource = PurposeSource.NONE
    supporting_evidence: tuple[InsightEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class InsightInput:
    """One declared callable input, without inferred semantics."""

    name: str
    kind: ArgumentKind
    annotation: str | None = None
    default: str | None = None


@dataclass(frozen=True, slots=True)
class ModuleInsight:
    """Structured static understanding of one module."""

    identity: str
    display_name: str
    path: Path
    role: InsightRole
    secondary_roles: tuple[InsightRole, ...]
    purpose: str | None
    purpose_source: PurposeSource
    confidence: InsightConfidence
    responsibilities: tuple[str, ...] = ()
    inputs: tuple[InsightInput, ...] = ()
    outputs: tuple[str, ...] = ()
    side_effects: tuple[str, ...] = ()
    evidence: tuple[InsightEvidence, ...] = ()
    supporting_evidence: tuple[InsightEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class ClassInsight:
    """Structured static understanding of one class."""

    identity: str
    display_name: str
    module: str
    path: Path
    qualified_name: str
    role: InsightRole
    secondary_roles: tuple[InsightRole, ...]
    purpose: str | None
    purpose_source: PurposeSource
    confidence: InsightConfidence
    responsibilities: tuple[str, ...] = ()
    inputs: tuple[InsightInput, ...] = ()
    outputs: tuple[str, ...] = ()
    side_effects: tuple[str, ...] = ()
    evidence: tuple[InsightEvidence, ...] = ()
    supporting_evidence: tuple[InsightEvidence, ...] = ()
    is_dataclass: bool = False
    field_count: int = 0
    method_count: int = 0


@dataclass(frozen=True, slots=True)
class CallableInsight:
    """Structured static understanding of one function or method."""

    identity: str
    display_name: str
    module: str
    path: Path
    symbol_id: str
    qualified_name: str
    kind: CallableKind
    is_async: bool
    source_line: int
    role: InsightRole
    secondary_roles: tuple[InsightRole, ...]
    purpose: str | None
    purpose_source: PurposeSource
    confidence: InsightConfidence
    responsibilities: tuple[str, ...] = ()
    inputs: tuple[InsightInput, ...] = ()
    outputs: tuple[str, ...] = ()
    side_effects: tuple[str, ...] = ()
    callers: tuple[str, ...] = ()
    callees: tuple[str, ...] = ()
    evidence: tuple[InsightEvidence, ...] = ()
    supporting_evidence: tuple[InsightEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class InsightAnalysis:
    """Deterministically ordered Structured Insights for one analysis context."""

    modules: tuple[ModuleInsight, ...]
    classes: tuple[ClassInsight, ...]
    callables: tuple[CallableInsight, ...]
