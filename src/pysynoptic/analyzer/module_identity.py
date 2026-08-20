"""Project-aware Python module identity resolution."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pysynoptic.models import ModuleIdentity, ProjectError


def resolve_source_roots(project_root: Path) -> tuple[Path, ...]:
    """Return conventional source roots from most to least specific."""
    src_root = project_root / "src"
    if src_root.is_dir() and not src_root.is_symlink():
        return (src_root, project_root)
    return (project_root,)


def _source_root_for(path: Path, source_roots: tuple[Path, ...]) -> Path:
    for source_root in source_roots:
        if path.is_relative_to(source_root):
            return source_root
    return source_roots[-1]


def _dotted_name(path: Path, source_root: Path) -> str:
    relative_path = path.relative_to(source_root).with_suffix("")
    parts = list(relative_path.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts else "__init__"


def resolve_module_identities(
    project_root: Path, python_files: Iterable[Path]
) -> tuple[tuple[Path, ...], tuple[ModuleIdentity, ...], tuple[ProjectError, ...]]:
    """Resolve deterministic dotted names and report ambiguous identities."""
    source_roots = resolve_source_roots(project_root)
    identities = []
    for path in python_files:
        source_root = _source_root_for(path, source_roots)
        identities.append(
            ModuleIdentity(
                path=path,
                dotted_name=_dotted_name(path, source_root),
                source_root=source_root,
            )
        )
    identities.sort(
        key=lambda identity: (
            identity.dotted_name.casefold(),
            identity.dotted_name,
            identity.path.as_posix(),
        )
    )

    identities_by_name: dict[str, list[ModuleIdentity]] = {}
    for identity in identities:
        identities_by_name.setdefault(identity.dotted_name, []).append(identity)

    errors = []
    sorted_names = sorted(identities_by_name, key=lambda name: (name.casefold(), name))
    for dotted_name in sorted_names:
        duplicates = identities_by_name[dotted_name]
        if len(duplicates) < 2:
            continue
        paths = ", ".join(
            sorted(
                str(identity.path.relative_to(project_root)) for identity in duplicates
            )
        )
        errors.append(
            ProjectError(
                path=project_root,
                operation="identity",
                message=f"Duplicate module identity '{dotted_name}': {paths}",
            )
        )

    return source_roots, tuple(identities), tuple(errors)
