from pathlib import Path

from pysynoptic import analyze_project


def write_python(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def analyze_sources(tmp_path: Path, sources: dict[str, str]):
    for relative_path, source in sources.items():
        write_python(tmp_path / relative_path, source)
    return analyze_project(tmp_path)


def only_resolution(analysis):
    assert len(analysis.call_resolutions) == 1
    return analysis.call_resolutions[0]


def test_resolves_module_function_from_module_function(tmp_path: Path) -> None:
    analysis = analyze_sources(
        tmp_path,
        {"module.py": ("def target():\n    pass\n\ndef source():\n    target()\n")},
    )

    resolution = only_resolution(analysis)
    assert resolution.status == "resolved"
    assert resolution.reason == "lexical"
    assert resolution.targets[0].qualified_name == "module::target"


def test_resolves_lexical_nested_function(tmp_path: Path) -> None:
    analysis = analyze_sources(
        tmp_path,
        {"module.py": "def outer():\n    def inner():\n        pass\n    inner()\n"},
    )

    resolution = only_resolution(analysis)
    assert resolution.status == "resolved"
    assert resolution.targets[0].qualified_name == "module::outer.<locals>.inner"


def test_prefers_nested_function_over_module_function(tmp_path: Path) -> None:
    analysis = analyze_sources(
        tmp_path,
        {
            "module.py": (
                "def helper():\n    pass\n\n"
                "def outer():\n"
                "    def helper():\n"
                "        pass\n"
                "    helper()\n"
            )
        },
    )

    resolution = only_resolution(analysis)
    assert resolution.targets[0].qualified_name == "module::outer.<locals>.helper"


def test_resolves_same_module_async_callable(tmp_path: Path) -> None:
    analysis = analyze_sources(
        tmp_path,
        {"module.py": "async def target():\n    pass\n\ndef source():\n    target()\n"},
    )

    resolution = only_resolution(analysis)
    assert resolution.status == "resolved"
    assert resolution.targets[0].symbol.is_async is True


def test_resolves_self_method_in_same_class(tmp_path: Path) -> None:
    analysis = analyze_sources(
        tmp_path,
        {
            "module.py": (
                "class Service:\n"
                "    def target(self):\n"
                "        pass\n"
                "    def source(self):\n"
                "        self.target()\n"
            )
        },
    )

    resolution = only_resolution(analysis)
    assert resolution.status == "resolved"
    assert resolution.reason == "method"
    assert resolution.targets[0].qualified_name == "module::Service.target"


def test_resolves_cls_method_in_same_class(tmp_path: Path) -> None:
    analysis = analyze_sources(
        tmp_path,
        {
            "module.py": (
                "class Service:\n"
                "    @classmethod\n"
                "    def target(cls):\n"
                "        pass\n"
                "    @classmethod\n"
                "    def source(cls):\n"
                "        cls.target()\n"
            )
        },
    )

    resolution = only_resolution(analysis)
    assert resolution.status == "resolved"
    assert resolution.targets[0].qualified_name == "module::Service.target"


def test_leaves_unknown_self_method_unresolved(tmp_path: Path) -> None:
    analysis = analyze_sources(
        tmp_path,
        {
            "module.py": (
                "class Service:\n    def source(self):\n        self.missing()\n"
            )
        },
    )

    resolution = only_resolution(analysis)
    assert resolution.status == "unresolved"
    assert resolution.reason == "unknown"


def test_resolves_imported_callable(tmp_path: Path) -> None:
    analysis = analyze_sources(
        tmp_path,
        {
            "target.py": "def run():\n    pass\n",
            "source.py": "from target import run\n\ndef main():\n    run()\n",
        },
    )

    resolution = only_resolution(analysis)
    assert resolution.status == "resolved"
    assert resolution.reason == "imported"
    assert resolution.targets[0].qualified_name == "target::run"


def test_resolves_imported_callable_alias(tmp_path: Path) -> None:
    analysis = analyze_sources(
        tmp_path,
        {
            "target.py": "def run():\n    pass\n",
            "source.py": "from target import run as execute\nexecute()\n",
        },
    )

    assert only_resolution(analysis).targets[0].qualified_name == "target::run"


def test_resolves_function_local_import_without_leaking_it(tmp_path: Path) -> None:
    analysis = analyze_sources(
        tmp_path,
        {
            "target.py": "def run():\n    pass\n",
            "source.py": (
                "def first():\n"
                "    from target import run\n"
                "    run()\n"
                "def second():\n"
                "    run()\n"
            ),
        },
    )

    first, second = analysis.call_resolutions
    assert first.status == "resolved"
    assert first.targets[0].qualified_name == "target::run"
    assert second.status == "unresolved"


def test_resolves_imported_module_alias_call(tmp_path: Path) -> None:
    analysis = analyze_sources(
        tmp_path,
        {
            "target.py": "def run():\n    pass\n",
            "source.py": "import target as service\nservice.run()\n",
        },
    )

    assert only_resolution(analysis).targets[0].qualified_name == "target::run"


def test_function_argument_shadows_imported_module_alias(tmp_path: Path) -> None:
    analysis = analyze_sources(
        tmp_path,
        {
            "target.py": "def run():\n    pass\n",
            "source.py": (
                "import target as service\ndef main(service):\n    service.run()\n"
            ),
        },
    )

    resolution = only_resolution(analysis)
    assert resolution.status == "unresolved"
    assert resolution.reason == "shadowed"


def test_resolves_dotted_imported_module_call(tmp_path: Path) -> None:
    analysis = analyze_sources(
        tmp_path,
        {
            "package/__init__.py": "",
            "package/service.py": "def run():\n    pass\n",
            "source.py": "import package.service\npackage.service.run()\n",
        },
    )

    resolution = only_resolution(analysis)
    assert resolution.status == "resolved"
    assert resolution.targets[0].qualified_name == "package.service::run"


def test_leaves_external_imported_callable_unresolved(tmp_path: Path) -> None:
    analysis = analyze_sources(
        tmp_path,
        {"module.py": "from external_package import run\nrun()\n"},
    )

    resolution = only_resolution(analysis)
    assert resolution.status == "unresolved"
    assert resolution.reason == "external"


def test_function_argument_shadows_module_callable(tmp_path: Path) -> None:
    analysis = analyze_sources(
        tmp_path,
        {
            "module.py": (
                "def target():\n    pass\n\ndef source(target):\n    target()\n"
            )
        },
    )

    resolution = only_resolution(analysis)
    assert resolution.status == "unresolved"
    assert resolution.reason == "shadowed"


def test_assignment_shadows_module_callable(tmp_path: Path) -> None:
    analysis = analyze_sources(
        tmp_path,
        {
            "module.py": (
                "def target():\n    pass\n\n"
                "def source():\n"
                "    target = lambda: None\n"
                "    target()\n"
            )
        },
    )

    resolution = only_resolution(analysis)
    assert resolution.status == "unresolved"
    assert resolution.reason == "shadowed"


def test_reports_duplicate_callable_as_ambiguous(tmp_path: Path) -> None:
    analysis = analyze_sources(
        tmp_path,
        {
            "module.py": (
                "if condition:\n"
                "    def target():\n"
                "        pass\n"
                "else:\n"
                "    def target():\n"
                "        pass\n"
                "target()\n"
            )
        },
    )

    resolution = only_resolution(analysis)
    assert resolution.status == "ambiguous"
    assert len(resolution.targets) == 2


def test_resolves_module_level_call(tmp_path: Path) -> None:
    analysis = analyze_sources(
        tmp_path,
        {"module.py": "def target():\n    pass\n\ntarget()\n"},
    )

    resolution = only_resolution(analysis)
    dependency = analysis.call_dependencies[0]
    assert resolution.status == "resolved"
    assert dependency.source_callable is None


def test_classifies_dynamic_expression_without_resolution(tmp_path: Path) -> None:
    analysis = analyze_sources(tmp_path, {"module.py": "registry[key]()\n"})

    resolution = only_resolution(analysis)
    assert resolution.status == "dynamic"
    assert resolution.reason == "dynamic"
    assert resolution.targets == ()


def test_leaves_generic_object_method_unresolved(tmp_path: Path) -> None:
    analysis = analyze_sources(
        tmp_path,
        {"module.py": "def source(obj):\n    obj.run()\n"},
    )

    assert only_resolution(analysis).status == "unresolved"


def test_does_not_infer_inherited_method(tmp_path: Path) -> None:
    analysis = analyze_sources(
        tmp_path,
        {
            "module.py": (
                "class Base:\n"
                "    def run(self):\n"
                "        pass\n"
                "class Child(Base):\n"
                "    def start(self):\n"
                "        self.run()\n"
            )
        },
    )

    resolution = only_resolution(analysis)
    assert resolution.status == "unresolved"


def test_call_resolution_order_is_deterministic(tmp_path: Path) -> None:
    sources = {
        "module.py": (
            "def first():\n    pass\ndef second():\n    first()\n    first()\n"
        )
    }

    first = analyze_sources(tmp_path, sources)
    second = analyze_project(tmp_path)

    assert first.callable_identities == second.callable_identities
    assert first.call_resolutions == second.call_resolutions
    assert first.call_dependencies == second.call_dependencies


def test_preserves_duplicate_call_occurrences_but_deduplicates_dependencies(
    tmp_path: Path,
) -> None:
    analysis = analyze_sources(
        tmp_path,
        {
            "module.py": (
                "def target():\n    pass\ndef source():\n    target()\n    target()\n"
            )
        },
    )

    assert len(analysis.call_resolutions) == 2
    assert all(item.status == "resolved" for item in analysis.call_resolutions)
    assert len(analysis.call_dependencies) == 1


def test_call_resolution_never_executes_source(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    analysis = analyze_sources(
        tmp_path,
        {"module.py": (f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")},
    )

    assert analysis.call_resolutions
    assert not marker.exists()
