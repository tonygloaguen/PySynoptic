"""Static intra-function control-flow models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

FlowNodeKind: TypeAlias = Literal[
    "break",
    "call",
    "continue",
    "entry",
    "except",
    "exit",
    "finally",
    "if",
    "loop",
    "raise",
    "return",
    "statement",
    "try",
]
FlowEdgeKind: TypeAlias = Literal[
    "break",
    "continue",
    "except",
    "exit-loop",
    "false",
    "finally",
    "loop",
    "next",
    "return",
    "true",
]


@dataclass(frozen=True, slots=True)
class FlowNode:
    """One concise semantic step in a callable's static control flow."""

    node_id: str
    label: str
    kind: FlowNodeKind
    line: int
    column: int
    detail: str


@dataclass(frozen=True, slots=True)
class FlowEdge:
    """One labeled possible transition between flow nodes."""

    source_id: str
    target_id: str
    kind: FlowEdgeKind
    label: str


@dataclass(frozen=True, slots=True)
class CallableFlowGraph:
    """A conservative, renderer-independent CFG for one declared callable."""

    symbol_id: str
    path: Path
    name: str
    qualified_name: str
    line: int
    nodes: tuple[FlowNode, ...]
    edges: tuple[FlowEdge, ...]


FunctionFlow = CallableFlowGraph
