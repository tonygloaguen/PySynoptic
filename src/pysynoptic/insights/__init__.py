"""Deterministic static facts used by future code-understanding insights."""

from pysynoptic.insights.classify import classify_evidence
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
    InsightConfidence,
    InsightEvidence,
    InsightRole,
    ModuleFacts,
    ModuleInsight,
    ParameterFacts,
    RoleClassification,
    RoleSupport,
    StaticOperation,
)

__all__ = [
    "CallableFacts",
    "CallableInsight",
    "ClassFacts",
    "ClassInsight",
    "EvidenceCategory",
    "EvidenceStrength",
    "InsightConfidence",
    "InsightEvidence",
    "InsightRole",
    "ModuleFacts",
    "ModuleInsight",
    "ParameterFacts",
    "RoleClassification",
    "RoleSupport",
    "StaticOperation",
    "classify_evidence",
    "extract_module_facts",
    "extract_project_facts",
    "generate_callable_evidence",
    "generate_class_evidence",
    "generate_evidence",
    "generate_module_evidence",
]
