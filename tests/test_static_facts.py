from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from pysynoptic import analyze_project
from pysynoptic.insights import extract_project_facts


def write_sources(tmp_path: Path, sources: dict[str, str]):
    for relative_path, source in sources.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return analyze_project(tmp_path)


def module_named(analysis, name: str):
    return next(item for item in extract_project_facts(analysis) if item.module == name)


def callable_named(module, qualified_name: str):
    return next(
        item for item in module.callable_facts if item.qualified_name == qualified_name
    )


def test_extracts_callable_declaration_structure_exceptions_and_operations(
    tmp_path: Path,
) -> None:
    analysis = write_sources(
        tmp_path,
        {
            "sample.py": (
                "from pathlib import Path\n"
                "import logging\n"
                "import os\n"
                "import socket\n"
                "import subprocess as sp\n\n"
                "import subprocess\n\n"
                "def decorated(value):\n    return value\n\n"
                "@decorated('worker')\n"
                "async def process(prefix: str, /, item: int = 1, "
                "*items: int, flag: bool = True, **options: str) -> list[str]:\n"
                '    """Process one item.\n\n    More details."""\n'
                "    if flag:\n        item += 1\n"
                "    for value in items:\n        print(value)\n"
                "    try:\n"
                "        Path('input').read_text()\n"
                "        Path('output').write_text(str(item))\n"
                "        open('audit.log')\n"
                "        Path('folder').mkdir()\n"
                "        sp.run(['tool'])\n"
                "        os.getenv('TOKEN')\n"
                "        os.environ['MODE']\n"
                "        socket.create_connection(('localhost', 80))\n"
                "        logging.info('done')\n"
                "    except (ValueError, TypeError):\n"
                "        raise RuntimeError()\n"
                "    return [str(item)]\n"
            )
        },
    )

    facts = callable_named(module_named(analysis, "sample"), "process")

    assert facts.display_name == "process()"
    assert facts.kind == "function"
    assert facts.is_async is True
    assert facts.positional_only_args[0].name == "prefix"
    assert facts.positional_only_args[0].annotation == "str"
    assert facts.arguments[0].default == "1"
    assert facts.keyword_only_args[0].default == "True"
    assert facts.vararg is not None and facts.vararg.name == "items"
    assert facts.varkw is not None and facts.varkw.name == "options"
    assert facts.return_annotation == "list[str]"
    assert facts.decorators == ("decorated('worker')",)
    assert facts.docstring_summary == "Process one item."
    assert facts.branch_count == 1
    assert facts.loop_count == 1
    assert facts.try_block_count == 1
    assert facts.except_handler_count == 1
    assert facts.return_statement_count == 1
    assert facts.raise_statement_count == 1
    assert facts.raised_exceptions == ("RuntimeError",)
    assert facts.caught_exceptions == ("TypeError", "ValueError")
    assert {item.operation for item in facts.io_operations} == {
        "mkdir",
        "open",
        "read_text",
        "write_text",
    }
    assert {item.operation for item in facts.process_operations} == {"subprocess.run"}
    assert {item.operation for item in facts.environment_operations} == {
        "os.environ",
        "os.getenv",
    }
    assert {item.operation for item in facts.network_operations} == {
        "socket.create_connection"
    }
    assert {item.operation for item in facts.logging_operations} == {"logging.info"}


def test_extracts_resolved_callers_callees_and_other_resolution_counts(
    tmp_path: Path,
) -> None:
    analysis = write_sources(
        tmp_path,
        {
            "calls.py": (
                "def target():\n    return 1\n\n"
                "def caller(registry):\n"
                "    target()\n"
                "    missing()\n"
                "    registry['handler']()\n"
            )
        },
    )
    module = module_named(analysis, "calls")
    caller = callable_named(module, "caller")
    target = callable_named(module, "target")

    assert caller.resolved_callees == ("calls::target",)
    assert caller.unresolved_call_count == 1
    assert caller.dynamic_call_count == 1
    assert caller.ambiguous_call_count == 0
    assert target.resolved_callers == ("calls::caller",)


def test_ambiguous_call_is_counted_without_becoming_a_resolved_callee(
    tmp_path: Path,
) -> None:
    analysis = write_sources(
        tmp_path,
        {
            "ambiguous.py": (
                "if enabled:\n"
                "    def target():\n        pass\n"
                "else:\n"
                "    def target():\n        pass\n"
                "def caller():\n    target()\n"
            )
        },
    )

    caller = callable_named(module_named(analysis, "ambiguous"), "caller")

    assert caller.ambiguous_call_count == 1
    assert caller.unresolved_call_count == 0
    assert caller.dynamic_call_count == 0
    assert caller.resolved_callees == ()


