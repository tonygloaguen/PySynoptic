"""PySynoptic public package interface."""

from pysynoptic.analyzer import analyze_project, analyze_python_file
from pysynoptic.models import (
    CallableSymbol,
    CallReference,
    FileAnalysis,
    ImportReference,
    ImportResolution,
    ModuleDependency,
    ModuleIdentity,
    ProjectAnalysis,
)
from pysynoptic.renderers import render_mermaid, write_mermaid

__all__ = [
    "CallReference",
    "CallableSymbol",
    "FileAnalysis",
    "ImportReference",
    "ImportResolution",
    "ModuleDependency",
    "ModuleIdentity",
    "ProjectAnalysis",
    "analyze_project",
    "analyze_python_file",
    "render_mermaid",
    "write_mermaid",
]
__version__ = "0.0.8"
