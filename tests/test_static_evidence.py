from pathlib import Path

from pysynoptic.insights import (
    CallableFacts,
    ClassFacts,
    EvidenceCategory,
    EvidenceStrength,
    ModuleFacts,
    ParameterFacts,
    StaticOperation,
    generate_callable_evidence,
    generate_class_evidence,
    generate_evidence,
    generate_module_evidence,
)


def callable_facts(**changes) -> CallableFacts:
    values = {
        "module": "sample",
        "path": Path("/source/does-not-need-to-exist.py"),
        "symbol_id": "sample.py::run@1:0",
        "name": "run",
        "qualified_name": "run",
        "display_name": "run()",
        "kind": "function",
        "is_async": False,
        "source_line": 1,
    }
    values.update(changes)
    return CallableFacts(**values)


def evidence_by_code(items, code: str):
    return next(item for item in items if item.code == code)


def test_tokenizes_snake_camel_pascal_and_leading_underscores() -> None:
    snake = generate_callable_evidence(
        callable_facts(
            name="_parse_pingcastle_xml", display_name="_parse_pingcastle_xml()"
        )
    )
    camel = generate_callable_evidence(
        callable_facts(name="renderMarkdown", display_name="renderMarkdown()")
    )
    pascal = generate_class_evidence(
        ClassFacts(
            module="sample",
            path=Path("sample.py"),
            name="HTTPServer",
            qualified_name="HTTPServer",
            source_line=1,
        )
    )

    assert {item.code for item in snake} == {
        "name_token:parse",
        "name_token:pingcastle",
        "name_token:xml",
    }
    assert {item.code for item in camel} == {
        "name_token:markdown",
        "name_token:render",
    }
    assert {item.code for item in pascal} == {
        "name_token:http",
        "name_token:server",
    }


def test_preserves_normalized_docstring_first_line_without_paraphrasing() -> None:
    evidence = generate_callable_evidence(
        callable_facts(
            has_docstring=True,
            docstring="Analyze the project and build dependencies.\n\nDetails.",
            docstring_summary="Analyze the project and build dependencies.",
        )
    )

    item = evidence_by_code(evidence, "docstring_summary")
    assert item.description == (
        'Docstring first line: "Analyze the project and build dependencies."'
    )
    assert item.reference == "Analyze the project and build dependencies."
    assert item.strength is EvidenceStrength.STRONG


def test_generates_objective_signature_evidence() -> None:
    evidence = generate_callable_evidence(
        callable_facts(
            is_async=True,
            positional_only_args=(ParameterFacts("path", "positional_only", "Path"),),
            arguments=(ParameterFacts("project", "positional", default="None"),),
            keyword_only_args=(ParameterFacts("strict", "keyword_only", "bool"),),
            vararg=ParameterFacts("items", "vararg"),
            varkw=ParameterFacts("options", "varkw"),
            return_annotation="ProjectAnalysis",
        )
    )
    descriptions = {item.description for item in evidence}

    assert 'Accepts positional-only parameter "path"' in descriptions
    assert 'Accepts parameter "project"' in descriptions
    assert 'Accepts keyword-only parameter "strict"' in descriptions
    assert 'Accepts variadic positional parameter "*items"' in descriptions
    assert 'Accepts variadic keyword parameter "**options"' in descriptions
    assert 'Return annotation is "ProjectAnalysis"' in descriptions
    assert "Declared as an async callable" in descriptions
    assert "Defines 1 keyword-only parameter" in descriptions


def test_uses_only_resolved_relationships_as_affirmative_targets() -> None:
    evidence = generate_callable_evidence(
        callable_facts(
            resolved_callees=("sample.parser::parse_xml",),
            resolved_callers=("sample.cli::main", "sample::<module>"),
            ambiguous_call_count=2,
            unresolved_call_count=3,
            dynamic_call_count=4,
        )
    )

    assert evidence_by_code(evidence, "calls:sample.parser::parse_xml").description == (
        "Calls parse_xml()"
    )
    assert evidence_by_code(evidence, "called_by:sample.cli::main").description == (
        "Called by main()"
    )
    assert evidence_by_code(evidence, "ambiguous_call_count").description == (
        "Contains 2 ambiguous calls"
    )
    assert evidence_by_code(evidence, "unresolved_call_count").description == (
        "Contains 3 unresolved calls"
    )
    assert evidence_by_code(evidence, "dynamic_call_count").description == (
        "Contains 4 dynamic calls"
    )
    affirmative_references = {
        item.reference
        for item in evidence
        if item.code.startswith(("calls:", "called_by:"))
    }
    assert affirmative_references == {
        "sample.parser::parse_xml",
        "sample.cli::main",
        "sample::<module>",
    }


