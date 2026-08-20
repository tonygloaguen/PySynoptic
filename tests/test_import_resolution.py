from pathlib import Path

from pysynoptic import analyze_project
from pysynoptic.models import ImportResolution, ProjectAnalysis


def write_python(path: Path, source: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def resolution_from(
    analysis: ProjectAnalysis, source_name: str
) -> tuple[ImportResolution, ...]:
    return tuple(
        resolution
        for resolution in analysis.import_resolutions
        if resolution.source.dotted_name == source_name
    )


def dependency_pairs(analysis: ProjectAnalysis) -> tuple[tuple[str, str], ...]:
    return tuple(
        (dependency.source.dotted_name, dependency.target.dotted_name)
        for dependency in analysis.dependencies
    )


def test_resolves_absolute_module_import(tmp_path: Path) -> None:
    write_python(tmp_path / "src" / "package" / "service.py")
    write_python(tmp_path / "src" / "consumer.py", "import package.service\n")

    analysis = analyze_project(tmp_path)
    resolution = resolution_from(analysis, "consumer")[0]

    assert resolution.absolute_name == "package.service"
    assert resolution.status == "resolved"
    assert resolution.targets[0].dotted_name == "package.service"
    assert dependency_pairs(analysis) == (("consumer", "package.service"),)


def test_resolves_from_import_to_specific_submodule(tmp_path: Path) -> None:
    write_python(tmp_path / "package" / "__init__.py")
    write_python(tmp_path / "package" / "service.py")
    write_python(tmp_path / "consumer.py", "from package import service\n")

    resolution = resolution_from(analyze_project(tmp_path), "consumer")[0]

    assert resolution.absolute_name == "package.service"
    assert resolution.status == "resolved"
    assert resolution.targets[0].dotted_name == "package.service"


def test_resolves_imported_symbol_to_its_module(tmp_path: Path) -> None:
    write_python(tmp_path / "package" / "models.py", "class Model:\n    pass\n")
    write_python(tmp_path / "consumer.py", "from package.models import Model\n")

    analysis = analyze_project(tmp_path)
    resolution = resolution_from(analysis, "consumer")[0]

    assert resolution.absolute_name == "package.models.Model"
    assert resolution.targets[0].dotted_name == "package.models"
    assert dependency_pairs(analysis) == (("consumer", "package.models"),)


def test_follows_explicit_static_reexport(tmp_path: Path) -> None:
    write_python(
        tmp_path / "package" / "__init__.py",
        "from package.implementation import Service\n",
    )
    write_python(
        tmp_path / "package" / "implementation.py",
        "class Service:\n    pass\n",
    )
    write_python(tmp_path / "consumer.py", "from package import Service\n")

    analysis = analyze_project(tmp_path)
    resolution = resolution_from(analysis, "consumer")[0]

    assert resolution.status == "resolved"
    assert resolution.targets[0].dotted_name == "package.implementation"
    assert ("consumer", "package.implementation") in dependency_pairs(analysis)


def test_follows_aliased_static_reexport(tmp_path: Path) -> None:
    write_python(
        tmp_path / "package" / "__init__.py",
        "from package.implementation import Service as PublicService\n",
    )
    write_python(tmp_path / "package" / "implementation.py")
    write_python(tmp_path / "consumer.py", "from package import PublicService\n")

    resolution = resolution_from(analyze_project(tmp_path), "consumer")[0]

    assert resolution.targets[0].dotted_name == "package.implementation"


def test_follows_chained_static_reexports(tmp_path: Path) -> None:
    write_python(
        tmp_path / "public" / "__init__.py",
        "from intermediate import Service\n",
    )
    write_python(
        tmp_path / "intermediate.py",
        "from implementation import Service\n",
    )
    write_python(tmp_path / "implementation.py", "class Service:\n    pass\n")
    write_python(tmp_path / "consumer.py", "from public import Service\n")

    resolution = resolution_from(analyze_project(tmp_path), "consumer")[0]

    assert resolution.targets[0].dotted_name == "implementation"


def test_classifies_external_import_without_runtime_inspection(tmp_path: Path) -> None:
    write_python(tmp_path / "module.py", "import third_party_library\n")

    analysis = analyze_project(tmp_path)
    resolution = resolution_from(analysis, "module")[0]

    assert resolution.status == "external"
    assert resolution.targets == ()
    assert analysis.dependencies == ()


def test_classifies_missing_internal_module_as_unresolved(tmp_path: Path) -> None:
    write_python(tmp_path / "package" / "__init__.py")
    write_python(tmp_path / "consumer.py", "import package.missing\n")

    resolution = resolution_from(analyze_project(tmp_path), "consumer")[0]

    assert resolution.status == "unresolved"
    assert resolution.absolute_name == "package.missing"


def test_resolves_same_package_relative_import(tmp_path: Path) -> None:
    write_python(tmp_path / "package" / "service.py")
    write_python(tmp_path / "package" / "consumer.py", "from . import service\n")

    analysis = analyze_project(tmp_path)
    resolution = resolution_from(analysis, "package.consumer")[0]

    assert resolution.absolute_name == "package.service"
    assert resolution.status == "resolved"
    assert dependency_pairs(analysis) == (("package.consumer", "package.service"),)


def test_resolves_parent_package_relative_import(tmp_path: Path) -> None:
    write_python(tmp_path / "package" / "shared.py")
    write_python(
        tmp_path / "package" / "nested" / "consumer.py",
        "from .. import shared\n",
    )

    resolution = resolution_from(analyze_project(tmp_path), "package.nested.consumer")[
        0
    ]

    assert resolution.absolute_name == "package.shared"
    assert resolution.status == "resolved"


def test_resolves_relative_import_from_package_init(tmp_path: Path) -> None:
    write_python(tmp_path / "package" / "service.py")
    write_python(tmp_path / "package" / "__init__.py", "from . import service\n")

    analysis = analyze_project(tmp_path)

    assert dependency_pairs(analysis) == (("package", "package.service"),)


def test_rejects_relative_import_beyond_top_level_package(tmp_path: Path) -> None:
    write_python(tmp_path / "package" / "module.py", "from ..outside import item\n")

    resolution = resolution_from(analyze_project(tmp_path), "package.module")[0]

    assert resolution.status == "unresolved"
    assert resolution.absolute_name is None


def test_resolves_relative_import_in_namespace_package(tmp_path: Path) -> None:
    write_python(tmp_path / "src" / "acme" / "plugins" / "service.py")
    write_python(
        tmp_path / "src" / "acme" / "plugins" / "consumer.py",
        "from . import service\n",
    )

    analysis = analyze_project(tmp_path)

    assert dependency_pairs(analysis) == (
        ("acme.plugins.consumer", "acme.plugins.service"),
    )


def test_recognizes_fileless_namespace_package(tmp_path: Path) -> None:
    write_python(tmp_path / "src" / "acme" / "plugins" / "module.py")
    write_python(tmp_path / "src" / "consumer.py", "import acme.plugins\n")

    resolution = resolution_from(analyze_project(tmp_path), "consumer")[0]

    assert resolution.status == "namespace"
    assert resolution.absolute_name == "acme.plugins"
    assert resolution.targets == ()


def test_marks_duplicate_target_identity_as_ambiguous(tmp_path: Path) -> None:
    root_target = write_python(tmp_path / "target.py")
    src_target = write_python(tmp_path / "src" / "target.py")
    write_python(tmp_path / "src" / "consumer.py", "import target\n")

    analysis = analyze_project(tmp_path)
    resolution = resolution_from(analysis, "consumer")[0]

    assert resolution.status == "ambiguous"
    assert {target.path for target in resolution.targets} == {
        root_target,
        src_target,
    }
    assert analysis.dependencies == ()


def test_dependencies_are_deduplicated_and_deterministic(tmp_path: Path) -> None:
    write_python(tmp_path / "package" / "target.py")
    write_python(
        tmp_path / "consumer.py",
        "import package.target\nimport package.target as repeated\n",
    )

    first = analyze_project(tmp_path)
    second = analyze_project(tmp_path)

    assert first.import_resolutions == second.import_resolutions
    assert first.dependencies == second.dependencies
    assert dependency_pairs(first) == (("consumer", "package.target"),)