def test_return_facts_distinguish_values_none_and_multiple_paths(
    tmp_path: Path,
) -> None:
    analysis = write_sources(
        tmp_path,
        {
            "returns.py": (
                "def choose(flag):\n    if flag:\n        return None\n    return 1\n"
            )
        },
    )

    facts = callable_named(module_named(analysis, "returns"), "choose")

    assert facts.has_explicit_return is True
    assert facts.returns_value is True
    assert facts.returns_none_explicitly is True
    assert facts.multiple_return_paths is True
    assert facts.return_statement_count == 2


def test_nested_callable_structure_does_not_leak_into_parent(
    tmp_path: Path,
) -> None:
    analysis = write_sources(
        tmp_path,
        {
            "nested.py": (
                "def outer():\n"
                "    def inner(items):\n"
                "        for item in items:\n            print(item)\n"
                "        return 1\n"
                "    class Local:\n"
                "        def method(self, items):\n"
                "            while items:\n                items.pop()\n"
                "            raise ValueError()\n"
                "    return None\n"
            )
        },
    )
    module = module_named(analysis, "nested")
    outer = callable_named(module, "outer")
    inner = callable_named(module, "outer.<locals>.inner")
    method = callable_named(module, "outer.<locals>.Local.method")

    assert outer.loop_count == 0
    assert outer.return_statement_count == 1
    assert outer.returns_none_explicitly is True
    assert outer.statement_count == 3
    assert outer.unresolved_call_count == 0
    assert inner.loop_count == 1
    assert inner.return_statement_count == 1
    assert inner.statement_count == 3
    assert inner.unresolved_call_count == 1
    assert method.loop_count == 1
    assert method.raise_statement_count == 1
    assert method.raised_exceptions == ("ValueError",)


def test_extracts_class_declaration_methods_and_variables(tmp_path: Path) -> None:
    analysis = write_sources(
        tmp_path,
        {
            "classes.py": (
                "from dataclasses import dataclass\n\n"
                "class Base:\n    pass\n\n"
                "@dataclass(frozen=True)\n"
                "class Item(Base):\n"
                '    """Stored item."""\n'
                "    kind = 'entry'\n"
                "    value: int = 0\n"
                "    def run(self):\n        return self.value\n"
                "    async def load(self):\n        return None\n"
            )
        },
    )

    module = module_named(analysis, "classes")
    item = next(value for value in module.class_facts if value.name == "Item")

    assert item.qualified_name == "Item"
    assert item.docstring_summary == "Stored item."
    assert item.decorators == ("dataclass(frozen=True)",)
    assert item.base_classes == ("Base",)
    assert item.methods == ("Item.run", "Item.load")
    assert item.async_methods == ("Item.load",)
    assert item.class_variables == ("kind", "value")
    assert item.is_dataclass is True
    assert item.method_count == 2


def test_extracts_module_import_dependencies_declarations_and_top_level_facts(
    tmp_path: Path,
) -> None:
    analysis = write_sources(
        tmp_path,
        {
            "target.py": "def run():\n    return 1\n",
            "source.py": (
                '"""Source module."""\n'
                "import json\n"
                "import target\n\n"
                "VALUE = 1\n"
                "class Service:\n    pass\n"
                "def main():\n    return target.run()\n"
                "target.run()\n"
                "open('module.log')\n"
            ),
        },
    )

    facts = module_named(analysis, "source")

    assert facts.docstring_summary == "Source module."
    assert facts.imports == ("json", "target")
    assert facts.resolved_internal_dependencies == ("target",)
    assert facts.external_import_names == ("json",)
    assert facts.functions == ("main",)
    assert facts.classes == ("Service",)
    assert facts.module_level_callables == ("main",)
    assert facts.module_level_executable_statement_count == 3
    assert facts.module_level_calls == ("target.run", "open")
    assert {item.operation for item in facts.io_operations} == {"open"}
    assert callable_named(facts, "main").has_docstring is False
    assert facts.class_facts[0].has_docstring is False


def test_path_rename_and_replace_require_syntactic_path_evidence(
    tmp_path: Path,
) -> None:
    analysis = write_sources(
        tmp_path,
        {
            "paths.py": (
                "from pathlib import Path\n\n"
                "def update(path: Path, text: str, sink):\n"
                "    import subprocess as local_sp\n"
                "    other = Path('other')\n"
                "    path.rename(other)\n"
                "    other.replace(path)\n"
                "    text.replace('a', 'b')\n"
                "    sink.write_text(text)\n"
                "    local_sp.run(['tool'])\n"
            )
        },
    )

    facts = callable_named(module_named(analysis, "paths"), "update")

    assert [item.operation for item in facts.io_operations] == ["rename", "replace"]
    assert [item.operation for item in facts.process_operations] == ["subprocess.run"]


