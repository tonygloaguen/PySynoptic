"""Filesystem discovery API for Python projects."""

from pysynoptic.scanner.exclusions import DEFAULT_EXCLUDED_DIRECTORIES
from pysynoptic.scanner.project_scanner import scan_project

__all__ = ["DEFAULT_EXCLUDED_DIRECTORIES", "scan_project"]
