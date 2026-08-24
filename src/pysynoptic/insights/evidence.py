"""Deterministic reformulation of static Facts as structured Evidence."""

from __future__ import annotations

import re

from pysynoptic.insights.models import (
    CallableFacts,
    ClassFacts,
    EvidenceCategory,
    EvidenceStrength,
    InsightEvidence,
    ModuleFacts,
    ParameterFacts,
    StaticOperation,
)

_MAX_DOCSTRING_SUMMARY = 160
_CATEGORY_ORDER = {
    category: index
    for index, category in enumerate(
        (
            EvidenceCategory.NAMING,
            EvidenceCategory.DOCSTRING,
            EvidenceCategory.SIGNATURE,
            EvidenceCategory.CALL_RELATIONSHIP,
            EvidenceCategory.FILESYSTEM,
            EvidenceCategory.PROCESS,
            EvidenceCategory.NETWORK,
            EvidenceCategory.ENVIRONMENT,
            EvidenceCategory.LOGGING,
            EvidenceCategory.CONTROL_FLOW,
            EvidenceCategory.RETURNS,
            EvidenceCategory.EXCEPTIONS,
            EvidenceCategory.IMPORTS,
            EvidenceCategory.CLASS_STRUCTURE,
            EvidenceCategory.MODULE_STRUCTURE,
        )
    )
}
_STRENGTH_ORDER = {
    EvidenceStrength.STRONG: 0,
    EvidenceStrength.SUPPORTING: 1,
}


def _stable_fragment(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.:-]+", "_", value.strip())
    return normalized.strip("_") or "unknown"


def _name_tokens(name: str) -> tuple[str, ...]:
    value = name.lstrip("_")
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    tokens = (token.casefold() for token in re.split(r"[^A-Za-z0-9]+", value))
    return tuple(dict.fromkeys(token for token in tokens if token))


def _evidence(
    category: EvidenceCategory,
    code: str,
    description: str,
    strength: EvidenceStrength,
    *,
    reference: str | None = None,
    source_line: int | None = None,
) -> InsightEvidence:
    return InsightEvidence(
        category=category,
        code=code,
        description=description,
        strength=strength,
        reference=reference,
        source_line=source_line,
    )


def _ordered(items: list[InsightEvidence]) -> tuple[InsightEvidence, ...]:
    unique = set(items)
    return tuple(
        sorted(
            unique,
            key=lambda item: (
                _CATEGORY_ORDER[item.category],
                item.code,
                item.description,
                item.reference or "",
                item.source_line if item.source_line is not None else -1,
                _STRENGTH_ORDER[item.strength],
            ),
        )
    )


def _naming_evidence(
    name: str,
    subject: str,
    source_line: int | None = None,
) -> list[InsightEvidence]:
    return [
        _evidence(
            EvidenceCategory.NAMING,
            f"name_token:{_stable_fragment(token)}",
            f'{subject} name contains token "{token}"',
            EvidenceStrength.SUPPORTING,
            reference=name,
            source_line=source_line,
        )
        for token in _name_tokens(name)
    ]


def _docstring_evidence(
    summary: str | None,
    source_line: int | None,
) -> list[InsightEvidence]:
    if not summary:
        return []
    normalized = " ".join(summary.split())
    if len(normalized) > _MAX_DOCSTRING_SUMMARY:
        normalized = f"{normalized[: _MAX_DOCSTRING_SUMMARY - 1].rstrip()}…"
    return [
        _evidence(
            EvidenceCategory.DOCSTRING,
            "docstring_summary",
            f'Docstring first line: "{normalized}"',
            EvidenceStrength.STRONG,
            reference=summary,
            source_line=source_line,
        )
    ]


