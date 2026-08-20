"""PySynoptic public package interface."""

from pysynoptic.analyzer import analyze_project, analyze_python_file
from pysynoptic.models import (
    FileAnalysis,
    ImportReference,
    ImportResolution,
    ModuleDependency,
    ModuleIdentity,
    ProjectAnalysis,
)

__all__ = [
    "FileAnalysis",
    "ImportReference",
    "ImportResolution",
    "ModuleDependency",
    "ModuleIdentity",
    "ProjectAnalysis",
    "analyze_project",
    "analyze_python_file",
]
__version__ = "0.0.4"
