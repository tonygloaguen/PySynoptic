from pathlib import Path

import pytest

from pysynoptic.insights import (
    CallableFacts,
    ClassFacts,
    EvidenceCategory,
    EvidenceStrength,
    InsightEvidence,
    InsightRole,
    ModuleFacts,
    PurposeResult,
    RoleClassification,
    generate_callable_evidence,
    generate_class_evidence,
    generate_module_evidence,
    generate_purpose,
)


def callable_facts(**changes) -> CallableFacts:
    values = {
        "module": "sample",
        "path": Path("/source/does-not-exist.py"),
        "symbol_id": "sample.py::x@1:0",
        "name": "x",
        "qualified_name": "x",
        "display_name": "x()",
        "kind": "function",
        "is_async": False,
        "source_line": 1,
    }
    values.update(changes)
    return CallableFacts(**values)


def class_facts(**changes) -> ClassFacts:
    values = {
        "module": "sample",
        "path": Path("/source/does-not-exist.py"),
        "name": "Data",
        "qualified_name": "Data",
        "source_line": 1,
    }
    values.update(changes)
    return ClassFacts(**values)


def classified(
    role: InsightRole,
    evidence=(),
    *,
    secondary_roles: tuple[InsightRole, ...] = (),
) -> RoleClassification:
    return RoleClassification(
        primary_role=role,
        secondary_roles=secondary_roles,
        supporting_evidence=tuple(evidence),
    )


def purpose_for(facts, role: InsightRole, *, secondary_roles=()) -> PurposeResult:
    if isinstance(facts, CallableFacts):
        evidence = generate_callable_evidence(facts)
    elif isinstance(facts, ClassFacts):
        evidence = generate_class_evidence(facts)
    else:
        evidence = generate_module_evidence(facts)
    return generate_purpose(
        facts,
        classified(role, evidence, secondary_roles=secondary_roles),
        evidence,
    )


def test_prefers_explicit_docstring_without_paraphrasing() -> None:
    facts = callable_facts(
        name="analyze_project",
        qualified_name="analyze_project",
        has_docstring=True,
        docstring="Analyze a Python project and resolve dependencies.",
        docstring_summary="Analyze a Python project and resolve dependencies.",
    )

    result = purpose_for(facts, InsightRole.ANALYZER)

    assert result.text == "Analyze a Python project and resolve dependencies."
    assert tuple(item.code for item in result.supporting_evidence) == (
        "docstring_summary",
    )


def test_normalizes_multiline_docstring_spacing_and_punctuation() -> None:
    facts = callable_facts(
        has_docstring=True,
        docstring="Load structured data\nfrom a project",
        docstring_summary="Load   structured data\nfrom a project",
    )

    assert purpose_for(facts, InsightRole.UNKNOWN).text == (
        "Load structured data from a project."
    )


def test_parser_uses_snake_case_subject() -> None:
    facts = callable_facts(
        name="parse_pingcastle_xml",
        qualified_name="parse_pingcastle_xml",
    )

    assert purpose_for(facts, InsightRole.PARSER).text == "Parse pingcastle XML."


def test_analyzer_adds_article_for_single_project_subject() -> None:
    facts = callable_facts(name="analyze_project", qualified_name="analyze_project")

    assert purpose_for(facts, InsightRole.ANALYZER).text == "Analyze a project."


def test_renderer_identifies_a_known_output_format() -> None:
    facts = callable_facts(name="render_markdown", qualified_name="render_markdown")

    assert purpose_for(facts, InsightRole.RENDERER).text == "Render Markdown output."


def test_resolver_uses_enclosing_class_when_method_name_has_no_subject() -> None:
    facts = callable_facts(
        name="resolve",
        qualified_name="_CallResolver.resolve",
        kind="method",
    )

    assert purpose_for(facts, InsightRole.RESOLVER).text == "Resolve calls."


def test_scanner_uses_project_subject() -> None:
    facts = callable_facts(name="scan_project", qualified_name="scan_project")

    assert purpose_for(facts, InsightRole.SCANNER).text == "Scan a project."


def test_model_uses_pascal_case_class_subject() -> None:
    facts = class_facts(name="CallResolution", qualified_name="CallResolution")

    assert purpose_for(facts, InsightRole.MODEL).text == (
        "Represent call resolution data."
    )


def test_orchestrator_with_resolved_calls_uses_safe_program_workflow() -> None:
    facts = callable_facts(
        name="main",
        qualified_name="main",
        resolved_callees=("sample::parse", "sample::render", "sample::write"),
    )

    assert purpose_for(facts, InsightRole.ORCHESTRATOR).text == (
        "Coordinate the program workflow."
    )


def test_unknown_minimal_callable_has_no_invented_purpose() -> None:
    assert purpose_for(callable_facts(), InsightRole.UNKNOWN) == PurposeResult(None)


def test_unknown_callable_can_use_a_clear_docstring() -> None:
    facts = callable_facts(
        has_docstring=True,
        docstring="Return the normalized display label.",
        docstring_summary="Return the normalized display label.",
    )

    assert purpose_for(facts, InsightRole.UNKNOWN).text == (
        "Return the normalized display label."
    )


def test_generic_role_name_uses_a_safe_role_fallback() -> None:
    facts = callable_facts(name="analyze", qualified_name="analyze")

    assert purpose_for(facts, InsightRole.ANALYZER).text == "Analyze code."


