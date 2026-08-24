from pathlib import Path

import pytest

from pysynoptic.analyzer.project import analyze_project, analyze_python_file_context
from pysynoptic.insights import (
    CallableFacts,
    ClassFacts,
    EvidenceCategory,
    EvidenceStrength,
    InsightConfidence,
    InsightEvidence,
    InsightRole,
    ModuleFacts,
    ParameterFacts,
    PurposeResult,
    PurposeSource,
    RoleClassification,
    StaticOperation,
    analyze_callable_insight,
    analyze_class_insight,
    analyze_insights,
    analyze_module_insight,
    assess_confidence,
    build_insight_analysis,
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


def evidence(
    category: EvidenceCategory,
    code: str,
    *,
    strength: EvidenceStrength = EvidenceStrength.STRONG,
    reference: str | None = None,
) -> InsightEvidence:
    return InsightEvidence(
        category=category,
        code=code,
        description=code,
        strength=strength,
        reference=reference,
    )


def test_builds_complete_callable_insight() -> None:
    facts = callable_facts(
        name="parse_xml",
        qualified_name="parse_xml",
        display_name="parse_xml()",
        arguments=(ParameterFacts("path", "positional", "Path"),),
        return_annotation="dict[str, object]",
        branch_count=1,
        loop_count=1,
        resolved_callees=("sample::get_text",),
        resolved_callers=("sample::main",),
        has_explicit_return=True,
        returns_value=True,
        return_statement_count=1,
    )

    insight = analyze_callable_insight(facts)

    assert insight.identity == "sample::parse_xml"
    assert insight.display_name == "parse_xml()"
    assert insight.role is InsightRole.PARSER
    assert insight.purpose == "Parse XML."
    assert insight.confidence is InsightConfidence.HIGH
    assert insight.inputs[0].name == "path"
    assert insight.outputs == ("dict[str, object]",)


def test_builds_module_insight_with_objective_responsibilities() -> None:
    facts = ModuleFacts(
        module="sample.project",
        path=Path("sample/project.py"),
        functions=("analyze", "render"),
        classes=("Result",),
        resolved_internal_dependencies=("sample.models",),
    )

    insight = analyze_module_insight(facts)

    assert insight.identity == "sample.project"
    assert insight.display_name == "project"
    assert insight.role is InsightRole.UNKNOWN
    assert insight.responsibilities == (
        "Define 2 functions",
        "Define 1 class",
        "Depend on sample.models",
    )


def test_builds_high_confidence_dataclass_model_insight() -> None:
    facts = ClassFacts(
        module="sample.models",
        path=Path("sample/models.py"),
        name="CallResolution",
        qualified_name="CallResolution",
        source_line=3,
        decorators=("dataclass(frozen=True, slots=True)",),
        class_variables=("status", "targets"),
        is_dataclass=True,
    )

    insight = analyze_class_insight(facts)

    assert insight.identity == "sample.models::CallResolution"
    assert insight.role is InsightRole.MODEL
    assert insight.purpose == "Represent call resolution data."
    assert insight.confidence is InsightConfidence.HIGH
    assert insight.is_dataclass
    assert insight.field_count == 2


def test_unknown_role_has_unknown_confidence() -> None:
    insight = analyze_callable_insight(callable_facts())

    assert insight.role is InsightRole.UNKNOWN
    assert insight.confidence is InsightConfidence.UNKNOWN


def test_high_confidence_requires_converging_strong_support() -> None:
    strong_items = (
        evidence(EvidenceCategory.NAMING, "name_token:parse"),
        evidence(EvidenceCategory.SIGNATURE, "return_annotation"),
        evidence(EvidenceCategory.CONTROL_FLOW, "loop_count"),
        evidence(EvidenceCategory.CALL_RELATIONSHIP, "calls:sample::read"),
    )

    result = assess_confidence(
        RoleClassification(InsightRole.PARSER, supporting_evidence=strong_items),
        PurposeResult("Parse input.", PurposeSource.ROLE_TEMPLATE, strong_items),
        strong_items,
    )

    assert result is InsightConfidence.HIGH


def test_supporting_only_role_is_medium_confidence() -> None:
    weak = (
        evidence(
            EvidenceCategory.NAMING,
            "name_token:parse",
            strength=EvidenceStrength.SUPPORTING,
        ),
        evidence(
            EvidenceCategory.SIGNATURE,
            "parameter:positional:data",
            strength=EvidenceStrength.SUPPORTING,
        ),
    )

    assert (
        assess_confidence(
            RoleClassification(InsightRole.PARSER, supporting_evidence=weak),
            PurposeResult("Parse input.", PurposeSource.ROLE_TEMPLATE, weak),
            weak,
        )
        is InsightConfidence.MEDIUM
    )


def test_missing_purpose_produces_unknown_confidence() -> None:
    strong = (evidence(EvidenceCategory.CONTROL_FLOW, "loop_count"),)

    assert (
        assess_confidence(
            RoleClassification(InsightRole.ANALYZER, supporting_evidence=strong),
            PurposeResult(None),
            strong,
        )
        is InsightConfidence.UNKNOWN
    )


def test_preserves_docstring_purpose_source() -> None:
    facts = callable_facts(
        has_docstring=True,
        docstring="Return a stable display label.",
        docstring_summary="Return a stable display label.",
    )

    insight = analyze_callable_insight(facts)

    assert insight.purpose == "Return a stable display label."
    assert insight.purpose_source is PurposeSource.DOCSTRING


def test_preserves_role_template_purpose_source() -> None:
    insight = analyze_callable_insight(
        callable_facts(
            name="render_markdown",
            qualified_name="render_markdown",
            display_name="render_markdown()",
            return_annotation="str",
            loop_count=1,
        )
    )

    assert insight.role is InsightRole.RENDERER
    assert insight.purpose_source is PurposeSource.ROLE_TEMPLATE


def test_callable_responsibilities_are_bounded_resolved_calls() -> None:
    facts = callable_facts(
        resolved_callees=tuple(f"sample::step_{index}" for index in range(7))
    )

    insight = analyze_callable_insight(facts)

    assert insight.responsibilities == tuple(
        f"Call step_{index}()" for index in range(5)
    )


def test_inputs_preserve_kind_annotation_and_default() -> None:
    facts = callable_facts(
        positional_only_args=(ParameterFacts("source", "positional_only", "Path"),),
        arguments=(ParameterFacts("limit", "positional", "int", "10"),),
        keyword_only_args=(ParameterFacts("strict", "keyword_only", "bool", "False"),),
        vararg=ParameterFacts("items", "vararg"),
        varkw=ParameterFacts("options", "varkw"),
    )

    inputs = analyze_callable_insight(facts).inputs
    assert [
        (item.name, item.kind, item.annotation, item.default) for item in inputs
    ] == [
        ("source", "positional_only", "Path", None),
        ("limit", "positional", "int", "10"),
        ("strict", "keyword_only", "bool", "False"),
        ("items", "vararg", None, None),
        ("options", "varkw", None, None),
    ]


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"return_annotation": "ProjectAnalysis"}, ("ProjectAnalysis",)),
        ({"returns_none_explicitly": True}, ("None",)),
        ({"returns_value": True}, ("return value",)),
        ({}, ()),
    ],
)
def test_outputs_remain_objective(changes, expected) -> None:
    assert analyze_callable_insight(callable_facts(**changes)).outputs == expected


