"""Conservative evidence-quality assessment for Structured Insights."""

from __future__ import annotations

from collections.abc import Iterable

from pysynoptic.insights.models import (
    EvidenceStrength,
    InsightConfidence,
    InsightEvidence,
    InsightRole,
    PurposeResult,
    RoleClassification,
)


def assess_confidence(
    classification: RoleClassification,
    purpose: PurposeResult,
    evidence: Iterable[InsightEvidence],
) -> InsightConfidence:
    """Assess proof quality without interpreting classifier scores."""
    if classification.primary_role is InsightRole.UNKNOWN or purpose.text is None:
        return InsightConfidence.UNKNOWN

    all_evidence = tuple(evidence)
    support = tuple(dict.fromkeys(classification.supporting_evidence))
    strong = tuple(item for item in support if item.strength is EvidenceStrength.STRONG)
    categories = {item.category for item in support}
    uncertain_calls = any(
        item.code in {"ambiguous_call_count", "dynamic_call_count"}
        for item in all_evidence
    )
    unresolved_without_proven_calls = any(
        item.code == "unresolved_call_count" for item in all_evidence
    ) and not any(item.code.startswith("calls:") for item in support)

    if uncertain_calls or unresolved_without_proven_calls:
        return InsightConfidence.MEDIUM if strong else InsightConfidence.UNKNOWN

    if classification.primary_role is InsightRole.MODEL:
        model_structure = {item.code.split(":", 1)[0] for item in support}
        if {
            "dataclass_decorator",
            "class_variable",
        } <= model_structure and len(strong) >= 2:
            return InsightConfidence.HIGH

    if len(support) >= 4 and len(strong) >= 2 and len(categories) >= 3:
        return InsightConfidence.HIGH
    if strong or support:
        return InsightConfidence.MEDIUM
    return InsightConfidence.UNKNOWN