def _parameter_evidence(parameter: ParameterFacts) -> list[InsightEvidence]:
    fragment = _stable_fragment(parameter.name)
    if parameter.kind == "positional_only":
        description = f'Accepts positional-only parameter "{parameter.name}"'
    elif parameter.kind == "keyword_only":
        description = f'Accepts keyword-only parameter "{parameter.name}"'
    elif parameter.kind == "vararg":
        description = f'Accepts variadic positional parameter "*{parameter.name}"'
    elif parameter.kind == "varkw":
        description = f'Accepts variadic keyword parameter "**{parameter.name}"'
    else:
        description = f'Accepts parameter "{parameter.name}"'
    items = [
        _evidence(
            EvidenceCategory.SIGNATURE,
            f"parameter:{parameter.kind}:{fragment}",
            description,
            EvidenceStrength.SUPPORTING,
            reference=parameter.name,
        )
    ]
    if parameter.annotation:
        items.append(
            _evidence(
                EvidenceCategory.SIGNATURE,
                f"parameter_annotation:{fragment}",
                f'Parameter "{parameter.name}" annotation is "{parameter.annotation}"',
                EvidenceStrength.STRONG,
                reference=parameter.annotation,
            )
        )
    if parameter.default is not None:
        items.append(
            _evidence(
                EvidenceCategory.SIGNATURE,
                f"parameter_default:{fragment}",
                f'Parameter "{parameter.name}" default syntax is "{parameter.default}"',
                EvidenceStrength.STRONG,
                reference=parameter.default,
            )
        )
    return items


def _callable_label(identity: str) -> str:
    _, separator, qualified_name = identity.partition("::")
    if not separator:
        qualified_name = identity
    if qualified_name == "<module>":
        return "<module>"
    return qualified_name.rpartition(".")[2]


def _operation_evidence(operation: StaticOperation) -> InsightEvidence:
    category = {
        "io": EvidenceCategory.FILESYSTEM,
        "process": EvidenceCategory.PROCESS,
        "network": EvidenceCategory.NETWORK,
        "environment": EvidenceCategory.ENVIRONMENT,
        "logging": EvidenceCategory.LOGGING,
    }[operation.category]
    if operation.category == "io":
        description = (
            "Calls builtin open()"
            if operation.operation == "open"
            else f"Calls Path.{operation.operation}()"
        )
    elif operation.operation == "os.environ":
        description = "Accesses os.environ"
    else:
        description = f"Calls {operation.operation}()"
    code = f"operation:{operation.operation}:{operation.line}:{operation.column}"
    return _evidence(
        category,
        code,
        description,
        EvidenceStrength.STRONG,
        reference=operation.expression,
        source_line=operation.line,
    )


def _operations_evidence(
    *operation_groups: tuple[StaticOperation, ...],
) -> list[InsightEvidence]:
    return [
        _operation_evidence(operation)
        for group in operation_groups
        for operation in group
    ]


