"""Public orchestration for deterministic flow explanations."""

from __future__ import annotations

from pysynoptic.insights.flow_explanation.models import FlowExplanation, InsightSource
from pysynoptic.insights.flow_explanation.structure import _FlowExplanationBuilder
from pysynoptic.models import CallableFlowGraph


def explain_callable_flow(
    flow: CallableFlowGraph,
    insights: InsightSource = None,
) -> FlowExplanation:
    """Explain an existing CFG without reading, importing, or executing source."""
    return _FlowExplanationBuilder(flow, insights).build()


analyze_flow_explanation = explain_callable_flow


__all__ = ["analyze_flow_explanation", "explain_callable_flow"]
