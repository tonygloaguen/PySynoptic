from pathlib import Path

from pysynoptic import analyze_project, analyze_python_file
from pysynoptic.models import ModuleIdentity, ProjectAnalysis
from pysynoptic.scanner import scan_project


def write_python(path: Path, source: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def identities_by_path(analysis: ProjectAnalysis) -> dict[Path, ModuleIdentity]:
    return {identity.path: identity for identity in analysis.module_identities}


def test_resolves_flat_layout_module(tmp_path: Path) -> None:
    module_path = write_python(tmp_path / "package" / "module.py")

    analysis = analyze_project(tmp_path)

    identity = identities_by_path(analysis)[module_path]
    assert identity.dotted_name == "package.module"
    assert identity.source_root == tmp_path


def test_resolves_nested_module(tmp_path: Path) -> None:
    module_path = write_python(tmp_path / "package" / "services" / "api.py")

    identity = identities_by_path(analyze_project(tmp_path))[module_path]

    assert identity.dotted_name == "package.services.api"


def test_resolves_init_modules_to_package_names(tmp_path: Path) -> None:
    package_init = write_python(tmp_path / "package" / "__init__.py")
    nested_init = write_python(tmp_path / "package" / "plugins" / "__init__.py")

    identities = identities_by_path(analyze_project(tmp_path))

    assert identities[package_init].dotted_name == "package"
    assert identities[nested_init].dotted_name == "package.plugins"


def test_keeps_main_as_module_component(tmp_path: Path) -> None:
    main_path = write_python(tmp_path / "package" / "__main__.py")

    identity = identities_by_path(analyze_project(tmp_path))[main_path]

    assert identity.dotted_name == "package.__main__"


def test_src_layout_omits_src_from_module_name(tmp_path: Path) -> None:
    module_path = write_python(tmp_path / "src" / "acme" / "service.py")

    analysis = analyze_project(tmp_path)
    identity = identities_by_path(analysis)[module_path]

    assert analysis.source_roots == (tmp_path / "src", tmp_path)
    assert identity.dotted_name == "acme.service"
    assert identity.source_root == tmp_path / "src"


def test_resolves_src_layout_top_level_module(tmp_path: Path) -> None:
    module_path = write_python(tmp_path / "src" / "command.py")

    identity = identities_by_path(analyze_project(tmp_path))[module_path]

    assert identity.dotted_name == "command"


def test_resolves_project_root_module_when_src_exists(tmp_path: Path) -> None:
    write_python(tmp_path / "src" / "package" / "__init__.py")
    script_path = write_python(tmp_path / "script.py")

    identity = identities_by_path(analyze_project(tmp_path))[script_path]

    assert identity.dotted_name == "script"
    assert identity.source_root == tmp_path


def test_resolves_namespace_style_package_without_init(tmp_path: Path) -> None:
    module_path = write_python(tmp_path / "src" / "acme" / "plugins" / "loader.py")

    identity = identities_by_path(analyze_project(tmp_path))[module_path]

    assert identity.dotted_name == "acme.plugins.loader"


def test_module_identity_order_is_deterministic(tmp_path: Path) -> None:
    write_python(tmp_path / "zebra.py")
    write_python(tmp_path / "alpha" / "zulu.py")
    write_python(tmp_path / "alpha" / "__init__.py")

    first = analyze_project(tmp_path).module_identities
    second = analyze_project(tmp_path).module_identities

    assert first == second
    assert tuple(identity.dotted_name for identity in first) == (
        "alpha",
        "alpha.zulu",
        "zebra",
    )


def test_reports_duplicate_module_identities(tmp_path: Path) -> None:
    root_module = write_python(tmp_path / "tool.py")
    src_module = write_python(tmp_path / "src" / "tool.py")

    analysis = analyze_project(tmp_path)

    duplicates = [error for error in analysis.errors if error.operation == "identity"]
    assert len(duplicates) == 1
    assert "Duplicate module identity 'tool'" in duplicates[0].message
    assert {identity.path for identity in analysis.module_identities} == {
        root_module,
        src_module,
    }


def test_project_scanning_inventory_is_unchanged(tmp_path: Path) -> None:
    module_path = write_python(tmp_path / "src" / "package" / "module.py")

    scan = scan_project(tmp_path)
    analysis = analyze_project(tmp_path)

    assert scan.python_files == analysis.python_files == (module_path,)
    assert scan.resources == analysis.resources
    assert scan.excluded_paths == analysis.excluded_paths


def test_single_file_api_keeps_stem_module_name(tmp_path: Path) -> None:
    module_path = write_python(tmp_path / "package" / "nested" / "module.py")

    analysis = analyze_python_file(module_path)

    assert analysis.module_name == "module"
