"""Orchestration of project scanning and Python file analysis."""

from __future__ import annotations

from pathlib import Path

from pysynoptic.analyzer.call_resolution import resolve_project_calls
from pysynoptic.analyzer.import_resolution import resolve_project_imports
from pysynoptic.analyzer.module_identity import resolve_module_identities
from pysynoptic.analyzer.python_file import analyze_python_file
from pysynoptic.models import (
    FileAnalysis,
    ProjectAnalysis,
    ProjectError,
    ProjectResource,
)
from pysynoptic.scanner import scan_project


def _completed_analysis(
    root_path: Path,
    python_files: tuple[Path, ...],
    file_analyses: tuple[FileAnalysis, ...],
    *,
    resources: tuple[ProjectResource, ...] = (),
    excluded_paths: tuple[Path, ...] = (),
    errors: tuple[ProjectError, ...] = (),
) -> ProjectAnalysis:
    source_roots, module_identities, identity_errors = resolve_module_identities(
        root_path, python_files
    )
    all_errors = (*errors, *identity_errors)
    import_resolutions, dependencies = resolve_project_imports(
        module_identities, file_analyses
    )
    callable_identities, call_resolutions, call_dependencies = resolve_project_calls(
        module_identities, file_analyses
    )
    return ProjectAnalysis(
        root_path=root_path,
        python_files=python_files,
        resources=resources,
        excluded_paths=excluded_paths,
        file_analyses=file_analyses,
        errors=all_errors,
        source_roots=source_roots,
        module_identities=module_identities,
        import_resolutions=import_resolutions,
        dependencies=dependencies,
        callable_identities=callable_identities,
        call_resolutions=call_resolutions,
        call_dependencies=call_dependencies,
    )


def analyze_python_file_context(path: Path) -> ProjectAnalysis:
    """Build project-level graph models for exactly one Python source file."""
    file_analysis = analyze_python_file(path)
    return _completed_analysis(
        path.parent,
        (path,),
        (file_analysis,),
    )


def analyze_project(path: Path) -> ProjectAnalysis:
    """Analyze every discovered Python file in a project statically."""
    scan = scan_project(path)
    file_analyses = []
    errors = list(scan.errors)
    for python_file in scan.python_files:
        try:
            file_analyses.append(analyze_python_file(python_file))
        except (OSError, ValueError) as error:
            errors.append(ProjectError(python_file, "read", str(error)))

    return _completed_analysis(
        scan.root_path,
        scan.python_files,
        tuple(file_analyses),
        resources=scan.resources,
        excluded_paths=scan.excluded_paths,
        errors=tuple(errors),
    )
