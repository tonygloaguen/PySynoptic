"""Immutable public models for deterministic flow explanations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, TypeAlias

from pysynoptic.insights.models import CallableInsight, InsightAnalysis

FlowStepKind: TypeAlias = Literal[
    "break",
    "call",
    "continue",
    "decision",
    "exception",
    "loop",
    "raise",
    "return",
    "sequence",
    "statement",
]
FlowOutcomeKind: TypeAlias = Literal["raise", "return"]


class FlowExplanationReliability(StrEnum):
    """Qualitative reliability of one deterministic flow explanation."""

    HIGH = "high"
    MEDIUM = "medium"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FlowStep:
    """One compact, source-traceable step in a flow explanation."""

    order: int
    kind: FlowStepKind
    text: str
    source_node_ids: tuple[str, ...]
    child_steps: tuple[FlowStep, ...] = ()


@dataclass(frozen=True, slots=True)
class FlowDecision:
    """One CFG decision with its true and false paths kept distinct."""

    condition: str
    true_path: tuple[FlowStep, ...]
    false_path: tuple[FlowStep, ...]
    source_node_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FlowLoop:
    """One loop and the compact explanation of its nested body."""

    header: str
    body_summary: str | None
    body_steps: tuple[FlowStep, ...]
    source_node_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FlowException:
    """One try region, its handlers, and an optional finalization path."""

    protected_summary: str | None
    handlers: tuple[str, ...]
    finally_summary: str | None
    source_node_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FlowOutcome:
    """One statically visible return or raise outcome."""

    kind: FlowOutcomeKind
    text: str
    source_node_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FlowExplanation:
    """Deterministic explanation of one existing CallableFlowGraph."""

    callable_identity: str
    summary: str | None
    steps: tuple[FlowStep, ...]
    decisions: tuple[FlowDecision, ...]
    loops: tuple[FlowLoop, ...]
    exceptions: tuple[FlowException, ...]
    outcomes: tuple[FlowOutcome, ...]
    reliability: FlowExplanationReliability
    supporting_node_ids: tuple[str, ...]


InsightSource: TypeAlias = (
    InsightAnalysis | Iterable[CallableInsight] | Mapping[str, CallableInsight] | None
)


__all__ = [
    "FlowDecision",
    "FlowException",
    "FlowExplanation",
    "FlowExplanationReliability",
    "FlowLoop",
    "FlowOutcome",
    "FlowStep",
]
