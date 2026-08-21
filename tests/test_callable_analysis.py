from pathlib import Path

import pytest

from pysynoptic import analyze_python_file


def analyze_source(tmp_path: Path, source: str):
    path = tmp_path / "module.py"
    path.write_text(source, encoding="utf-8")
    return analyze_python_file(path)


def test_collects_top_level_function(tmp_path: Path) -> None:
    analysis = analyze_source(tmp_path, "def run():\n    pass\n")

    symbol = analysis.callable_symbols[0]
    assert symbol.name == "run"
    assert symbol.qualified_name == "run"
    assert symbol.kind == "function"
    assert symbol.is_async is False
    assert symbol.parent_symbol_id is None


def test_collects_top_level_async_function(tmp_path: Path) -> None:
    analysis = analyze_source(tmp_path, "async def run():\n    pass\n")

    assert analysis.callable_symbols[0].is_async is True


def test_collects_class_method(tmp_path: Path) -> None:
    analysis = analyze_source(
        tmp_path, "class Service:\n    def run(self):\n        pass\n"
    )

    symbol = analysis.callable_symbols[0]
    assert symbol.qualified_name == "Service.run"
    assert symbol.kind == "method"


def test_collects_async_method(tmp_path: Path) -> None:
    analysis = analyze_source(
        tmp_path,
        "class Service:\n    async def run(self):\n        pass\n",
    )

    symbol = analysis.callable_symbols[0]
    assert symbol.kind == "method"
    assert symbol.is_async is True


def test_collects_nested_function_with_parent_identity(tmp_path: Path) -> None:
    analysis = analyze_source(
        tmp_path,
        "def outer():\n    def inner():\n        pass\n",
    )

    outer, inner = analysis.callable_symbols
    assert inner.qualified_name == "outer.<locals>.inner"
    assert inner.kind == "function"
    assert inner.parent_symbol_id == outer.symbol_id


def test_collects_method_of_class_nested_in_function(tmp_path: Path) -> None:
    analysis = analyze_source(
        tmp_path,
        "def outer():\n"
        "    class Nested:\n"
        "        def method(self):\n"
        "            pass\n",
    )

    outer, method = analysis.callable_symbols
    assert method.qualified_name == "outer.<locals>.Nested.method"
    assert method.kind == "method"
    assert method.parent_symbol_id == outer.symbol_id


def test_distinguishes_duplicate_logical_names_by_location(tmp_path: Path) -> None:
    analysis = analyze_source(
        tmp_path,
        "if condition:\n"
        "    def run():\n"
        "        pass\n"
        "else:\n"
        "    def run():\n"
        "        pass\n",
    )

    first, second = analysis.callable_symbols
    assert first.qualified_name == second.qualified_name == "run"
    assert first.symbol_id != second.symbol_id
    assert (first.line, second.line) == (2, 5)


def test_symbol_identity_is_stable(tmp_path: Path) -> None:
    source = "def run():\n    pass\n"

    first = analyze_source(tmp_path, source)
    second = analyze_python_file(tmp_path / "module.py")

    assert first.callable_symbols == second.callable_symbols
    assert first.callable_symbols[0].symbol_id.endswith("::run@1:0")


def test_collects_module_level_call(tmp_path: Path) -> None:
    analysis = analyze_source(tmp_path, "bootstrap()\n")

    call = analysis.call_references[0]
    assert call.scope_kind == "module"
    assert call.scope_name == "<module>"
    assert call.caller_symbol_id is None


def test_collects_simple_name_call(tmp_path: Path) -> None:
    analysis = analyze_source(tmp_path, "run()\n")

    call = analysis.call_references[0]
    assert call.target == "run"
    assert call.expression == "run"
    assert call.kind == "name"


def test_collects_attribute_call(tmp_path: Path) -> None:
    analysis = analyze_source(tmp_path, "service.run()\n")

    call = analysis.call_references[0]
    assert call.target == "service.run"
    assert call.kind == "attribute"


