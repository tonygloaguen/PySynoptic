"""Immutable models for optional AI rewriting of static explanations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from pysynoptic.insights.flow_explanation.models import (
    FlowExplanationReliability,
    FlowOutcomeKind,
    FlowStepKind,
)


class AIProviderKind(StrEnum):
    """Explicitly configured AI provider families."""

    DISABLED = "disabled"
    OPENAI_COMPATIBLE = "openai-compatible"
    OLLAMA_COMPATIBLE = "ollama-compatible"


@dataclass(frozen=True, slots=True)
class AIProviderConfig:
    """Session-only provider configuration with a redacted API key."""

    kind: AIProviderKind = AIProviderKind.DISABLED
    endpoint: str = ""
    model: str = ""
    api_key: str = field(default="", repr=False, compare=False)
    timeout_seconds: float = 30.0

    @property
    def enabled(self) -> bool:
        """Return whether explicit AI rewriting is configured."""
        return self.kind is not AIProviderKind.DISABLED


@dataclass(frozen=True, slots=True)
class AIExplanationStep:
    """One deterministically ordered static flow step."""

    position: tuple[int, ...]
    kind: FlowStepKind
    text: str


@dataclass(frozen=True, slots=True)
class AIExplanationDecision:
    """One decision and the two statically distinguished paths."""

    condition: str
    true_path: tuple[str, ...]
    false_path: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AIExplanationLoop:
    """One statically visible loop."""

    header: str
    body_summary: str | None
    body_steps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AIExplanationException:
    """One static try/handler/finally description."""

    protected_summary: str | None
    handlers: tuple[str, ...]
    finally_summary: str | None


@dataclass(frozen=True, slots=True)
class AIExplanationOutcome:
    """One statically visible return or raise outcome."""

    kind: FlowOutcomeKind
    text: str


@dataclass(frozen=True, slots=True)
class AIResolvedCallee:
    """One resolved callee and its optional statically inferred purpose."""

    identity: str
    purpose: str | None


@dataclass(frozen=True, slots=True)
class AIExplanationOmissions:
    """Deterministic counts describing facts omitted to fit provider limits."""

    steps: int = 0
    decisions: int = 0
    loops: int = 0
    exceptions: int = 0
    outcomes: int = 0
    resolved_callees: int = 0
    truncated_fields: tuple[str, ...] = ()

    @property
    def any(self) -> bool:
        """Return whether normalization changed any provider-visible fact."""
        return bool(
            self.steps
            or self.decisions
            or self.loops
            or self.exceptions
            or self.outcomes
            or self.resolved_callees
            or self.truncated_fields
        )


@dataclass(frozen=True, slots=True)
class AIExplanationRequest:
    """Structured facts allowed to cross the optional provider boundary."""

    callable_name: str
    callable_identity: str
    role: str
    purpose: str | None
    static_summary: str
    steps: tuple[AIExplanationStep, ...]
    decisions: tuple[AIExplanationDecision, ...]
    loops: tuple[AIExplanationLoop, ...]
    exceptions: tuple[AIExplanationException, ...]
    outcomes: tuple[AIExplanationOutcome, ...]
    resolved_callees: tuple[AIResolvedCallee, ...]
    reliability: FlowExplanationReliability
    omissions: AIExplanationOmissions = AIExplanationOmissions()


@dataclass(frozen=True, slots=True)
class AIExplanationResult:
    """Validated provider prose kept separate from the static explanation."""

    text: str
    provider: str
    model: str
    source: Literal["AI"] = "AI"
    warnings: tuple[str, ...] = ()


__all__ = [
    "AIExplanationDecision",
    "AIExplanationException",
    "AIExplanationLoop",
    "AIExplanationOmissions",
    "AIExplanationOutcome",
    "AIExplanationRequest",
    "AIExplanationResult",
    "AIExplanationStep",
    "AIProviderConfig",
    "AIProviderKind",
    "AIResolvedCallee",
]