def test_side_effects_use_prudent_static_wording() -> None:
    facts = callable_facts(
        io_operations=(
            StaticOperation("io", "write_text", "path.write_text(x)", 1, 0),
        ),
        process_operations=(
            StaticOperation("process", "subprocess.run", "subprocess.run(x)", 2, 0),
        ),
        network_operations=(
            StaticOperation("network", "requests.get", "requests.get(url)", 3, 0),
        ),
        environment_operations=(
            StaticOperation("environment", "os.getenv", "os.getenv(name)", 4, 0),
        ),
        logging_operations=(
            StaticOperation("logging", "logging.info", "logging.info(x)", 5, 0),
        ),
        raise_statement_count=1,
        raised_exceptions=("ValueError",),
    )

    assert analyze_callable_insight(facts).side_effects == (
        "Contains Path.write_text() call",
        "Contains subprocess.run() call",
        "Contains requests.get() call",
        "Contains os.getenv() call",
        "Contains logging.info() call",
        "Contains raise syntax for ValueError",
    )


def test_preserves_callers_and_callees() -> None:
    facts = callable_facts(
        resolved_callers=("sample::main",),
        resolved_callees=("sample::parse", "sample::render"),
    )

    insight = analyze_callable_insight(facts)

    assert insight.callers == facts.resolved_callers
    assert insight.callees == facts.resolved_callees


def test_preserves_all_and_supporting_evidence() -> None:
    insight = analyze_callable_insight(
        callable_facts(
            name="scan_project",
            qualified_name="scan_project",
            display_name="scan_project()",
            arguments=(ParameterFacts("path", "positional", "Path"),),
            return_annotation="ProjectScan",
            resolved_callees=("sample::_scan_directory",),
            branch_count=1,
        )
    )

    assert insight.evidence
    assert insight.supporting_evidence
    assert set(insight.supporting_evidence) <= set(insight.evidence)


