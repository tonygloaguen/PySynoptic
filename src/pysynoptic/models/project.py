"""Models used for project discovery and analysis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from pysynoptic.models.analysis import FileAnalysis

ResourceKind: TypeAlias = Literal[
    "configuration",
    "data",
    "documentation",
    "image",
    "template",
    "web",
    "other",
]
ErrorOperation: TypeAlias = Literal["identity", "scan", "read"]


@dataclass(frozen=True, slots=True)
class ProjectResource:
    """A non-Python file discovered in a project tree."""

    path: Path
    kind: ResourceKind


@dataclass(frozen=True, slots=True)
class ProjectError:
    """A recoverable filesystem or source-reading error."""

    path: Path
    operation: ErrorOperation
    message: str


@dataclass(frozen=True, slots=True)
class ModuleIdentity:
    """A project-aware dotted name assigned to one Python source file."""

    path: Path
    dotted_name: str
    source_root: Path


@dataclass(frozen=True, slots=True)
class ProjectScan:
    """Filesystem inventory produced without parsing Python source."""

    root_path: Path
    python_files: tuple[Path, ...] = ()
    resources: tuple[ProjectResource, ...] = ()
    excluded_paths: tuple[Path, ...] = ()
    errors: tuple[ProjectError, ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectAnalysis:
    """Static analysis result for a complete project directory."""

    root_path: Path
    python_files: tuple[Path, ...] = ()
    resources: tuple[ProjectResource, ...] = ()
    excluded_paths: tuple[Path, ...] = ()
    file_analyses: tuple[FileAnalysis, ...] = ()
    errors: tuple[ProjectError, ...] = ()
    source_roots: tuple[Path, ...] = ()
    module_identities: tuple[ModuleIdentity, ...] = ()
