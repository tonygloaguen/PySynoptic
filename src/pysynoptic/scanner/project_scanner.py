"""Recursive filesystem discovery for Python projects."""

from __future__ import annotations

from pathlib import Path

from pysynoptic.models import ProjectError, ProjectResource, ProjectScan
from pysynoptic.models.project import ResourceKind
from pysynoptic.scanner.exclusions import is_excluded_directory

_IMAGE_SUFFIXES = frozenset({".gif", ".ico", ".jpeg", ".jpg", ".png", ".svg", ".webp"})
_DATA_SUFFIXES = frozenset({".csv", ".json", ".tsv", ".xml"})
_CONFIGURATION_SUFFIXES = frozenset({".ini", ".toml", ".yaml", ".yml"})
_WEB_SUFFIXES = frozenset(
    {".css", ".htm", ".html", ".js", ".jsx", ".mjs", ".ts", ".tsx"}
)
_DOCUMENTATION_SUFFIXES = frozenset({".md", ".rst"})
_TEMPLATE_SUFFIXES = frozenset({".j2", ".jinja", ".jinja2", ".template", ".tmpl"})


def _resource_kind(path: Path) -> ResourceKind:
    name = path.name.casefold()
    suffix = path.suffix.casefold()

    if (
        name in {".editorconfig", ".env", ".gitignore", "dockerfile", "makefile"}
        or name.startswith("dockerfile.")
        or name.startswith("compose.")
        or name.startswith("requirements")
        or suffix in _CONFIGURATION_SUFFIXES
    ):
        return "configuration"
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    if suffix in _DATA_SUFFIXES:
        return "data"
    if suffix in _WEB_SUFFIXES:
        return "web"
    if suffix in _DOCUMENTATION_SUFFIXES or name in {"license", "copying"}:
        return "documentation"
    if suffix in _TEMPLATE_SUFFIXES:
        return "template"
    return "other"


def _scan_directory(
    directory: Path,
    python_files: list[Path],
    resources: list[ProjectResource],
    excluded_paths: list[Path],
    errors: list[ProjectError],
) -> None:
    try:
        entries = sorted(directory.iterdir(), key=lambda entry: entry.name.casefold())
    except OSError as error:
        errors.append(ProjectError(directory, "scan", str(error)))
        return

    for entry in entries:
        try:
            if entry.is_symlink():
                excluded_paths.append(entry)
            elif entry.is_dir():
                if is_excluded_directory(entry.name):
                    excluded_paths.append(entry)
                else:
                    _scan_directory(
                        entry,
                        python_files,
                        resources,
                        excluded_paths,
                        errors,
                    )
            elif entry.is_file():
                if entry.suffix == ".py":
                    python_files.append(entry)
                else:
                    resources.append(ProjectResource(entry, _resource_kind(entry)))
        except OSError as error:
            errors.append(ProjectError(entry, "scan", str(error)))


def scan_project(path: Path) -> ProjectScan:
    """Inventory a project directory without reading or parsing its files."""
    if not path.exists():
        raise FileNotFoundError(f"Project path not found: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Expected a project directory: {path}")

    python_files: list[Path] = []
    resources: list[ProjectResource] = []
    excluded_paths: list[Path] = []
    errors: list[ProjectError] = []
    _scan_directory(path, python_files, resources, excluded_paths, errors)

    return ProjectScan(
        root_path=path,
        python_files=tuple(python_files),
        resources=tuple(resources),
        excluded_paths=tuple(excluded_paths),
        errors=tuple(errors),
    )
