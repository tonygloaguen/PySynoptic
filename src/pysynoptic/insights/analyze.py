"""Assembly of immutable Structured Insights from existing static layers."""

from __future__ import annotations

from collections.abc import Iterable

from pysynoptic.insights.classify import classify_evidence
from pysynoptic.insights.confidence import assess_confidence
from pysynoptic.insights.evidence import generate_evidence
from pysynoptic.insights.facts import extract_project_facts
from pysynoptic.insights.models import (
    CallableFacts,
    CallableInsight,
    ClassFacts,
    ClassInsight,
    InsightAnalysis,
    InsightEvidence,
    InsightInput,
    ModuleFacts,
    ModuleInsight,
    PurposeResult,
    RoleClassification,
    StaticOperation,
)
from pysynoptic.insights.purpose import generate_purpose
from pysynoptic.models import ProjectAnalysis

_MAX_RESPONSIBILITIES = 5


def _evidence_key(item: InsightEvidence) -> tuple[str, str, str, str, int, str]:
    return (
        item.category.value,
        item.code,
        item.description,
        item.reference or "",
        item.source_line if item.source_line is not None else -1,
        item.strength.value,
    )


def _ordered_evidence(
    evidence: Iterable[InsightEvidence],
) -> tuple[InsightEvidence, ...]:
    return tuple(sorted(set(evidence), key=_evidence_key))


def _pipeline(
    facts: ModuleFacts | ClassFacts | CallableFacts,
) -> tuple[
    tuple[InsightEvidence, ...],
    RoleClassification,
    PurposeResult,
]:
    evidence = generate_evidence(facts)
    classification = classify_evidence(evidence)
    purpose = generate_purpose(facts, classification, evidence)
    return evidence, classification, purpose


def _supporting_evidence(
    classification: RoleClassification,
    purpose: PurposeResult,
) -> tuple[InsightEvidence, ...]:
    return _ordered_evidence(
        (
            *classification.supporting_evidence,
            *(
                item
                for support in classification.secondary_support
                for item in support.evidence
            ),
            *purpose.supporting_evidence,
        )
    )


def _module_responsibilities(facts: ModuleFacts) -> tuple[str, ...]:
    values = []
    if facts.functions:
        count = len(facts.functions)
        values.append(f"Define {count} function{'s' if count != 1 else ''}")
    if facts.classes:
        count = len(facts.classes)
        values.append(f"Define {count} class{'es' if count != 1 else ''}")
    values.extend(
        f"Depend on {dependency}" for dependency in facts.resolved_internal_dependencies
    )
    return tuple(values[:_MAX_RESPONSIBILITIES])


def _class_responsibilities(facts: ClassFacts) -> tuple[str, ...]:
    values = []
    if facts.class_variables:
        count = len(facts.class_variables)
        values.append(f"Declare {count} field{'s' if count != 1 else ''}")
    if facts.method_count:
        values.append(
            f"Define {facts.method_count} method"
            f"{'s' if facts.method_count != 1 else ''}"
        )
    return tuple(values)


def _callable_responsibilities(facts: CallableFacts) -> tuple[str, ...]:
    return tuple(
        f"Call {(target.partition('::')[2] or target)}()"
        for target in facts.resolved_callees[:_MAX_RESPONSIBILITIES]
    )


def _inputs(facts: CallableFacts) -> tuple[InsightInput, ...]:
    parameters = (
        *facts.positional_only_args,
        *facts.arguments,
        *facts.keyword_only_args,
        *((facts.vararg,) if facts.vararg else ()),
        *((facts.varkw,) if facts.varkw else ()),
    )
    return tuple(
        InsightInput(
            name=item.name,
            kind=item.kind,
            annotation=item.annotation,
            default=item.default,
        )
        for item in parameters
    )


def _outputs(facts: CallableFacts) -> tuple[str, ...]:
    if facts.return_annotation:
        return (facts.return_annotation,)
    if facts.returns_none_explicitly:
        return ("None",)
    if facts.returns_value:
        return ("return value",)
    return ()


def _operation_side_effect(operation: StaticOperation) -> str:
    if operation.category == "io":
        if operation.operation == "open":
            return "Contains open() call"
        return f"Contains Path.{operation.operation}() call"
    if operation.operation == "os.environ":
        return "Contains access to os.environ"
    return f"Contains {operation.operation}() call"


