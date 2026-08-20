"""Static resolution of structured imports against project module identities."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pysynoptic.models import (
    FileAnalysis,
    ImportReference,
    ImportResolution,
    ModuleDependency,
    ModuleIdentity,
)


def _package_name(source: ModuleIdentity) -> str | None:
    if source.path.name == "__init__.py":
        return source.dotted_name
    package, separator, _ = source.dotted_name.rpartition(".")
    return package if separator else None


def _absolute_base(source: ModuleIdentity, reference: ImportReference) -> str | None:
    if reference.kind == "import":
        return reference.module
    if reference.level == 0:
        return reference.module

    package = _package_name(source)
    if package is None:
        return None
    package_parts = package.split(".")
    parent_count = reference.level - 1
    if parent_count >= len(package_parts):
        return None

    base_parts = package_parts[: len(package_parts) - parent_count]
    if reference.module:
        base_parts.extend(reference.module.split("."))
    return ".".join(base_parts)


def _is_namespace(name: str, known_names: set[str]) -> bool:
    prefix = f"{name}."
    return any(known_name.startswith(prefix) for known_name in known_names)


def _resolution_for_reference(
    source: ModuleIdentity,
    reference: ImportReference,
    identities_by_name: dict[str, tuple[ModuleIdentity, ...]],
    known_names: set[str],
    known_top_levels: set[str],
    reexports: dict[tuple[str, str], tuple[ModuleIdentity, ...]],
) -> ImportResolution:
    base = _absolute_base(source, reference)
    is_relative = reference.level > 0
    if base is None:
        return ImportResolution(source, reference, None, "unresolved")

    if reference.kind == "import":
        requested_name = base
        candidates = (requested_name,)
    else:
        imported_name = reference.imported_name
        requested_name = (
            base
            if imported_name == "*"
            else f"{base}.{imported_name}"
            if base
            else imported_name or ""
        )
        candidates = (
            (requested_name,) if imported_name == "*" else (requested_name, base)
        )

    for index, candidate in enumerate(candidates):
        targets = identities_by_name.get(candidate, ())
        if targets:
            status = "resolved" if len(targets) == 1 else "ambiguous"
            return ImportResolution(
                source=source,
                reference=reference,
                absolute_name=requested_name,
                status=status,
                targets=targets,
            )
        if index == 0:
            imported_name = reference.imported_name
            if reference.kind == "from" and imported_name not in {None, "*"}:
                targets = reexports.get((base, imported_name), ())
                if targets:
                    status = "resolved" if len(targets) == 1 else "ambiguous"
                    return ImportResolution(
                        source=source,
                        reference=reference,
                        absolute_name=requested_name,
                        status=status,
                        targets=targets,
                    )
            if _is_namespace(candidate, known_names):
                return ImportResolution(
                    source=source,
                    reference=reference,
                    absolute_name=requested_name,
                    status="namespace",
                )

    top_level = requested_name.partition(".")[0]
    status = (
        "unresolved" if is_relative or top_level in known_top_levels else "external"
    )
    return ImportResolution(
        source=source,
        reference=reference,
        absolute_name=requested_name,
        status=status,
    )


def _local_binding(reference: ImportReference) -> str | None:
    if reference.alias:
        return reference.alias
    if reference.kind == "from":
        return None if reference.imported_name == "*" else reference.imported_name
    return reference.module.partition(".")[0] if reference.module else None


def _build_reexports(
    identities: tuple[ModuleIdentity, ...],
    analyses_by_path: dict[Path, FileAnalysis],
    identities_by_name: dict[str, tuple[ModuleIdentity, ...]],
) -> dict[tuple[str, str], tuple[ModuleIdentity, ...]]:
    raw_reexports: dict[
        tuple[str, str], list[tuple[ModuleIdentity, ImportReference]]
    ] = {}
    for source in identities:
        analysis = analyses_by_path.get(source.path)
        if analysis is None:
            continue
        for reference in analysis.import_references:
            local_binding = _local_binding(reference)
            if local_binding is None:
                continue
            raw_reexports.setdefault((source.dotted_name, local_binding), []).append(
                (source, reference)
            )

    resolved_reexports: dict[tuple[str, str], tuple[ModuleIdentity, ...]] = {}

    def resolve_reexport(
        key: tuple[str, str], trail: frozenset[tuple[str, str]] = frozenset()
    ) -> tuple[ModuleIdentity, ...]:
        if key in resolved_reexports:
            return resolved_reexports[key]
        if key in trail:
            return ()

        targets_by_path: dict[Path, ModuleIdentity] = {}
        next_trail = trail | {key}
        for source, reference in raw_reexports.get(key, []):
            base = _absolute_base(source, reference)
            if base is None:
                continue
            if reference.kind == "import":
                targets = identities_by_name.get(base, ())
            else:
                imported_name = reference.imported_name
                requested_name = (
                    base
                    if imported_name == "*"
                    else f"{base}.{imported_name}"
                    if base
                    else imported_name or ""
                )
                targets = identities_by_name.get(requested_name, ())
                nested_key = (base, imported_name or "")
                if not targets and nested_key in raw_reexports:
                    targets = resolve_reexport(nested_key, next_trail)
                if not targets:
                    targets = identities_by_name.get(base, ())
            for target in targets:
                targets_by_path[target.path] = target

        targets = tuple(
            sorted(
                targets_by_path.values(),
                key=lambda identity: (
                    identity.dotted_name.casefold(),
                    identity.dotted_name,
                    identity.path.as_posix(),
                ),
            )
        )
        resolved_reexports[key] = targets
        return targets

    for key in raw_reexports:
        resolve_reexport(key)
    return resolved_reexports


def resolve_project_imports(
    module_identities: Iterable[ModuleIdentity],
    file_analyses: Iterable[FileAnalysis],
) -> tuple[tuple[ImportResolution, ...], tuple[ModuleDependency, ...]]:
    """Resolve project imports and derive deterministic file-backed edges."""
    identities = tuple(module_identities)
    analyses_by_path = {analysis.path: analysis for analysis in file_analyses}
    grouped_identities: dict[str, list[ModuleIdentity]] = {}
    for identity in identities:
        grouped_identities.setdefault(identity.dotted_name, []).append(identity)
    identities_by_name = {
        name: tuple(group) for name, group in grouped_identities.items()
    }
    known_names = set(identities_by_name)
    known_top_levels = {name.partition(".")[0] for name in known_names}
    reexports = _build_reexports(
        identities,
        analyses_by_path,
        identities_by_name,
    )

    resolutions = []
    dependencies_by_path: dict[tuple[Path, Path], ModuleDependency] = {}
    for source in identities:
        analysis = analyses_by_path.get(source.path)
        if analysis is None:
            continue
        for reference in analysis.import_references:
            resolution = _resolution_for_reference(
                source,
                reference,
                identities_by_name,
                known_names,
                known_top_levels,
                reexports,
            )
            resolutions.append(resolution)
            if resolution.status == "resolved":
                target = resolution.targets[0]
                key = (source.path, target.path)
                dependencies_by_path.setdefault(
                    key, ModuleDependency(source=source, target=target)
                )

    dependencies = sorted(
        dependencies_by_path.values(),
        key=lambda dependency: (
            dependency.source.dotted_name.casefold(),
            dependency.source.dotted_name,
            dependency.source.path.as_posix(),
            dependency.target.dotted_name.casefold(),
            dependency.target.dotted_name,
            dependency.target.path.as_posix(),
        ),
    )
    return tuple(resolutions), tuple(dependencies)
