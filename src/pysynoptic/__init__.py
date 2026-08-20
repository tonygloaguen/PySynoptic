"""PySynoptic public package interface."""

from pysynoptic.analyzer import analyze_project, analyze_python_file
from pysynoptic.models import FileAnalysis, ProjectAnalysis

__all__ = [
    "FileAnalysis",
    "ProjectAnalysis",
    "analyze_project",
    "analyze_python_file",
]
__version__ = "0.0.2"
