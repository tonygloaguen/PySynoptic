"""Models used for project discovery and analysis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from pysynoptic.models.analysis import FileAnalysis
from pysynoptic.models.imports import ImportReference
from pysynoptic.models.symbols import CallableSymbol, CallReference

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
ImportResolutionStatus: TypeAlias = Literal[
    "ambiguous", "external", "namespace", "resolved", "unresolved"
]
CallResolutionStatus: TypeAlias = Literal[
    "ambiguous", "dynamic", "resolved", "unresolved"
]
CallResolutionReason: TypeAlias = Literal[
    "ambiguous",
    "dynamic",
    "external",
    "generic_attribute",
    "imported",
    "lexical",
    "method",
    "shadowed",
    "unknown",
]


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
class ImportResolution:
    """Project-level result of resolving one structured import reference."""

    source: ModuleIdentity
    reference: ImportReference
    absolute_name: str | None
    status: ImportResolutionStatus
    targets: tuple[ModuleIdentity, ...] = ()


@dataclass(frozen=True, slots=True)
class ModuleDependency:
    """A directed dependency between two file-backed project modules."""

    source: ModuleIdentity
    target: ModuleIdentity


@dataclass(frozen=True, slots=True)
class CallableIdentity:
    """A callable symbol paired with its project-aware module identity."""

    module: ModuleIdentity
    symbol: CallableSymbol

    @property
    def qualified_name(self) -> str:
        """Return a stable human-readable project callable name."""
        return f"{self.module.dotted_name}::{self.symbol.qualified_name}"


@dataclass(frozen=True, slots=True)
class CallResolution:
    """Conservative project-level resolution of one static call reference."""

    source: ModuleIdentity
    reference: CallReference
    status: CallResolutionStatus
    reason: CallResolutionReason
    targets: tuple[CallableIdentity, ...] = ()


@dataclass(frozen=True, slots=True)
class CallDependency:
    """One deduplicated, confidently resolved callable dependency."""

    source_module: ModuleIdentity
    source_callable: CallableIdentity | None
    target: CallableIdentity


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
    import_resolutions: tuple[ImportResolution, ...] = ()
    dependencies: tuple[ModuleDependency, ...] = ()
    callable_identities: tuple[CallableIdentity, ...] = ()
    call_resolutions: tuple[CallResolution, ...] = ()
    call_dependencies: tuple[CallDependency, ...] = ()
