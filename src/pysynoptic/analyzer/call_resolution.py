"""Conservative static resolution of project call references."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from pysynoptic.models import (
    CallableIdentity,
    CallDependency,
    CallReference,
    CallResolution,
    FileAnalysis,
    ImportReference,
    ModuleIdentity,
    NameBinding,
)
from pysynoptic.models.project import CallResolutionReason


def _identity_key(identity: CallableIdentity) -> tuple[str, str, str, int, int]:
    return (
        identity.module.dotted_name.casefold(),
        identity.module.dotted_name,
        identity.symbol.qualified_name,
        identity.symbol.line,
        identity.symbol.column,
    )


def _local_import_name(reference: ImportReference) -> str | None:
    if reference.alias:
        return reference.alias
    if reference.kind == "from":
        return None if reference.imported_name == "*" else reference.imported_name
    return reference.module.partition(".")[0] if reference.module else None


def _absolute_import_base(
    source: ModuleIdentity,
    reference: ImportReference,
) -> str | None:
    if reference.kind == "import" or reference.level == 0:
        return reference.module
    package = (
        source.dotted_name
        if source.path.name == "__init__.py"
        else source.dotted_name.rpartition(".")[0]
    )
    if not package:
        return None
    parts = package.split(".")
    parent_count = reference.level - 1
    if parent_count >= len(parts):
        return None
    base_parts = parts[: len(parts) - parent_count]
    if reference.module:
        base_parts.extend(reference.module.split("."))
    return ".".join(base_parts)


class _CallResolver:
    def __init__(
        self,
        module_identities: tuple[ModuleIdentity, ...],
        file_analyses: tuple[FileAnalysis, ...],
    ) -> None:
        self.modules = module_identities
        self.analyses_by_path = {analysis.path: analysis for analysis in file_analyses}
        self.modules_by_name: dict[str, list[ModuleIdentity]] = defaultdict(list)
        for module in module_identities:
            self.modules_by_name[module.dotted_name].append(module)
        self.known_top_levels = {
            module.dotted_name.partition(".")[0] for module in module_identities
        }

        identities = []
        for module in module_identities:
            analysis = self.analyses_by_path.get(module.path)
            if analysis is None:
                continue
            identities.extend(
                CallableIdentity(module=module, symbol=symbol)
                for symbol in analysis.callable_symbols
            )
        self.callable_identities = tuple(sorted(identities, key=_identity_key))
        self.callables_by_id = {
            identity.symbol.symbol_id: identity for identity in self.callable_identities
        }

        self.top_level: dict[tuple[Path, str], list[CallableIdentity]] = defaultdict(
            list
        )
        self.nested: dict[tuple[str, str], list[CallableIdentity]] = defaultdict(list)
        self.methods: dict[tuple[Path, str, str], list[CallableIdentity]] = defaultdict(
            list
        )
        for identity in self.callable_identities:
            symbol = identity.symbol
            if symbol.kind == "method":
                owner, _, _ = symbol.qualified_name.rpartition(".")
                self.methods[(identity.module.path, owner, symbol.name)].append(
                    identity
                )
            elif symbol.parent_symbol_id is not None:
                self.nested[(symbol.parent_symbol_id, symbol.name)].append(identity)
            elif symbol.qualified_name == symbol.name:
                self.top_level[(identity.module.path, symbol.name)].append(identity)

    @staticmethod
    def _result(
        source: ModuleIdentity,
        reference: CallReference,
        candidates: Iterable[CallableIdentity] = (),
        *,
        unresolved_reason: CallResolutionReason = "unknown",
    ) -> CallResolution:
        targets = tuple(sorted(set(candidates), key=_identity_key))
        if len(targets) == 1:
            return CallResolution(source, reference, "resolved", "lexical", targets)
        if len(targets) > 1:
            return CallResolution(source, reference, "ambiguous", "ambiguous", targets)
        return CallResolution(
            source,
            reference,
            "unresolved",
            unresolved_reason,
        )

    @staticmethod
    def _bindings(
        analysis: FileAnalysis,
        name: str,
        *,
        scope_symbol_id: str | None,
        scope_kind: str,
        scope_name: str,
    ) -> tuple[NameBinding, ...]:
        return tuple(
            binding
            for binding in analysis.name_bindings
            if binding.name == name
            and binding.scope_symbol_id == scope_symbol_id
            and binding.scope_kind == scope_kind
            and binding.scope_name == scope_name
        )

    @staticmethod
    def _matching_imports(
        analysis: FileAnalysis,
        bindings: Iterable[NameBinding],
    ) -> tuple[ImportReference, ...]:
        locations = {
            (binding.line, binding.column, binding.name) for binding in bindings
        }
        return tuple(
            reference
            for reference in analysis.import_references
            if (
                reference.line,
                reference.column,
                _local_import_name(reference),
            )
            in locations
        )

    def _module_callable_candidates(
        self,
        module_name: str,
        callable_name: str,
    ) -> tuple[CallableIdentity, ...]:
        return tuple(
            candidate
            for module in self.modules_by_name.get(module_name, ())
            for candidate in self.top_level.get((module.path, callable_name), ())
        )

    def _resolve_imported_name(
        self,
        source: ModuleIdentity,
        reference: CallReference,
        imports: tuple[ImportReference, ...],
    ) -> CallResolution:
        candidates: list[CallableIdentity] = []
        external = False
        for imported in imports:
            base = _absolute_import_base(source, imported)
            if base is None:
                continue
            if imported.kind == "from" and imported.imported_name not in {None, "*"}:
                candidates.extend(
                    self._module_callable_candidates(base, imported.imported_name)
                )
            if base.partition(".")[0] not in self.known_top_levels:
                external = True
        result = self._result(
            source,
            reference,
            candidates,
            unresolved_reason="external" if external else "unknown",
        )
        if result.status == "resolved":
            return CallResolution(
                source,
                reference,
                result.status,
                "imported",
                result.targets,
            )
        return result

    def _resolve_imported_attribute(
        self,
        source: ModuleIdentity,
        reference: CallReference,
        parts: list[str],
        imports: tuple[ImportReference, ...],
    ) -> CallResolution:
        candidates: list[CallableIdentity] = []
        external = False
        for imported in imports:
            base = _absolute_import_base(source, imported)
            if base is None:
                continue
            if imported.kind == "import":
                if imported.alias:
                    module_name = ".".join((base, *parts[1:-1]))
                else:
                    module_name = ".".join(parts[:-1])
            elif imported.imported_name not in {None, "*"}:
                module_name = ".".join((base, imported.imported_name, *parts[1:-1]))
            else:
                continue
            candidates.extend(self._module_callable_candidates(module_name, parts[-1]))
            if module_name.partition(".")[0] not in self.known_top_levels:
                external = True
        result = self._result(
            source,
            reference,
            candidates,
            unresolved_reason="external" if external else "unknown",
        )
        if result.status == "resolved":
            return CallResolution(
                source,
                reference,
                result.status,
                "imported",
                result.targets,
            )
        return result

    def _scope_chain(
        self,
        reference: CallReference,
    ) -> tuple[CallableIdentity, ...]:
        chain = []
        symbol_id = reference.caller_symbol_id
        while symbol_id is not None:
            identity = self.callables_by_id.get(symbol_id)
            if identity is None:
                break
            chain.append(identity)
            symbol_id = identity.symbol.parent_symbol_id
        return tuple(chain)

    def _resolve_name(
        self,
        source: ModuleIdentity,
        analysis: FileAnalysis,
        reference: CallReference,
    ) -> CallResolution:
        name = reference.target or ""
        for scope in self._scope_chain(reference):
            bindings = self._bindings(
                analysis,
                name,
                scope_symbol_id=scope.symbol.symbol_id,
                scope_kind="callable",
                scope_name=scope.symbol.qualified_name,
            )
            blockers = tuple(
                binding for binding in bindings if binding.kind != "import"
            )
            imports = tuple(binding for binding in bindings if binding.kind == "import")
            candidates = tuple(self.nested.get((scope.symbol.symbol_id, name), ()))
            if blockers:
                return CallResolution(source, reference, "unresolved", "shadowed")
            if imports and candidates:
                return CallResolution(
                    source,
                    reference,
                    "ambiguous",
                    "ambiguous",
                    tuple(sorted(candidates, key=_identity_key)),
                )
            if imports:
                return self._resolve_imported_name(
                    source,
                    reference,
                    self._matching_imports(analysis, imports),
                )
            if candidates:
                return self._result(source, reference, candidates)

        module_bindings = self._bindings(
            analysis,
            name,
            scope_symbol_id=None,
            scope_kind="module",
            scope_name="<module>",
        )
        blockers = tuple(
            binding for binding in module_bindings if binding.kind != "import"
        )
        imports = tuple(
            binding for binding in module_bindings if binding.kind == "import"
        )
        candidates = tuple(self.top_level.get((source.path, name), ()))
        if blockers:
            return CallResolution(source, reference, "unresolved", "shadowed")
        if imports and candidates:
            return CallResolution(
                source,
                reference,
                "ambiguous",
                "ambiguous",
                tuple(sorted(candidates, key=_identity_key)),
            )
        if imports:
            return self._resolve_imported_name(
                source,
                reference,
                self._matching_imports(analysis, imports),
            )
        return self._result(source, reference, candidates)

    def _resolve_method(
        self,
        source: ModuleIdentity,
        analysis: FileAnalysis,
        reference: CallReference,
        base_name: str,
        method_name: str,
    ) -> CallResolution:
        method_identity = None
        for scope in self._scope_chain(reference):
            bindings = self._bindings(
                analysis,
                base_name,
                scope_symbol_id=scope.symbol.symbol_id,
                scope_kind="callable",
                scope_name=scope.symbol.qualified_name,
            )
            if scope.symbol.kind == "method":
                arguments = tuple(
                    binding for binding in bindings if binding.kind == "argument"
                )
                blockers = tuple(
                    binding for binding in bindings if binding.kind != "argument"
                )
                if len(arguments) != 1 or blockers:
                    return CallResolution(source, reference, "unresolved", "shadowed")
                method_identity = scope
                break
            if bindings:
                return CallResolution(source, reference, "unresolved", "shadowed")
        if method_identity is None:
            return CallResolution(source, reference, "unresolved", "unknown")
        owner, _, _ = method_identity.symbol.qualified_name.rpartition(".")
        candidates = self.methods.get((source.path, owner, method_name), ())
        result = self._result(source, reference, candidates)
        if result.status == "resolved":
            return CallResolution(
                source,
                reference,
                "resolved",
                "method",
                result.targets,
            )
        return result

    def _nearest_binding(
        self,
        analysis: FileAnalysis,
        reference: CallReference,
        name: str,
    ) -> tuple[NameBinding, ...]:
        for scope in self._scope_chain(reference):
            bindings = self._bindings(
                analysis,
                name,
                scope_symbol_id=scope.symbol.symbol_id,
                scope_kind="callable",
                scope_name=scope.symbol.qualified_name,
            )
            if bindings:
                return bindings
        return self._bindings(
            analysis,
            name,
            scope_symbol_id=None,
            scope_kind="module",
            scope_name="<module>",
        )

    def _resolve_attribute(
        self,
        source: ModuleIdentity,
        analysis: FileAnalysis,
        reference: CallReference,
    ) -> CallResolution:
        parts = (reference.target or "").split(".")
        if len(parts) == 2 and parts[0] in {"self", "cls"}:
            return self._resolve_method(
                source,
                analysis,
                reference,
                parts[0],
                parts[1],
            )
        bindings = self._nearest_binding(analysis, reference, parts[0])
        if not bindings:
            return CallResolution(source, reference, "unresolved", "generic_attribute")
        if any(binding.kind != "import" for binding in bindings):
            return CallResolution(source, reference, "unresolved", "shadowed")
        return self._resolve_imported_attribute(
            source,
            reference,
            parts,
            self._matching_imports(analysis, bindings),
        )

    def resolve(
        self,
    ) -> tuple[
        tuple[CallResolution, ...],
        tuple[CallDependency, ...],
    ]:
        resolutions = []
        dependencies: dict[tuple[Path, str, str], CallDependency] = {}
        for source in self.modules:
            analysis = self.analyses_by_path.get(source.path)
            if analysis is None:
                continue
            for reference in analysis.call_references:
                if reference.kind == "dynamic":
                    resolution = CallResolution(source, reference, "dynamic", "dynamic")
                elif reference.kind == "name":
                    resolution = self._resolve_name(source, analysis, reference)
                else:
                    resolution = self._resolve_attribute(source, analysis, reference)
                resolutions.append(resolution)
                if resolution.status != "resolved":
                    continue
                target = resolution.targets[0]
                caller = self.callables_by_id.get(reference.caller_symbol_id or "")
                source_key = caller.symbol.symbol_id if caller else "<module>"
                key = (source.path, source_key, target.symbol.symbol_id)
                dependencies.setdefault(
                    key,
                    CallDependency(
                        source_module=source,
                        source_callable=caller,
                        target=target,
                    ),
                )
        ordered_dependencies = tuple(
            sorted(
                dependencies.values(),
                key=lambda dependency: (
                    dependency.source_module.dotted_name,
                    dependency.source_callable.symbol.qualified_name
                    if dependency.source_callable
                    else "<module>",
                    _identity_key(dependency.target),
                ),
            )
        )
        return tuple(resolutions), ordered_dependencies


def resolve_project_calls(
    module_identities: Iterable[ModuleIdentity],
    file_analyses: Iterable[FileAnalysis],
) -> tuple[
    tuple[CallableIdentity, ...],
    tuple[CallResolution, ...],
    tuple[CallDependency, ...],
]:
    """Resolve only calls supported with high confidence by static models."""
    resolver = _CallResolver(tuple(module_identities), tuple(file_analyses))
    resolutions, dependencies = resolver.resolve()
    return resolver.callable_identities, resolutions, dependencies