def generate_callable_evidence(facts: CallableFacts) -> tuple[InsightEvidence, ...]:
    """Generate descriptive Evidence from callable Facts only."""
    items = _naming_evidence(facts.name, "Callable", facts.source_line)
    items.extend(_docstring_evidence(facts.docstring_summary, facts.source_line))

    parameters = (
        *facts.positional_only_args,
        *facts.arguments,
        *facts.keyword_only_args,
        *((facts.vararg,) if facts.vararg else ()),
        *((facts.varkw,) if facts.varkw else ()),
    )
    for parameter in parameters:
        items.extend(_parameter_evidence(parameter))
    if facts.is_async:
        items.append(
            _evidence(
                EvidenceCategory.SIGNATURE,
                "async_callable",
                "Declared as an async callable",
                EvidenceStrength.STRONG,
                source_line=facts.source_line,
            )
        )
    if facts.keyword_only_args:
        count = len(facts.keyword_only_args)
        items.append(
            _evidence(
                EvidenceCategory.SIGNATURE,
                "keyword_only_parameter_count",
                f"Defines {count} keyword-only parameter{'s' if count != 1 else ''}",
                EvidenceStrength.STRONG,
                source_line=facts.source_line,
            )
        )
    if facts.return_annotation:
        items.append(
            _evidence(
                EvidenceCategory.SIGNATURE,
                "return_annotation",
                f'Return annotation is "{facts.return_annotation}"',
                EvidenceStrength.STRONG,
                reference=facts.return_annotation,
                source_line=facts.source_line,
            )
        )

    for target in facts.resolved_callees:
        label = _callable_label(target)
        items.append(
            _evidence(
                EvidenceCategory.CALL_RELATIONSHIP,
                f"calls:{_stable_fragment(target)}",
                f"Calls {label}()",
                EvidenceStrength.STRONG,
                reference=target,
                source_line=facts.source_line,
            )
        )
    for caller in facts.resolved_callers:
        label = _callable_label(caller)
        description = (
            f"Called by module-level code in {caller.partition('::')[0]}"
            if label == "<module>"
            else f"Called by {label}()"
        )
        items.append(
            _evidence(
                EvidenceCategory.CALL_RELATIONSHIP,
                f"called_by:{_stable_fragment(caller)}",
                description,
                EvidenceStrength.STRONG,
                reference=caller,
                source_line=facts.source_line,
            )
        )
    for status, count in (
        ("ambiguous", facts.ambiguous_call_count),
        ("dynamic", facts.dynamic_call_count),
        ("unresolved", facts.unresolved_call_count),
    ):
        if count:
            items.append(
                _evidence(
                    EvidenceCategory.CALL_RELATIONSHIP,
                    f"{status}_call_count",
                    f"Contains {count} {status} call{'s' if count != 1 else ''}",
                    EvidenceStrength.STRONG,
                    source_line=facts.source_line,
                )
            )

    for code, count, singular, plural in (
        (
            "branch_count",
            facts.branch_count,
            "conditional branch",
            "conditional branches",
        ),
        ("loop_count", facts.loop_count, "loop", "loops"),
        ("try_block_count", facts.try_block_count, "try block", "try blocks"),
        (
            "except_handler_count",
            facts.except_handler_count,
            "exception handler",
            "exception handlers",
        ),
    ):
        if count:
            label = singular if count == 1 else plural
            items.append(
                _evidence(
                    EvidenceCategory.CONTROL_FLOW,
                    code,
                    f"Contains {count} {label}",
                    EvidenceStrength.STRONG,
                    source_line=facts.source_line,
                )
            )

    if facts.has_explicit_return:
        items.append(
            _evidence(
                EvidenceCategory.RETURNS,
                "explicit_return_count",
                f"Contains {facts.return_statement_count} explicit return "
                f"statement{'s' if facts.return_statement_count != 1 else ''}",
                EvidenceStrength.STRONG,
                source_line=facts.source_line,
            )
        )
    if facts.returns_value:
        items.append(
            _evidence(
                EvidenceCategory.RETURNS,
                "returns_value_syntax",
                "Contains a return statement with a value",
                EvidenceStrength.STRONG,
                source_line=facts.source_line,
            )
        )
    if facts.returns_none_explicitly:
        items.append(
            _evidence(
                EvidenceCategory.RETURNS,
                "returns_none_explicitly",
                "Contains an explicit return None statement",
                EvidenceStrength.STRONG,
                source_line=facts.source_line,
            )
        )
    if facts.multiple_return_paths:
        items.append(
            _evidence(
                EvidenceCategory.RETURNS,
                "multiple_explicit_returns",
                "Contains multiple explicit return statements",
                EvidenceStrength.STRONG,
                source_line=facts.source_line,
            )
        )

    for exception in facts.raised_exceptions:
        items.append(
            _evidence(
                EvidenceCategory.EXCEPTIONS,
                f"raises:{_stable_fragment(exception)}",
                f'Contains raise syntax for "{exception}"',
                EvidenceStrength.STRONG,
                reference=exception,
                source_line=facts.source_line,
            )
        )
    if facts.raise_statement_count:
        count = facts.raise_statement_count
        items.append(
            _evidence(
                EvidenceCategory.EXCEPTIONS,
                "raise_statement_count",
                f"Contains {count} raise statement{'s' if count != 1 else ''}",
                EvidenceStrength.STRONG,
                source_line=facts.source_line,
            )
        )
    for exception in facts.caught_exceptions:
        items.append(
            _evidence(
                EvidenceCategory.EXCEPTIONS,
                f"catches:{_stable_fragment(exception)}",
                f'Contains an exception handler for "{exception}"',
                EvidenceStrength.STRONG,
                reference=exception,
                source_line=facts.source_line,
            )
        )
    items.extend(
        _operations_evidence(
            facts.io_operations,
            facts.process_operations,
            facts.network_operations,
            facts.environment_operations,
            facts.logging_operations,
        )
    )
    return _ordered(items)


