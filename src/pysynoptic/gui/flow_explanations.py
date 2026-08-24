"""Lazy in-memory FlowExplanation cache shared by GUI panels."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pysynoptic.analyzer import analyze_callable_flow
from pysynoptic.insights import FlowExplanation, InsightAnalysis, explain_callable_flow
from pysynoptic.models import CallableFlowGraph, CallableIdentity, ProjectAnalysis

FlowBuilder = Callable[[CallableIdentity], CallableFlowGraph]
FlowExplainer = Callable[
    [CallableFlowGraph, InsightAnalysis | None],
    FlowExplanation,
]


@dataclass(frozen=True, slots=True)
class CachedFlowExplanation:
    """One CFG and its explanation, built together for one callable."""

    flow: CallableFlowGraph
    explanation: FlowExplanation


class FlowExplanationCache:
    """Build each callable CFG at most once for the current analysis generation."""

    def __init__(
        self,
        *,
        build_flow: FlowBuilder | None = None,
        explain_flow: FlowExplainer = explain_callable_flow,
    ) -> None:
        self._build_flow = build_flow or self._analyze_identity
        self._explain_flow = explain_flow
        self._analysis: ProjectAnalysis | None = None
        self._insights: InsightAnalysis | None = None
        self._identities: dict[str, CallableIdentity] = {}
        self._items: dict[str, CachedFlowExplanation] = {}
        self._generation = 0

    @staticmethod
    def _analyze_identity(identity: CallableIdentity) -> CallableFlowGraph:
        return analyze_callable_flow(identity.module.path, identity.symbol)

    @property
    def generation(self) -> int:
        """Return the current in-memory analysis generation."""
        return self._generation

    @property
    def size(self) -> int:
        """Return the number of cached callable explanations."""
        return len(self._items)

    def set_analysis(
        self,
        analysis: ProjectAnalysis | None,
        insights: InsightAnalysis | None,
    ) -> int:
        """Replace the generation and invalidate every previously cached result."""
        if analysis is self._analysis and insights is self._insights:
            return self._generation
        self._generation += 1
        self._analysis = analysis
        self._insights = insights
        self._identities = (
            {item.symbol.symbol_id: item for item in analysis.callable_identities}
            if analysis is not None
            else {}
        )
        self._items.clear()
        return self._generation

    def peek(self, symbol_id: str) -> CachedFlowExplanation | None:
        """Return a cached result without constructing a CFG."""
        return self._items.get(symbol_id)

    def get(self, symbol_id: str) -> CachedFlowExplanation | None:
        """Build once, rejecting a result if the analysis changed meanwhile."""
        cached = self._items.get(symbol_id)
        if cached is not None:
            return cached
        identity = self._identities.get(symbol_id)
        if identity is None:
            return None
        generation = self._generation
        analysis = self._analysis
        insights = self._insights
        flow = self._build_flow(identity)
        explanation = self._explain_flow(flow, insights)
        if generation != self._generation or analysis is not self._analysis:
            return None
        result = CachedFlowExplanation(flow, explanation)
        self._items[symbol_id] = result
        return result


__all__ = ["CachedFlowExplanation", "FlowExplanationCache"]
