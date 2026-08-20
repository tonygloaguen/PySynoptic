"""Orchestration of project scanning and Python file analysis."""

from __future__ import annotations

from pathlib import Path

from pysynoptic.analyzer.module_identity import resolve_module_identities
from pysynoptic.analyzer.python_file import analyze_python_file
from pysynoptic.models import ProjectAnalysis, ProjectError
from pysynoptic.scanner import scan_project


def analyze_project(path: Path) -> ProjectAnalysis:
    """Analyze every discovered Python file in a project statically."""
    scan = scan_project(path)
    file_analyses = []
    errors = list(scan.errors)
    source_roots, module_identities, identity_errors = resolve_module_identities(
        scan.root_path, scan.python_files
    )
    errors.extend(identity_errors)

    for python_file in scan.python_files:
        try:
            file_analyses.append(analyze_python_file(python_file))
        except (OSError, ValueError) as error:
            errors.append(ProjectError(python_file, "read", str(error)))

    return ProjectAnalysis(
        root_path=scan.root_path,
        python_files=scan.python_files,
        resources=scan.resources,
        excluded_paths=scan.excluded_paths,
        file_analyses=tuple(file_analyses),
        errors=tuple(errors),
        source_roots=source_roots,
        module_identities=module_identities,
    )