def test_specialized_operations_require_unshadowed_external_import_evidence(
    tmp_path: Path,
) -> None:
    analysis = write_sources(
        tmp_path,
        {
            "shadowed.py": (
                "from pathlib import Path\n"
                "import logging\n"
                "import os\n"
                "import socket\n"
                "import subprocess as sp\n\n"
                "open = lambda value: value\n\n"
                "def run(Path, logging, open, os, socket, sp):\n"
                "    Path('out').write_text('x')\n"
                "    logging.info('x')\n"
                "    open('out')\n"
                "    os.getenv('TOKEN')\n"
                "    socket.create_connection(('localhost', 80))\n"
                "    sp.run(['tool'])\n"
                "def module_shadow():\n    open('out')\n"
                "def outer(callback):\n"
                "    sp = callback\n"
                "    def inner():\n        sp.run(['tool'])\n"
                "    return inner\n"
                "def comprehension(items):\n"
                "    return [subprocess.run() for subprocess in items]\n"
                "def match_alias(value):\n"
                "    match value:\n"
                "        case {'runner': sp}:\n            sp.run(['tool'])\n"
            )
        },
    )

    facts = callable_named(module_named(analysis, "shadowed"), "run")

    assert facts.io_operations == ()
    assert facts.process_operations == ()
    assert facts.environment_operations == ()
    assert facts.network_operations == ()
    assert facts.logging_operations == ()
    assert (
        callable_named(
            module_named(analysis, "shadowed"), "module_shadow"
        ).io_operations
        == ()
    )
    assert (
        callable_named(
            module_named(analysis, "shadowed"), "comprehension"
        ).process_operations
        == ()
    )
    assert (
        callable_named(
            module_named(analysis, "shadowed"), "match_alias"
        ).process_operations
        == ()
    )
    assert (
        callable_named(
            module_named(analysis, "shadowed"), "outer.<locals>.inner"
        ).process_operations
        == ()
    )


def test_internal_modules_do_not_gain_external_library_semantics(
    tmp_path: Path,
) -> None:
    analysis = write_sources(
        tmp_path,
        {
            "logging.py": "def info(value):\n    return value\n",
            "os.py": "def getenv(name):\n    return name\n",
            "pathlib.py": "class Path:\n    pass\n",
            "socket.py": "def create_connection(value):\n    return value\n",
            "subprocess.py": "def run(value):\n    return value\n",
            "consumer.py": (
                "from pathlib import Path\n"
                "import logging\n"
                "import os\n"
                "import socket\n"
                "import subprocess\n\n"
                "def run():\n"
                "    Path('out').write_text('x')\n"
                "    logging.info('x')\n"
                "    os.getenv('TOKEN')\n"
                "    socket.create_connection(('localhost', 80))\n"
                "    subprocess.run(['tool'])\n"
            ),
        },
    )

    facts = callable_named(module_named(analysis, "consumer"), "run")

    assert facts.io_operations == ()
    assert facts.process_operations == ()
    assert facts.environment_operations == ()
    assert facts.network_operations == ()
    assert facts.logging_operations == ()


def test_fact_extraction_never_executes_module_level_source(tmp_path: Path) -> None:
    markers = tuple(tmp_path / f"SHOULD_NOT_EXIST_{index}" for index in range(4))
    analysis = write_sources(
        tmp_path,
        {
            "unsafe.py": (
                "from pathlib import Path\n"
                "import side_effect_package\n"
                "import subprocess\n\n"
                "def dangerous():\n"
                f"    Path({str(markers[0])!r}).write_text('function')\n"
                "@dangerous()\n"
                "def decorated(value=dangerous()):\n    return value\n"
                "class Dangerous:\n"
                f"    Path({str(markers[1])!r}).write_text('class')\n"
                f"Path({str(markers[2])!r}).write_text('module')\n"
                f"subprocess.run(['touch', {str(markers[3])!r}])\n"
            )
        },
    )

    facts = extract_project_facts(analysis)

    assert facts[0].io_operations[0].operation == "write_text"
    assert facts[0].process_operations[0].operation == "subprocess.run"
    assert all(not marker.exists() for marker in markers)


def test_fact_extraction_is_exactly_deterministic_and_models_are_frozen(
    tmp_path: Path,
) -> None:
    analysis = write_sources(
        tmp_path,
        {
            "zeta.py": "def last():\n    return None\n",
            "alpha.py": "def run(value: int = 1) -> int:\n    return value\n",
        },
    )

    first = extract_project_facts(analysis)
    second = extract_project_facts(analysis)

    assert first == second
    assert tuple(item.module for item in first) == ("alpha", "zeta")
    with pytest.raises(FrozenInstanceError):
        first[0].module = "changed"