def _side_effects(
    facts: ModuleFacts | CallableFacts,
) -> tuple[str, ...]:
    operations = (
        *facts.io_operations,
        *facts.process_operations,
        *facts.network_operations,
        *facts.environment_operations,
        *facts.logging_operations,
    )
    values = [_operation_side_effect(operation) for operation in operations]
    if isinstance(facts, CallableFacts):
        values.extend(
            f"Contains raise syntax for {exception}"
            for exception in facts.raised_exceptions
        )
        if facts.raise_statement_count and not facts.raised_exceptions:
            values.append("Contains raise statement syntax")
    return tuple(dict.fromkeys(values))


def analyze_module_insight(facts: ModuleFacts) -> ModuleInsight:
    """Assemble one module Insight from precomputed static Facts."""
    evidence, classification, purpose = _pipeline(facts)
    return ModuleInsight(
        identity=facts.module,
        display_name=facts.module.rpartition(".")[2],
        path=facts.path,
        role=classification.primary_role,
        secondary_roles=classification.secondary_roles,
        purpose=purpose.text,
        purpose_source=purpose.source,
        confidence=assess_confidence(classification, purpose, evidence),
        responsibilities=_module_responsibilities(facts),
        side_effects=_side_effects(facts),
        evidence=evidence,
        supporting_evidence=_supporting_evidence(classification, purpose),
    )


def analyze_class_insight(facts: ClassFacts) -> ClassInsight:
    """Assemble one class Insight from precomputed static Facts."""
    evidence, classification, purpose = _pipeline(facts)
    return ClassInsight(
        identity=f"{facts.module}::{facts.qualified_name}",
        display_name=facts.name,
        module=facts.module,
        path=facts.path,
        qualified_name=facts.qualified_name,
        role=classification.primary_role,
        secondary_roles=classification.secondary_roles,
        purpose=purpose.text,
        purpose_source=purpose.source,
        confidence=assess_confidence(classification, purpose, evidence),
        responsibilities=_class_responsibilities(facts),
        evidence=evidence,
        supporting_evidence=_supporting_evidence(classification, purpose),
        is_dataclass=facts.is_dataclass,
        field_count=len(facts.class_variables),
        method_count=facts.method_count,
    )


def analyze_callable_insight(facts: CallableFacts) -> CallableInsight:
    """Assemble one function or method Insight from precomputed static Facts."""
    evidence, classification, purpose = _pipeline(facts)
    return CallableInsight(
        identity=f"{facts.module}::{facts.qualified_name}",
        display_name=facts.display_name,
        module=facts.module,
        path=facts.path,
        symbol_id=facts.symbol_id,
        qualified_name=facts.qualified_name,
        kind=facts.kind,
        is_async=facts.is_async,
        source_line=facts.source_line,
        role=classification.primary_role,
        secondary_roles=classification.secondary_roles,
        purpose=purpose.text,
        purpose_source=purpose.source,
        confidence=assess_confidence(classification, purpose, evidence),
        responsibilities=_callable_responsibilities(facts),
        inputs=_inputs(facts),
        outputs=_outputs(facts),
        side_effects=_side_effects(facts),
        callers=facts.resolved_callers,
        callees=facts.resolved_callees,
        evidence=evidence,
        supporting_evidence=_supporting_evidence(classification, purpose),
    )


def build_insight_analysis(
    module_facts: Iterable[ModuleFacts],
) -> InsightAnalysis:
    """Assemble a complete result from already extracted module Facts."""
    ordered = tuple(
        sorted(
            module_facts,
            key=lambda item: (
                item.module.casefold(),
                item.module,
                item.path.as_posix(),
            ),
        )
    )
    return InsightAnalysis(
        modules=tuple(analyze_module_insight(item) for item in ordered),
        classes=tuple(
            analyze_class_insight(class_facts)
            for module in ordered
            for class_facts in module.class_facts
        ),
        callables=tuple(
            analyze_callable_insight(callable_facts)
            for module in ordered
            for callable_facts in module.callable_facts
        ),
    )


def analyze_insights(analysis: ProjectAnalysis) -> InsightAnalysis:
    """Extract Facts once, then build Insights for a project or standalone file."""
    return build_insight_analysis(extract_project_facts(analysis))