def test_collects_multi_level_attribute_call(tmp_path: Path) -> None:
    analysis = analyze_source(tmp_path, "package.service.run()\n")

    assert analysis.call_references[0].target == "package.service.run"


def test_collects_self_and_cls_method_calls(tmp_path: Path) -> None:
    analysis = analyze_source(
        tmp_path,
        "class Service:\n"
        "    def run(self):\n"
        "        self.start()\n"
        "        cls.finish()\n",
    )

    assert tuple(call.target for call in analysis.call_references) == (
        "self.start",
        "cls.finish",
    )


def test_attributes_nested_function_call_to_inner_symbol(tmp_path: Path) -> None:
    analysis = analyze_source(
        tmp_path,
        "def outer():\n    def inner():\n        execute()\n",
    )

    inner = analysis.callable_symbols[1]
    call = analysis.call_references[0]
    assert call.scope_name == "outer.<locals>.inner"
    assert call.caller_symbol_id == inner.symbol_id


@pytest.mark.parametrize(
    "statement",
    [
        "if condition:\n        execute()",
        "try:\n        execute()\n    except Exception:\n        recover()",
        "with manager():\n        execute()",
        "for item in items:\n        execute()",
        "while condition:\n        execute()",
    ],
    ids=["if", "try", "with", "for", "while"],
)
def test_attributes_calls_in_control_flow_to_function(
    tmp_path: Path,
    statement: str,
) -> None:
    source = "def run():\n    " + statement + "\n"
    analysis = analyze_source(tmp_path, source)
    run = analysis.callable_symbols[0]

    assert analysis.call_references
    assert all(
        call.caller_symbol_id == run.symbol_id for call in analysis.call_references
    )


def test_attributes_decorator_calls_to_outer_scope(tmp_path: Path) -> None:
    analysis = analyze_source(
        tmp_path,
        "@decorate(factory())\ndef run():\n    pass\n",
    )

    assert tuple(call.target for call in analysis.call_references) == (
        "decorate",
        "factory",
    )
    assert all(call.scope_kind == "module" for call in analysis.call_references)


def test_attributes_default_argument_call_to_outer_scope(tmp_path: Path) -> None:
    analysis = analyze_source(
        tmp_path,
        "def run(value=build_default()):\n    pass\n",
    )

    call = analysis.call_references[0]
    assert call.target == "build_default"
    assert call.scope_kind == "module"


def test_attributes_function_body_call_to_function(tmp_path: Path) -> None:
    analysis = analyze_source(tmp_path, "def run():\n    execute()\n")

    symbol = analysis.callable_symbols[0]
    call = analysis.call_references[0]
    assert call.scope_kind == "callable"
    assert call.scope_name == "run"
    assert call.caller_symbol_id == symbol.symbol_id


def test_attributes_class_body_call_to_class(tmp_path: Path) -> None:
    analysis = analyze_source(tmp_path, "class Service:\n    value = build()\n")

    call = analysis.call_references[0]
    assert call.scope_kind == "class"
    assert call.scope_name == "Service"
    assert call.caller_symbol_id is None


def test_records_dynamic_call_expression_without_target(tmp_path: Path) -> None:
    analysis = analyze_source(tmp_path, "registry[key]()\n")

    call = analysis.call_references[0]
    assert call.kind == "dynamic"
    assert call.target is None
    assert call.expression == "registry[key]"


def test_call_order_is_deterministic(tmp_path: Path) -> None:
    source = "second()\nfirst()\nobject.method()\n"

    first = analyze_source(tmp_path, source)
    second = analyze_python_file(tmp_path / "module.py")

    assert first.call_references == second.call_references
    assert tuple(call.line for call in first.call_references) == (1, 2, 3)


def test_callable_analysis_never_executes_source(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    analysis = analyze_source(
        tmp_path,
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
    )

    assert analysis.call_references
    assert not marker.exists()
