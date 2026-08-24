"""Deterministic static facts used by future code-understanding insights."""

from pysynoptic.insights.analyze import (
    analyze_callable_insight,
    analyze_class_insight,
    analyze_insights,
    analyze_module_insight,
    build_insight_analysis,
)
from pysynoptic.insights.classify import classify_evidence
from pysynoptic.insights.confidence import assess_confidence
from pysynoptic.insights.evidence import (
    generate_callable_evidence,
    generate_class_evidence,
    generate_evidence,
    generate_module_evidence,
)
from pysynoptic.insights.facts import extract_module_facts, extract_project_facts
from pysynoptic.insights.models import (
    CallableFacts,
    CallableInsight,
    ClassFacts,
    ClassInsight,
    EvidenceCategory,
    EvidenceStrength,
    InsightAnalysis,
    InsightConfidence,
    InsightEvidence,
    InsightInput,
    InsightRole,
    ModuleFacts,
    ModuleInsight,
    ParameterFacts,
    PurposeResult,
    PurposeSource,
    RoleClassification,
    RoleSupport,
    StaticOperation,
)
from pysynoptic.insights.purpose import generate_purpose

__all__ = [
    "CallableFacts",
    "CallableInsight",
    "ClassFacts",
    "ClassInsight",
    "EvidenceCategory",
    "EvidenceStrength",
    "InsightConfidence",
    "InsightEvidence",
    "InsightInput",
    "InsightAnalysis",
    "InsightRole",
    "ModuleFacts",
    "ModuleInsight",
    "ParameterFacts",
    "PurposeResult",
    "PurposeSource",
    "RoleClassification",
    "RoleSupport",
    "StaticOperation",
    "analyze_callable_insight",
    "analyze_class_insight",
    "analyze_insights",
    "analyze_module_insight",
    "assess_confidence",
    "build_insight_analysis",
    "classify_evidence",
    "extract_module_facts",
    "extract_project_facts",
    "generate_callable_evidence",
    "generate_class_evidence",
    "generate_evidence",
    "generate_module_evidence",
    "generate_purpose",
]
