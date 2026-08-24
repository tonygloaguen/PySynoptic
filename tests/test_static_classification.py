from pysynoptic.insights import (
    EvidenceCategory,
    EvidenceStrength,
    InsightEvidence,
    InsightRole,
    classify_evidence,
)


def evidence(
    category: EvidenceCategory,
    code: str,
    description: str | None = None,
    *,
    reference: str | None = None,
    strength: EvidenceStrength = EvidenceStrength.STRONG,
) -> InsightEvidence:
    return InsightEvidence(
        category=category,
        code=code,
        description=description or code,
        strength=strength,
        reference=reference,
    )


def token(value: str) -> InsightEvidence:
    return evidence(
        EvidenceCategory.NAMING,
        f"name_token:{value}",
        f'Callable name contains token "{value}"',
        reference=value,
        strength=EvidenceStrength.SUPPORTING,
    )


def parameter(name: str) -> InsightEvidence:
    return evidence(
        EvidenceCategory.SIGNATURE,
        f"parameter:positional:{name}",
        f'Accepts parameter "{name}"',
        reference=name,
    )


def parameter_annotation(name: str, annotation: str) -> InsightEvidence:
    return evidence(
        EvidenceCategory.SIGNATURE,
        f"parameter_annotation:{name}",
        reference=annotation,
    )


def return_annotation(annotation: str) -> InsightEvidence:
    return evidence(
        EvidenceCategory.SIGNATURE,
        "return_annotation",
        reference=annotation,
    )


def call(target: str) -> InsightEvidence:
    return evidence(
        EvidenceCategory.CALL_RELATIONSHIP,
        f"calls:{target}",
        reference=target,
    )


def control(code: str) -> InsightEvidence:
    return evidence(EvidenceCategory.CONTROL_FLOW, code)


def test_empty_and_minimal_evidence_remain_unknown() -> None:
    assert classify_evidence(()).primary_role is InsightRole.UNKNOWN
    assert classify_evidence((token("x"),)).primary_role is InsightRole.UNKNOWN


def test_role_like_name_alone_is_insufficient() -> None:
    classification = classify_evidence(
        (
            token("parse"),
            evidence(EvidenceCategory.RETURNS, "returns_value_syntax"),
        )
    )

    assert classification.primary_role is InsightRole.UNKNOWN
    assert classification.supporting_evidence == ()


def test_classifies_parser_from_converging_evidence() -> None:
    items = (
        token("parse"),
        token("xml"),
        parameter("path"),
        return_annotation("dict[str, object]"),
        control("loop_count"),
    )

    classification = classify_evidence(items)

    assert classification.primary_role is InsightRole.PARSER
    assert set(classification.supporting_evidence) == set(items)


def test_classifies_renderer_from_name_format_text_return_and_flow() -> None:
    classification = classify_evidence(
        (
            token("render"),
            token("markdown"),
            return_annotation("str"),
            control("loop_count"),
        )
    )

    assert classification.primary_role is InsightRole.RENDERER


def test_classifies_exporter_only_with_proven_write_and_context() -> None:
    write = evidence(
        EvidenceCategory.FILESYSTEM,
        "operation:write_text:10:4",
        reference="path.write_text(text)",
    )

    assert classify_evidence((token("export"), write)).primary_role is (
        InsightRole.EXPORTER
    )
    assert classify_evidence((write,)).primary_role is InsightRole.UNKNOWN


def test_classifies_orchestrator_from_multiple_resolved_calls_and_context() -> None:
    items = (
        token("main"),
        *(call(f"sample::step_{index}") for index in range(5)),
    )

    classification = classify_evidence(items)

    assert classification.primary_role is InsightRole.ORCHESTRATOR
    assert len(classification.supporting_evidence) == 6


def test_many_local_helper_calls_do_not_force_orchestrator() -> None:
    classification = classify_evidence(
        tuple(call(f"sample.helpers::step_{index}") for index in range(6))
    )

    assert classification.primary_role is InsightRole.UNKNOWN


def test_distributed_calls_can_prove_orchestration_without_a_name_hint() -> None:
    classification = classify_evidence(
        (
            call("sample.reader::read"),
            call("sample.parser::parse"),
            call("sample.model::normalize"),
            call("sample.renderer::render"),
            call("sample.writer::write"),
        )
    )

    assert classification.primary_role is InsightRole.ORCHESTRATOR


