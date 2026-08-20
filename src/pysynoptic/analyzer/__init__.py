"""Static analyzers exposed by PySynoptic."""

from pysynoptic.analyzer.project import analyze_project
from pysynoptic.analyzer.python_file import analyze_python_file

__all__ = ["analyze_project", "analyze_python_file"]
