"""Immutable application state for the PySynoptic desktop interface."""

from __future__ import annotations

from dataclasses import dataclass, replace
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
    is_analyzing: bool = False


@dataclass(frozen=True, slots=True)
class ApplicationControls:
    """Enabled GUI actions derived exclusively from immutable state."""

    can_select: bool
    can_analyze: bool
    can_export: bool


def controls_for_state(state: ApplicationState) -> ApplicationControls:
    """Return deterministic toolbar availability for an application state."""
    idle = not state.is_analyzing
    return ApplicationControls(
        can_select=idle,
        can_analyze=idle and state.target_kind is not None,
        can_export=idle and state.project_analysis is not None,
    )


def mark_analysis_started(state: ApplicationState) -> ApplicationState:
    """Return the visible pending state without performing analysis."""
    target_label = "project" if state.target_kind == "project" else "file"
    return replace(
        state,
        is_analyzing=True,
        status_message=f"Analyzing {target_label}: {state.selected_path}",
        error_message=None,
    )
