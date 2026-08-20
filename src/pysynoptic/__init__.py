"""PySynoptic public package interface."""

from pysynoptic.analyzer import analyze_python_file
from pysynoptic.models import FileAnalysis

__all__ = ["FileAnalysis", "analyze_python_file"]
__version__ = "0.1.0"
