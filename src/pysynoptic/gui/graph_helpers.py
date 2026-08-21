"""Headless-safe selection and graph usability helpers."""

from __future__ import annotations

from pysynoptic.graph import CallGraphDirection
from pysynoptic.models import CallableIdentity, ProjectAnalysis

DEFAULT_CALL_DIRECTION: CallGraphDirection = "both"
DEFAULT_CALL_DEPTH = 1


def empty_outgoing_suggestion(
    incoming_count: int, direction: CallGraphDirection
) -> str | None:
    """Explain an empty outgoing view without implying there are no callers."""
    if direction != "outgoing":
        return None
    suffix = (
        f"\n\n{incoming_count} resolved incoming caller"
        f"{'s are' if incoming_count != 1 else ' is'} available."
        if incoming_count
        else ""
    )
    return f"No resolved outgoing calls.{suffix}"


def search_flow_callables(
    analysis: ProjectAnalysis, query: str
) -> tuple[CallableIdentity, ...]:
    """Return deterministic callable selector matches without requiring Tk."""
    normalized = query.strip().casefold()
    return tuple(
        item
        for item in sorted(
            analysis.callable_identities,
            key=lambda candidate: (
                candidate.qualified_name.casefold(),
                candidate.qualified_name,
                candidate.symbol.line,
            ),
        )
        if normalized in item.qualified_name.casefold()
    )


def default_flow_callable(analysis: ProjectAnalysis) -> CallableIdentity | None:
    """Choose main, otherwise the first top-level callable in source order."""
    if len(analysis.module_identities) != 1:
        return None
    top_level = tuple(
        sorted(
            (
                item
                for item in analysis.callable_identities
                if item.symbol.parent_symbol_id is None
            ),
            key=lambda item: (item.symbol.line, item.symbol.column),
        )
    )
    return next(
        (item for item in top_level if item.symbol.name == "main"),
        top_level[0] if top_level else None,
    )