def test_orphaned_subject_preposition_is_removed() -> None:
    facts = callable_facts(
        name="_resolution_for_reference",
        qualified_name="_resolution_for_reference",
    )

    assert purpose_for(facts, InsightRole.RESOLVER).text == "Resolve references."


def test_isolated_past_participle_is_not_used_as_analyzer_subject() -> None:
    facts = callable_facts(
        name="_completed_analysis",
        qualified_name="_completed_analysis",
    )

    assert purpose_for(facts, InsightRole.ANALYZER).text == "Analyze code."


def test_common_renderer_subject_is_not_artificially_capitalized() -> None:
    facts = callable_facts(name="_format_items", qualified_name="_format_items")

    assert purpose_for(facts, InsightRole.RENDERER).text == "Render items."


def test_camel_case_name_is_split_conservatively() -> None:
    facts = callable_facts(name="renderMarkdown", qualified_name="renderMarkdown")

    assert purpose_for(facts, InsightRole.RENDERER).text == "Render Markdown output."


def test_pascal_case_callable_name_is_split_conservatively() -> None:
    facts = callable_facts(name="ParseProjectXML", qualified_name="ParseProjectXML")

    assert purpose_for(facts, InsightRole.PARSER).text == "Parse project XML."


def test_leading_underscore_is_removed_from_subject() -> None:
    facts = callable_facts(name="_scan_project", qualified_name="_scan_project")

    assert purpose_for(facts, InsightRole.SCANNER).text == "Scan a project."


def test_evidence_order_does_not_change_purpose() -> None:
    facts = callable_facts(name="render_markdown", qualified_name="render_markdown")
    evidence = generate_callable_evidence(facts)
    classification = classified(InsightRole.RENDERER, evidence)

    first = generate_purpose(facts, classification, evidence)
    reversed_input = generate_purpose(facts, classification, reversed(evidence))

    assert first == reversed_input


def test_repeated_generation_is_exactly_deterministic() -> None:
    facts = callable_facts(name="analyze_project", qualified_name="analyze_project")
    evidence = generate_callable_evidence(facts)
    classification = classified(InsightRole.ANALYZER, evidence)

    assert generate_purpose(facts, classification, evidence) == generate_purpose(
        facts, classification, evidence
    )


def test_secondary_role_does_not_replace_primary_template() -> None:
    facts = callable_facts(name="render_markdown", qualified_name="render_markdown")

    result = purpose_for(
        facts,
        InsightRole.RENDERER,
        secondary_roles=(InsightRole.EXPORTER,),
    )

    assert result.text == "Render Markdown output."


def test_unknown_module_can_use_a_structural_description() -> None:
    facts = ModuleFacts(
        module="sample",
        path=Path("/source/does-not-exist.py"),
        functions=("a", "b", "c", "d"),
        classes=("One", "Two"),
    )

    result = purpose_for(facts, InsightRole.UNKNOWN)

    assert result.text == "Defines 4 functions and 2 classes."
    assert {item.code for item in result.supporting_evidence} == {
        "class_count",
        "function_count",
    }


def test_unknown_class_can_use_a_structural_description() -> None:
    facts = class_facts(method_count=5, methods=("a", "b", "c", "d", "e"))

    assert purpose_for(facts, InsightRole.UNKNOWN).text == "Defines 5 methods."


def test_unhelpful_single_word_docstring_does_not_create_purpose() -> None:
    facts = callable_facts(
        has_docstring=True,
        docstring="Helper.",
        docstring_summary="Helper.",
    )

    assert purpose_for(facts, InsightRole.UNKNOWN).text is None


def test_placeholder_docstring_sentence_does_not_create_purpose() -> None:
    facts = callable_facts(
        has_docstring=True,
        docstring="TODO add useful documentation.",
        docstring_summary="TODO add useful documentation.",
    )

    assert purpose_for(facts, InsightRole.UNKNOWN).text is None


def test_long_docstring_is_truncated_without_completion() -> None:
    summary = "Explain " + "structured static evidence " * 10
    facts = callable_facts(
        has_docstring=True,
        docstring=summary,
        docstring_summary=summary,
    )

    result = purpose_for(facts, InsightRole.UNKNOWN)

    assert result.text is not None
    assert len(result.text) == 160
    assert result.text.endswith("…")


def test_generation_uses_only_in_memory_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = callable_facts(name="scan_project", qualified_name="scan_project")
    evidence = generate_callable_evidence(facts)

    def fail_read(*args, **kwargs):
        raise AssertionError("Purpose generation must not read source files")

    monkeypatch.setattr(Path, "read_text", fail_read)

    assert (
        generate_purpose(
            facts,
            classified(InsightRole.SCANNER, evidence),
            evidence,
        ).text
        == "Scan a project."
    )


def test_support_contains_only_existing_evidence() -> None:
    facts = callable_facts(name="analyze_project", qualified_name="analyze_project")
    evidence = generate_callable_evidence(facts)
    result = generate_purpose(
        facts,
        classified(InsightRole.ANALYZER, evidence),
        evidence,
    )

    assert set(result.supporting_evidence) <= set(evidence)
    assert all(isinstance(item, InsightEvidence) for item in result.supporting_evidence)
    assert all(
        item.strength in {EvidenceStrength.STRONG, EvidenceStrength.SUPPORTING}
        for item in result.supporting_evidence
    )
    assert all(item.category is not EvidenceCategory.DOCSTRING for item in evidence)