def generate_class_evidence(facts: ClassFacts) -> tuple[InsightEvidence, ...]:
    """Generate descriptive Evidence from class Facts only."""
    items = _naming_evidence(facts.name, "Class", facts.source_line)
    items.extend(_docstring_evidence(facts.docstring_summary, facts.source_line))
    if facts.is_dataclass:
        items.append(
            _evidence(
                EvidenceCategory.CLASS_STRUCTURE,
                "dataclass_decorator",
                "Decorated with dataclass syntax",
                EvidenceStrength.STRONG,
                source_line=facts.source_line,
            )
        )
    for decorator in facts.decorators:
        items.append(
            _evidence(
                EvidenceCategory.CLASS_STRUCTURE,
                f"decorator:{_stable_fragment(decorator)}",
                f'Decorator syntax is "{decorator}"',
                EvidenceStrength.STRONG,
                reference=decorator,
                source_line=facts.source_line,
            )
        )
    for base in facts.base_classes:
        items.append(
            _evidence(
                EvidenceCategory.CLASS_STRUCTURE,
                f"base:{_stable_fragment(base)}",
                f'Inherits syntactically from "{base}"',
                EvidenceStrength.STRONG,
                reference=base,
                source_line=facts.source_line,
            )
        )
    if facts.method_count:
        items.append(
            _evidence(
                EvidenceCategory.CLASS_STRUCTURE,
                "method_count",
                f"Defines {facts.method_count} "
                f"method{'s' if facts.method_count != 1 else ''}",
                EvidenceStrength.STRONG,
                source_line=facts.source_line,
            )
        )
    for method in facts.async_methods:
        items.append(
            _evidence(
                EvidenceCategory.CLASS_STRUCTURE,
                f"async_method:{_stable_fragment(method)}",
                f'Defines async method "{method}"',
                EvidenceStrength.STRONG,
                reference=method,
                source_line=facts.source_line,
            )
        )
    for variable in facts.class_variables:
        items.append(
            _evidence(
                EvidenceCategory.CLASS_STRUCTURE,
                f"class_variable:{_stable_fragment(variable)}",
                f'Defines class variable "{variable}"',
                EvidenceStrength.STRONG,
                reference=variable,
                source_line=facts.source_line,
            )
        )
    return _ordered(items)


def generate_module_evidence(facts: ModuleFacts) -> tuple[InsightEvidence, ...]:
    """Generate descriptive Evidence from module Facts only."""
    module_name = facts.module.rpartition(".")[2]
    items = _naming_evidence(module_name, "Module")
    items.extend(_docstring_evidence(facts.docstring_summary, None))
    for imported in facts.imports:
        items.append(
            _evidence(
                EvidenceCategory.IMPORTS,
                f"import:{_stable_fragment(imported)}",
                f'Imports "{imported}"',
                EvidenceStrength.STRONG,
                reference=imported,
            )
        )
    for dependency in facts.resolved_internal_dependencies:
        items.append(
            _evidence(
                EvidenceCategory.IMPORTS,
                f"internal_dependency:{_stable_fragment(dependency)}",
                f'Depends on internal module "{dependency}"',
                EvidenceStrength.STRONG,
                reference=dependency,
            )
        )
    for imported in facts.external_import_names:
        items.append(
            _evidence(
                EvidenceCategory.IMPORTS,
                f"external_import:{_stable_fragment(imported)}",
                f'Contains external import "{imported}"',
                EvidenceStrength.STRONG,
                reference=imported,
            )
        )
    for code, count, singular, plural in (
        ("function_count", len(facts.functions), "function", "functions"),
        ("class_count", len(facts.classes), "class", "classes"),
        (
            "module_executable_statement_count",
            facts.module_level_executable_statement_count,
            "module-level executable statement",
            "module-level executable statements",
        ),
    ):
        if count:
            label = singular if count == 1 else plural
            items.append(
                _evidence(
                    EvidenceCategory.MODULE_STRUCTURE,
                    code,
                    f"Defines {count} {label}"
                    if code != "module_executable_statement_count"
                    else f"Contains {count} {label}",
                    EvidenceStrength.STRONG,
                )
            )
    items.extend(
        _operations_evidence(
            facts.io_operations,
            facts.process_operations,
            facts.network_operations,
            facts.environment_operations,
            facts.logging_operations,
        )
    )
    return _ordered(items)


def generate_evidence(
    facts: ModuleFacts | ClassFacts | CallableFacts,
) -> tuple[InsightEvidence, ...]:
    """Dispatch Evidence generation by immutable Facts model type."""
    if isinstance(facts, ModuleFacts):
        return generate_module_evidence(facts)
    if isinstance(facts, ClassFacts):
        return generate_class_evidence(facts)
    return generate_callable_evidence(facts)