def test_structured_insight_equality_is_deterministic() -> None:
    facts = callable_facts(
        name="analyze_project",
        qualified_name="analyze_project",
        display_name="analyze_project()",
        return_annotation="ProjectAnalysis",
        loop_count=1,
        resolved_callees=("sample::scan", "sample::resolve"),
    )

    assert analyze_callable_insight(facts) == analyze_callable_insight(facts)


def test_confidence_ignores_initial_evidence_order() -> None:
    items = (
        evidence(EvidenceCategory.NAMING, "name_token:resolve"),
        evidence(EvidenceCategory.CONTROL_FLOW, "branch_count"),
        evidence(EvidenceCategory.SIGNATURE, "return_annotation"),
        evidence(EvidenceCategory.CALL_RELATIONSHIP, "calls:sample::target"),
    )
    classification = RoleClassification(
        InsightRole.RESOLVER,
        supporting_evidence=items,
    )
    purpose = PurposeResult("Resolve calls.", PurposeSource.ROLE_TEMPLATE, items)

    assert assess_confidence(classification, purpose, items) == assess_confidence(
        classification, purpose, reversed(items)
    )


def test_supports_standalone_file_analysis(tmp_path: Path) -> None:
    source = tmp_path / "standalone.py"
    source.write_text(
        "def parse_json(text: str) -> dict:\n    return {'value': text}\n",
        encoding="utf-8",
    )

    result = analyze_insights(analyze_python_file_context(source))

    assert len(result.modules) == 1
    assert result.modules[0].identity == "standalone"
    assert result.callables[0].identity == "standalone::parse_json"


def test_supports_project_analysis(tmp_path: Path) -> None:
    (tmp_path / "source.py").write_text(
        "from target import render\n\ndef run():\n    render()\n",
        encoding="utf-8",
    )
    (tmp_path / "target.py").write_text(
        "def render():\n    return 'ok'\n",
        encoding="utf-8",
    )

    result = analyze_insights(analyze_project(tmp_path))

    assert tuple(item.identity for item in result.modules) == ("source", "target")
    assert {item.identity for item in result.callables} == {
        "source::run",
        "target::render",
    }


def test_preserves_async_callable_kind() -> None:
    insight = analyze_callable_insight(
        callable_facts(
            name="load_data",
            qualified_name="Loader.load_data",
            display_name="load_data()",
            kind="method",
            is_async=True,
        )
    )

    assert insight.kind == "method"
    assert insight.is_async


def test_complete_pipeline_never_executes_source(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    source = tmp_path / "malicious.py"
    source.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed')\n"
        "def run():\n    return 1\n",
        encoding="utf-8",
    )

    result = analyze_insights(analyze_project(tmp_path))

    assert result.callables
    assert not marker.exists()


def test_confidence_and_assembly_do_not_read_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = ModuleFacts(
        module="sample",
        path=Path("/source/does-not-exist.py"),
        callable_facts=(callable_facts(),),
    )

    def fail_read(*args, **kwargs):
        raise AssertionError("Structured Insight assembly must not read source")

    monkeypatch.setattr(Path, "read_text", fail_read)

    assert build_insight_analysis((facts,)).callables


def test_minimal_callable_remains_structurally_useful() -> None:
    insight = analyze_callable_insight(
        callable_facts(arguments=(ParameterFacts("value", "positional"),))
    )

    assert insight.role is InsightRole.UNKNOWN
    assert insight.purpose is None
    assert insight.confidence is InsightConfidence.UNKNOWN
    assert insight.inputs[0].name == "value"


def test_structural_unknown_class_records_method_count() -> None:
    facts = ClassFacts(
        module="sample",
        path=Path("sample.py"),
        name="Worker",
        qualified_name="Worker",
        source_line=1,
        methods=("run", "stop"),
        method_count=2,
    )

    insight = analyze_class_insight(facts)

    assert insight.role is InsightRole.UNKNOWN
    assert insight.purpose == "Defines 2 methods."
    assert insight.purpose_source is PurposeSource.STRUCTURE
    assert insight.method_count == 2


def test_ambiguous_calls_prevent_high_confidence() -> None:
    support = (
        evidence(EvidenceCategory.NAMING, "name_token:resolve"),
        evidence(EvidenceCategory.CONTROL_FLOW, "branch_count"),
        evidence(EvidenceCategory.SIGNATURE, "return_annotation"),
        evidence(EvidenceCategory.CALL_RELATIONSHIP, "calls:sample::target"),
    )
    ambiguous = evidence(EvidenceCategory.CALL_RELATIONSHIP, "ambiguous_call_count")

    assert (
        assess_confidence(
            RoleClassification(InsightRole.RESOLVER, supporting_evidence=support),
            PurposeResult("Resolve calls.", PurposeSource.ROLE_TEMPLATE, support),
            (*support, ambiguous),
        )
        is InsightConfidence.MEDIUM
    )
