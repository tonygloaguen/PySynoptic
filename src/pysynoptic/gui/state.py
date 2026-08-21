"""Immutable application state for the PySynoptic desktop interface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from pysynoptic.models import FileAnalysis, ProjectAnalysis

TargetKind: TypeAlias = Literal["file", "project"]


@dataclass(frozen=True, slots=True)
class ApplicationState:
    """Complete state rendered by the desktop application."""

    selected_path: Path | None = None
    target_kind: TargetKind | None = None
    file_analysis: FileAnalysis | None = None
    project_analysis: ProjectAnalysis | None = None
    mermaid_source: str = ""
    status_message: str = "Choose a Python file or project to begin."
    error_message: str | None = None