def test_generic_build_name_does_not_imply_factory() -> None:
    classification = classify_evidence(
        (
            token("build"),
            return_annotation("ProjectTree"),
            control("branch_count"),
            call("sample::make_node"),
            call("sample::append_child"),
        )
    )

    assert classification.primary_role is InsightRole.UNKNOWN


def test_classifies_analyzer_resolver_validator_and_scanner() -> None:
    analyzer = classify_evidence(
        (
            token("analyze"),
            control("loop_count"),
            return_annotation("ProjectAnalysis"),
            call("sample::scan"),
            call("sample::resolve"),
        )
    )
    resolver = classify_evidence(
        (
            token("resolve"),
            control("branch_count"),
            return_annotation("CallResolution"),
        )
    )
    validator = classify_evidence(
        (
            token("validate"),
            control("branch_count"),
            evidence(EvidenceCategory.EXCEPTIONS, "raise_statement_count"),
            return_annotation("bool"),
        )
    )
    scanner = classify_evidence(
        (
            token("scan"),
            parameter("path"),
            return_annotation("ProjectScan"),
            call("sample::_scan_directory"),
            control("branch_count"),
        )
    )

    assert analyzer.primary_role is InsightRole.ANALYZER
    assert resolver.primary_role is InsightRole.RESOLVER
    assert validator.primary_role is InsightRole.VALIDATOR
    assert scanner.primary_role is InsightRole.SCANNER


def test_classifies_graph_builder_from_build_graph_return_and_node_calls() -> None:
    classification = classify_evidence(
        (
            token("build"),
            return_annotation("DependencyGraph"),
            call("sample::_add_node"),
        )
    )

    assert classification.primary_role is InsightRole.GRAPH_BUILDER


def test_model_requires_structure_and_rejects_dataclass_with_heavy_behavior() -> None:
    dataclass = evidence(EvidenceCategory.CLASS_STRUCTURE, "dataclass_decorator")
    variable = evidence(
        EvidenceCategory.CLASS_STRUCTURE,
        "class_variable:value",
    )
    simple_methods = evidence(
        EvidenceCategory.CLASS_STRUCTURE,
        "method_count",
        "Defines 2 methods",
    )
    many_methods = evidence(
        EvidenceCategory.CLASS_STRUCTURE,
        "method_count",
        "Defines 6 methods",
    )

    assert (
        classify_evidence((dataclass, variable, simple_methods)).primary_role
        is InsightRole.MODEL
    )
    assert (
        classify_evidence((dataclass, variable, many_methods)).primary_role
        is InsightRole.UNKNOWN
    )


def test_keeps_only_compatible_secondary_roles() -> None:
    write = evidence(
        EvidenceCategory.FILESYSTEM,
        "operation:write_text:10:4",
    )
    structured_input = parameter_annotation("items", "list[Item]")
    classification = classify_evidence(
        (
            token("render"),
            token("markdown"),
            token("export"),
            return_annotation("str"),
            control("loop_count"),
            write,
            structured_input,
        )
    )

    assert classification.primary_role is InsightRole.RENDERER
    assert classification.secondary_roles == (InsightRole.EXPORTER,)
    assert classification.secondary_support[0].role is InsightRole.EXPORTER


def test_conflicting_roles_do_not_become_unrelated_secondaries() -> None:
    classification = classify_evidence(
        (
            token("parse"),
            token("xml"),
            token("render"),
            token("markdown"),
            parameter("path"),
            return_annotation("dict[str, str]"),
            control("loop_count"),
            control("branch_count"),
        )
    )

    assert classification.primary_role in {InsightRole.PARSER, InsightRole.RENDERER}
    assert classification.secondary_roles == ()


def test_input_order_and_repeated_classification_are_exactly_deterministic() -> None:
    items = (
        token("resolve"),
        control("branch_count"),
        return_annotation("CallResolution"),
        parameter("reference"),
    )

    first = classify_evidence(items)
    reversed_input = classify_evidence(reversed(items))
    repeated = classify_evidence(items)

    assert first == reversed_input == repeated
    assert first.primary_role is InsightRole.RESOLVER


def test_writer_is_not_inferred_from_a_punctual_write_in_an_orchestrator() -> None:
    write = evidence(
        EvidenceCategory.FILESYSTEM,
        "operation:write_text:10:4",
    )
    classification = classify_evidence(
        (
            token("main"),
            *(call(f"sample::step_{index}") for index in range(5)),
            write,
        )
    )

    assert classification.primary_role is InsightRole.ORCHESTRATOR
    assert InsightRole.WRITER not in classification.secondary_roles