def test_generates_control_flow_return_and_exception_evidence() -> None:
    evidence = generate_callable_evidence(
        callable_facts(
            branch_count=3,
            loop_count=4,
            try_block_count=2,
            except_handler_count=3,
            return_statement_count=2,
            has_explicit_return=True,
            returns_value=True,
            returns_none_explicitly=True,
            multiple_return_paths=True,
            raise_statement_count=1,
            raised_exceptions=("RuntimeError",),
            caught_exceptions=("TypeError", "ValueError"),
        )
    )
    descriptions = {item.description for item in evidence}

    assert "Contains 3 conditional branches" in descriptions
    assert "Contains 4 loops" in descriptions
    assert "Contains 2 try blocks" in descriptions
    assert "Contains 3 exception handlers" in descriptions
    assert "Contains 2 explicit return statements" in descriptions
    assert "Contains multiple explicit return statements" in descriptions
    assert 'Contains raise syntax for "RuntimeError"' in descriptions
    assert "Contains 1 raise statement" in descriptions
    assert 'Contains an exception handler for "ValueError"' in descriptions


def test_generates_operations_only_from_specialized_fact_operations() -> None:
    evidence = generate_callable_evidence(
        callable_facts(
            io_operations=(
                StaticOperation("io", "write_text", "path.write_text(text)", 10, 4),
            ),
            process_operations=(
                StaticOperation(
                    "process", "subprocess.run", "subprocess.run(cmd)", 11, 4
                ),
            ),
            environment_operations=(
                StaticOperation("environment", "os.environ", "os.environ", 12, 4),
            ),
            network_operations=(
                StaticOperation(
                    "network",
                    "socket.create_connection",
                    "socket.create_connection(addr)",
                    13,
                    4,
                ),
            ),
            logging_operations=(
                StaticOperation("logging", "logging.info", "logging.info(msg)", 14, 4),
            ),
        )
    )
    by_category = {
        item.category: item for item in evidence if item.code.startswith("operation:")
    }

    assert by_category[EvidenceCategory.FILESYSTEM].description == (
        "Calls Path.write_text()"
    )
    assert by_category[EvidenceCategory.PROCESS].description == (
        "Calls subprocess.run()"
    )
    assert by_category[EvidenceCategory.ENVIRONMENT].description == (
        "Accesses os.environ"
    )
    assert by_category[EvidenceCategory.NETWORK].description == (
        "Calls socket.create_connection()"
    )
    assert by_category[EvidenceCategory.LOGGING].description == ("Calls logging.info()")
    assert all(
        item.strength is EvidenceStrength.STRONG for item in by_category.values()
    )


def test_generates_class_structure_without_resolving_inheritance() -> None:
    evidence = generate_class_evidence(
        ClassFacts(
            module="sample",
            path=Path("sample.py"),
            name="ResultRecord",
            qualified_name="ResultRecord",
            source_line=4,
            decorators=("dataclass(frozen=True)",),
            base_classes=("Generic[T]",),
            methods=("ResultRecord.save", "ResultRecord.load"),
            async_methods=("ResultRecord.load",),
            class_variables=("kind",),
            is_dataclass=True,
            method_count=2,
        )
    )
    descriptions = {item.description for item in evidence}

    assert "Decorated with dataclass syntax" in descriptions
    assert 'Inherits syntactically from "Generic[T]"' in descriptions
    assert "Defines 2 methods" in descriptions
    assert 'Defines async method "ResultRecord.load"' in descriptions
    assert 'Defines class variable "kind"' in descriptions
    assert all("data model" not in value.casefold() for value in descriptions)


def test_generates_module_structure_import_and_dependency_evidence() -> None:
    evidence = generate_module_evidence(
        ModuleFacts(
            module="sample.analyzer.project",
            path=Path("project.py"),
            imports=("pathlib.Path", "sample.scanner"),
            resolved_internal_dependencies=("sample.scanner",),
            external_import_names=("pathlib.Path",),
            functions=("analyze", "scan"),
            classes=("Project",),
            module_level_executable_statement_count=3,
        )
    )
    descriptions = {item.description for item in evidence}

    assert 'Imports "pathlib.Path"' in descriptions
    assert 'Depends on internal module "sample.scanner"' in descriptions
    assert 'Contains external import "pathlib.Path"' in descriptions
    assert "Defines 2 functions" in descriptions
    assert "Defines 1 class" in descriptions
    assert "Contains 3 module-level executable statements" in descriptions


def test_minimal_callable_is_deterministic_and_invents_no_meaning() -> None:
    facts = callable_facts(name="x", display_name="x()")

    first = generate_evidence(facts)
    second = generate_evidence(facts)

    assert first == second
    assert tuple(item.code for item in first) == ("name_token:x",)
    assert first[0].description == 'Callable name contains token "x"'
    assert first[0].strength is EvidenceStrength.SUPPORTING


def test_generation_from_memory_does_not_require_the_source_path() -> None:
    missing = Path("/path/that/does/not/exist/source.py")
    facts = callable_facts(path=missing, name="readData", display_name="readData()")

    evidence = generate_evidence(facts)

    assert not missing.exists()
    assert {item.code for item in evidence} == {
        "name_token:data",
        "name_token:read",
    }
