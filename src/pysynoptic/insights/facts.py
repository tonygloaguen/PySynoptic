"""Deterministic extraction of objective static facts from analyzed source."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from pysynoptic.insights.models import (
    ArgumentKind,
    CallableFacts,
    ClassFacts,
    ModuleFacts,
    OperationCategory,
    ParameterFacts,
    StaticOperation,
)
from pysynoptic.models import (
    FileAnalysis,
    ImportReference,
    ModuleIdentity,
    ProjectAnalysis,
)

_IO_METHODS = {
    "mkdir",
    "read_bytes",
    "read_text",
    "unlink",
    "write_bytes",
    "write_text",
}
_PATH_SENSITIVE_IO_METHODS = {"rename", "replace"}
_NETWORK_ROOTS = {"aiohttp", "http", "httpx", "requests", "socket", "urllib"}
_ImportKey = tuple[int, int, str, str | None, str | None, str | None]


def _source(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except ValueError:
        return node.__class__.__name__


def _docstring(
    node: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
):
    value = ast.get_docstring(node, clean=True)
    summary = next(
        (line.strip() for line in (value or "").splitlines() if line.strip()), None
    )
    return value, summary


def _is_docstring_statement(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def _bound_names(node: ast.expr) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, (ast.List, ast.Tuple)):
        return tuple(name for item in node.elts for name in _bound_names(item))
    if isinstance(node, ast.Starred):
        return _bound_names(node.value)
    return ()


def _pattern_bound_names(pattern: ast.pattern) -> tuple[str, ...]:
    names: set[str] = set()
    for node in ast.walk(pattern):
        if isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            names.add(node.rest)
    return tuple(sorted(names))


def _attribute_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if not isinstance(node, ast.Attribute):
        return None
    prefix = _attribute_name(node.value)
    return f"{prefix}.{node.attr}" if prefix else None


def _reference_key(reference: ImportReference) -> _ImportKey:
    return (
        reference.line,
        reference.column,
        reference.kind,
        reference.module,
        reference.imported_name,
        reference.alias,
    )


def _ast_import_key(
    node: ast.Import | ast.ImportFrom,
    item: ast.alias,
) -> _ImportKey:
    return (
        node.lineno,
        node.col_offset,
        "import" if isinstance(node, ast.Import) else "from",
        item.name if isinstance(node, ast.Import) else node.module,
        None if isinstance(node, ast.Import) else item.name,
        item.asname,
    )


class _ScopeAliasVisitor(ast.NodeVisitor):
    def __init__(
        self,
        aliases: dict[str, str],
        trusted_imports: frozenset[_ImportKey],
        blocked_names: set[str],
    ) -> None:
        self.aliases = dict(aliases)
        self.trusted_imports = trusted_imports
        self.blocked_names = set(blocked_names)
        self.local_imports: dict[str, str] = {}
        for name in self.blocked_names:
            self.aliases.pop(name, None)

    def _block(self, names: tuple[str, ...]) -> None:
        self.blocked_names.update(names)
        for name in names:
            self.aliases.pop(name, None)

    def _import(self, local_name: str, target: str, trusted: bool) -> None:
        if local_name in self.blocked_names:
            return
        previous = self.local_imports.get(local_name)
        if not trusted or previous is not None and previous != target:
            self._block((local_name,))
            return
        self.local_imports[local_name] = target
        self.aliases[local_name] = target

    def visit_Import(self, node: ast.Import) -> None:
        for item in node.names:
            local_name = item.asname or item.name.partition(".")[0]
            target = item.name if item.asname else local_name
            self._import(
                local_name,
                target,
                _ast_import_key(node, item) in self.trusted_imports,
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if not node.module:
            return
        for item in node.names:
            if item.name == "*":
                self._block(tuple(self.aliases))
                continue
            local_name = item.asname or item.name
            self._import(
                local_name,
                f"{node.module}.{item.name}",
                _ast_import_key(node, item) in self.trusted_imports,
            )

    def visit_Assign(self, node: ast.Assign) -> None:
        self._block(
            tuple(name for target in node.targets for name in _bound_names(target))
        )
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._block(_bound_names(node.target))
        if node.value is not None:
            self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._block(_bound_names(node.target))
        self.visit(node.value)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._block(_bound_names(node.target))
        self.visit(node.value)

    def visit_For(self, node: ast.For) -> None:
        self._block(_bound_names(node.target))
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._block(_bound_names(node.target))
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self._block(_bound_names(node.target))
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        for case in node.cases:
            self._block(_pattern_bound_names(case.pattern))
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self._block(_bound_names(item.optional_vars))
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.visit_With(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self._block((node.name,))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._block((node.name,))
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._block((node.name,))
        return None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._block((node.name,))
        return None

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return None


def _scoped_aliases(
    statements: tuple[ast.stmt, ...],
    aliases: dict[str, str],
    trusted_imports: frozenset[_ImportKey],
    arguments: ast.arguments | None,
    inherited_blocked: set[str] | None = None,
) -> tuple[dict[str, str], set[str]]:
    blocked_names = (
        {
            argument.arg
            for argument in (
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
                *((arguments.vararg,) if arguments.vararg else ()),
                *((arguments.kwarg,) if arguments.kwarg else ()),
            )
        }
        if arguments is not None
        else set()
    )
    blocked_names.update(inherited_blocked or ())
    visitor = _ScopeAliasVisitor(aliases, trusted_imports, blocked_names)
    for statement in statements:
        visitor.visit(statement)
    return visitor.aliases, visitor.blocked_names


def _normalized_name(name: str | None, aliases: dict[str, str]) -> str | None:
    if not name:
        return None
    root, separator, remainder = name.partition(".")
    normalized_root = aliases.get(root, root)
    return f"{normalized_root}.{remainder}" if separator else normalized_root


def _trusted_name(node: ast.AST, aliases: dict[str, str]) -> str | None:
    name = _attribute_name(node)
    if not name or name.partition(".")[0] not in aliases:
        return None
    return _normalized_name(name, aliases)


def _call_name(node: ast.expr, aliases: dict[str, str]) -> str | None:
    direct = _trusted_name(node, aliases)
    if direct is not None:
        return direct
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Call):
        receiver = _call_name(node.value.func, aliases)
        if receiver == "pathlib.Path":
            return f"pathlib.Path.{node.attr}"
    return None


def _is_path_annotation(annotation: ast.expr | None, aliases: dict[str, str]) -> bool:
    return (
        annotation is not None and _trusted_name(annotation, aliases) == "pathlib.Path"
    )


class _PathBindingVisitor(ast.NodeVisitor):
    def __init__(self, aliases: dict[str, str]) -> None:
        self.aliases = aliases
        self.names: set[str] = set()
        self.blocked_names: set[str] = set()

    def _is_path_constructor(self, node: ast.expr | None) -> bool:
        return (
            isinstance(node, ast.Call)
            and _call_name(node.func, self.aliases) == "pathlib.Path"
        )

    def _record_assignment(self, target: ast.expr, is_path: bool) -> None:
        names = set(_bound_names(target))
        if is_path:
            self.names.update(names)
        else:
            self.blocked_names.update(names)

    def visit_Assign(self, node: ast.Assign) -> None:
        is_path = self._is_path_constructor(node.value)
        for target in node.targets:
            self._record_assignment(target, is_path)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._record_assignment(
            node.target,
            _is_path_annotation(node.annotation, self.aliases)
            or self._is_path_constructor(node.value),
        )
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.blocked_names.update(_bound_names(node.target))
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._record_assignment(node.target, self._is_path_constructor(node.value))
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.blocked_names.update(_bound_names(node.target))
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.blocked_names.update(_bound_names(node.target))
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self.blocked_names.update(_bound_names(node.target))
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        for case in node.cases:
            self.blocked_names.update(_pattern_bound_names(case.pattern))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return None

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return None


def _path_like_names(
    statements: tuple[ast.stmt, ...],
    aliases: dict[str, str],
    arguments: ast.arguments | None = None,
) -> set[str]:
    if arguments is None:
        declared_arguments: tuple[ast.arg, ...] = ()
    else:
        declared_arguments = (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
            *((arguments.vararg,) if arguments.vararg else ()),
            *((arguments.kwarg,) if arguments.kwarg else ()),
        )
    names = {
        argument.arg
        for argument in declared_arguments
        if _is_path_annotation(argument.annotation, aliases)
    }
    visitor = _PathBindingVisitor(aliases)
    for statement in statements:
        visitor.visit(statement)
    names.update(visitor.names)
    names.difference_update(visitor.blocked_names)
    return names


def _exception_names(node: ast.expr | None) -> tuple[str, ...]:
    if node is None:
        return ()
    if isinstance(node, ast.Tuple):
        return tuple(name for item in node.elts for name in _exception_names(item))
    if isinstance(node, ast.Call):
        return _exception_names(node.func)
    name = _attribute_name(node)
    return (name,) if name else ()


def _operation_key(operation: StaticOperation) -> tuple[int, int, str, str, str]:
    return (
        operation.line,
        operation.column,
        operation.category,
        operation.operation,
        operation.expression,
    )


class _ScopedFactVisitor(ast.NodeVisitor):
    def __init__(
        self,
        aliases: dict[str, str],
        blocked_names: set[str],
        path_names: set[str],
        ignored_docstring: ast.stmt | None,
    ) -> None:
        self.aliases = aliases
        self.blocked_names = blocked_names
        self.path_names = path_names
        self.ignored_docstring = ignored_docstring
        self.statement_count = 0
        self.branch_count = 0
        self.loop_count = 0
        self.try_block_count = 0
        self.except_handler_count = 0
        self.returns: list[ast.Return] = []
        self.raises: list[ast.Raise] = []
        self.raised_exceptions: set[str] = set()
        self.caught_exceptions: set[str] = set()
        self.operations: set[StaticOperation] = set()

    def visit(self, node: ast.AST):
        if isinstance(node, ast.stmt) and node is not self.ignored_docstring:
            self.statement_count += 1
        return super().visit(node)

    def _record(
        self,
        category: OperationCategory,
        operation: str,
        node: ast.AST,
    ) -> None:
        self.operations.add(
            StaticOperation(
                category=category,
                operation=operation,
                expression=_source(node) or node.__class__.__name__,
                line=getattr(node, "lineno", 0),
                column=getattr(node, "col_offset", 0),
            )
        )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return None

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return None

    def visit_If(self, node: ast.If) -> None:
        self.branch_count += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.branch_count += 1
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        self.branch_count += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.loop_count += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.loop_count += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.loop_count += 1
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        self.try_block_count += 1
        self.generic_visit(node)

    def visit_TryStar(self, node: ast.TryStar) -> None:
        self.try_block_count += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.except_handler_count += 1
        self.caught_exceptions.update(_exception_names(node.type))
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        self.returns.append(node)
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        self.raises.append(node)
        self.raised_exceptions.update(_exception_names(node.exc))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        name = _trusted_name(node, self.aliases)
        if name == "os.environ":
            self._record("environment", "os.environ", node)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if _trusted_name(node, self.aliases) == "os.environ":
            self._record("environment", "os.environ", node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func, self.aliases)
        observed_name = _attribute_name(node.func)
        tail = (name or observed_name or "").rpartition(".")[2]
        receiver = node.func.value if isinstance(node.func, ast.Attribute) else None
        receiver_name = _attribute_name(receiver) if receiver is not None else None
        path_receiver = (
            receiver_name in self.path_names
            or name is not None
            and name.startswith("pathlib.Path.")
        )

        if (
            observed_name == "open" and "open" not in self.blocked_names
        ) or name == "builtins.open":
            self._record("io", "open", node)
        elif tail in (_IO_METHODS | _PATH_SENSITIVE_IO_METHODS) and path_receiver:
            self._record("io", tail, node)

        root = name.partition(".")[0] if name else ""
        if root == "subprocess":
            self._record("process", name or "subprocess", node)
        if (
            name in {"os.getenv", "os.putenv", "os.unsetenv"}
            or name == "os.environ.get"
        ):
            self._record("environment", name, node)
        if root in _NETWORK_ROOTS:
            self._record("network", name or root, node)
        if root == "logging":
            self._record("logging", name or "logging", node)
        self.generic_visit(node)


def _scoped_facts(
    statements: tuple[ast.stmt, ...],
    aliases: dict[str, str],
    trusted_imports: frozenset[_ImportKey],
    *,
    arguments: ast.arguments | None = None,
    inherited_blocked: set[str] | None = None,
) -> _ScopedFactVisitor:
    aliases, blocked_names = _scoped_aliases(
        statements,
        aliases,
        trusted_imports,
        arguments,
        inherited_blocked,
    )
    ignored_docstring = (
        statements[0] if statements and _is_docstring_statement(statements[0]) else None
    )
    visitor = _ScopedFactVisitor(
        aliases,
        blocked_names,
        _path_like_names(statements, aliases, arguments),
        ignored_docstring,
    )
    for statement in statements:
        visitor.visit(statement)
    return visitor


def _operations(
    visitor: _ScopedFactVisitor, category: OperationCategory
) -> tuple[StaticOperation, ...]:
    return tuple(
        sorted(
            (item for item in visitor.operations if item.category == category),
            key=_operation_key,
        )
    )


def _parameters(
    arguments: ast.arguments,
) -> tuple[
    tuple[ParameterFacts, ...],
    tuple[ParameterFacts, ...],
    tuple[ParameterFacts, ...],
    ParameterFacts | None,
    ParameterFacts | None,
]:
    positional = (*arguments.posonlyargs, *arguments.args)
    defaults: dict[int, ast.expr] = {}
    if arguments.defaults:
        for argument, default in zip(
            positional[-len(arguments.defaults) :], arguments.defaults, strict=True
        ):
            defaults[id(argument)] = default

    def parameter(
        argument: ast.arg,
        kind: ArgumentKind,
        default: ast.expr | None = None,
    ) -> ParameterFacts:
        return ParameterFacts(
            name=argument.arg,
            kind=kind,
            annotation=_source(argument.annotation),
            default=_source(default),
        )

    positional_only = tuple(
        parameter(item, "positional_only", defaults.get(id(item)))
        for item in arguments.posonlyargs
    )
    regular = tuple(
        parameter(item, "positional", defaults.get(id(item))) for item in arguments.args
    )
    keyword_only = tuple(
        parameter(item, "keyword_only", default)
        for item, default in zip(
            arguments.kwonlyargs, arguments.kw_defaults, strict=True
        )
    )
    vararg = parameter(arguments.vararg, "vararg") if arguments.vararg else None
    varkw = parameter(arguments.kwarg, "varkw") if arguments.kwarg else None
    return positional_only, regular, keyword_only, vararg, varkw


@dataclass(frozen=True, slots=True)
class _ClassNode:
    qualified_name: str
    node: ast.ClassDef


@dataclass(frozen=True, slots=True)
class _DefinitionScope:
    kind: str
    qualified_name: str


class _ClassCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scopes = [_DefinitionScope("module", "<module>")]
        self.classes: list[_ClassNode] = []

    def _qualified_name(self, name: str) -> str:
        scope = self.scopes[-1]
        if scope.kind == "module":
            return name
        separator = ".<locals>." if scope.kind == "callable" else "."
        return f"{scope.qualified_name}{separator}{name}"

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualified_name = self._qualified_name(node.name)
        self.scopes.append(_DefinitionScope("callable", qualified_name))
        for statement in node.body:
            self.visit(statement)
        self.scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualified_name = self._qualified_name(node.name)
        self.classes.append(_ClassNode(qualified_name, node))
        self.scopes.append(_DefinitionScope("class", qualified_name))
        for statement in node.body:
            self.visit(statement)
        self.scopes.pop()


def _class_variables(node: ast.ClassDef) -> tuple[str, ...]:
    names: set[str] = set()
    for statement in node.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                names.update(_bound_names(target))
        elif isinstance(statement, ast.AnnAssign):
            names.update(_bound_names(statement.target))
    return tuple(sorted(names, key=lambda item: (item.casefold(), item)))


def _is_dataclass_decorator(decorator: ast.expr) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    name = _attribute_name(target)
    return name == "dataclass" or bool(name and name.endswith(".dataclass"))


def _class_facts(
    module: ModuleIdentity,
    tree: ast.Module,
    file_analysis: FileAnalysis,
) -> tuple[ClassFacts, ...]:
    collector = _ClassCollector()
    collector.visit(tree)
    symbols_by_location = {
        (symbol.line, symbol.column, symbol.name): symbol
        for symbol in file_analysis.callable_symbols
    }
    facts = []
    for item in collector.classes:
        node = item.node
        docstring, summary = _docstring(node)
        method_symbols = tuple(
            symbols_by_location[
                (statement.lineno, statement.col_offset, statement.name)
            ]
            for statement in node.body
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
            and (statement.lineno, statement.col_offset, statement.name)
            in symbols_by_location
        )
        facts.append(
            ClassFacts(
                module=module.dotted_name,
                path=module.path,
                name=node.name,
                qualified_name=item.qualified_name,
                source_line=node.lineno,
                has_docstring=docstring is not None,
                docstring=docstring,
                docstring_summary=summary,
                decorators=tuple(_source(value) or "" for value in node.decorator_list),
                base_classes=tuple(_source(value) or "" for value in node.bases),
                methods=tuple(symbol.qualified_name for symbol in method_symbols),
                async_methods=tuple(
                    symbol.qualified_name
                    for symbol in method_symbols
                    if symbol.is_async
                ),
                class_variables=_class_variables(node),
                is_dataclass=any(
                    _is_dataclass_decorator(value) for value in node.decorator_list
                ),
                method_count=len(method_symbols),
            )
        )
    return tuple(
        sorted(
            facts,
            key=lambda item: (item.source_line, item.qualified_name, item.name),
        )
    )


def _callable_facts(
    analysis: ProjectAnalysis,
    module: ModuleIdentity,
    tree: ast.Module,
    file_analysis: FileAnalysis,
    aliases: dict[str, str],
    module_blocked_names: set[str],
    trusted_imports: frozenset[_ImportKey],
) -> tuple[CallableFacts, ...]:
    nodes_by_location = {
        (node.lineno, node.col_offset, node.name): node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    facts = []
    scoped_aliases_by_symbol: dict[str, dict[str, str]] = {}
    blocked_names_by_symbol: dict[str, set[str]] = {}
    for symbol in file_analysis.callable_symbols:
        node = nodes_by_location[(symbol.line, symbol.column, symbol.name)]
        base_aliases = scoped_aliases_by_symbol.get(
            symbol.parent_symbol_id or "",
            aliases,
        )
        inherited_blocked = blocked_names_by_symbol.get(
            symbol.parent_symbol_id or "",
            module_blocked_names,
        )
        scoped = _scoped_facts(
            tuple(node.body),
            base_aliases,
            trusted_imports,
            arguments=node.args,
            inherited_blocked=inherited_blocked,
        )
        scoped_aliases_by_symbol[symbol.symbol_id] = scoped.aliases
        blocked_names_by_symbol[symbol.symbol_id] = scoped.blocked_names
        docstring, summary = _docstring(node)
        positional_only, arguments, keyword_only, vararg, varkw = _parameters(node.args)
        resolutions = tuple(
            resolution
            for resolution in analysis.call_resolutions
            if resolution.reference.caller_symbol_id == symbol.symbol_id
        )
        callees = tuple(
            sorted(
                {
                    target.qualified_name
                    for resolution in resolutions
                    if resolution.status == "resolved"
                    for target in resolution.targets
                },
                key=lambda item: (item.casefold(), item),
            )
        )
        callers = tuple(
            sorted(
                {
                    dependency.source_callable.qualified_name
                    if dependency.source_callable
                    else f"{dependency.source_module.dotted_name}::<module>"
                    for dependency in analysis.call_dependencies
                    if dependency.target.symbol.symbol_id == symbol.symbol_id
                },
                key=lambda item: (item.casefold(), item),
            )
        )
        returns_value = any(
            item.value is not None
            and not (isinstance(item.value, ast.Constant) and item.value.value is None)
            for item in scoped.returns
        )
        returns_none = any(
            isinstance(item.value, ast.Constant) and item.value.value is None
            for item in scoped.returns
        )
        facts.append(
            CallableFacts(
                module=module.dotted_name,
                path=module.path,
                symbol_id=symbol.symbol_id,
                name=symbol.name,
                qualified_name=symbol.qualified_name,
                display_name=f"{symbol.name}()",
                kind=symbol.kind,
                is_async=symbol.is_async,
                source_line=symbol.line,
                positional_only_args=positional_only,
                arguments=arguments,
                keyword_only_args=keyword_only,
                vararg=vararg,
                varkw=varkw,
                return_annotation=_source(node.returns),
                decorators=tuple(_source(value) or "" for value in node.decorator_list),
                has_docstring=docstring is not None,
                docstring=docstring,
                docstring_summary=summary,
                statement_count=scoped.statement_count,
                branch_count=scoped.branch_count,
                loop_count=scoped.loop_count,
                try_block_count=scoped.try_block_count,
                except_handler_count=scoped.except_handler_count,
                return_statement_count=len(scoped.returns),
                raise_statement_count=len(scoped.raises),
                resolved_callees=callees,
                resolved_callers=callers,
                ambiguous_call_count=sum(
                    item.status == "ambiguous" for item in resolutions
                ),
                unresolved_call_count=sum(
                    item.status == "unresolved" for item in resolutions
                ),
                dynamic_call_count=sum(
                    item.status == "dynamic" for item in resolutions
                ),
                has_explicit_return=bool(scoped.returns),
                returns_value=returns_value,
                returns_none_explicitly=returns_none,
                multiple_return_paths=len(scoped.returns) > 1,
                raised_exceptions=tuple(sorted(scoped.raised_exceptions)),
                caught_exceptions=tuple(sorted(scoped.caught_exceptions)),
                io_operations=_operations(scoped, "io"),
                process_operations=_operations(scoped, "process"),
                environment_operations=_operations(scoped, "environment"),
                network_operations=_operations(scoped, "network"),
                logging_operations=_operations(scoped, "logging"),
            )
        )
    return tuple(
        sorted(
            facts,
            key=lambda item: (item.source_line, item.qualified_name, item.symbol_id),
        )
    )


def extract_module_facts(
    analysis: ProjectAnalysis,
    module: ModuleIdentity,
) -> ModuleFacts:
    """Extract facts for one analyzed module without importing or executing it."""
    file_analysis = next(
        (item for item in analysis.file_analyses if item.path == module.path),
        None,
    )
    if file_analysis is None:
        raise ValueError(f"No file analysis for module: {module.dotted_name}")
    if file_analysis.syntax_error is not None:
        raise ValueError(f"Cannot extract facts from invalid syntax: {module.path}")

    source = module.path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module.path))
    trusted_imports = frozenset(
        _reference_key(resolution.reference)
        for resolution in analysis.import_resolutions
        if resolution.source.path == module.path and resolution.status == "external"
    )
    aliases, module_blocked_names = _scoped_aliases(
        tuple(tree.body), {}, trusted_imports, None
    )
    module_scoped = _scoped_facts(tuple(tree.body), {}, trusted_imports)
    callable_facts = _callable_facts(
        analysis,
        module,
        tree,
        file_analysis,
        aliases,
        module_blocked_names,
        trusted_imports,
    )
    class_facts = _class_facts(module, tree, file_analysis)
    docstring, summary = _docstring(tree)
    top_level_functions = tuple(
        statement.name
        for statement in tree.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    top_level_classes = tuple(
        statement.name for statement in tree.body if isinstance(statement, ast.ClassDef)
    )
    top_level_callables = tuple(
        item.qualified_name for item in callable_facts if "." not in item.qualified_name
    )
    executable_count = sum(
        not isinstance(
            statement,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
                ast.Import,
                ast.ImportFrom,
            ),
        )
        and not _is_docstring_statement(statement)
        for statement in tree.body
    )
    return ModuleFacts(
        module=module.dotted_name,
        path=module.path,
        has_docstring=docstring is not None,
        docstring=docstring,
        docstring_summary=summary,
        imports=file_analysis.imports,
        resolved_internal_dependencies=tuple(
            sorted(
                {
                    dependency.target.dotted_name
                    for dependency in analysis.dependencies
                    if dependency.source.path == module.path
                },
                key=lambda item: (item.casefold(), item),
            )
        ),
        external_import_names=tuple(
            sorted(
                {
                    resolution.absolute_name
                    for resolution in analysis.import_resolutions
                    if resolution.source.path == module.path
                    and resolution.status == "external"
                    and resolution.absolute_name
                },
                key=lambda item: (item.casefold(), item),
            )
        ),
        functions=top_level_functions,
        classes=top_level_classes,
        module_level_callables=top_level_callables,
        callable_facts=callable_facts,
        class_facts=class_facts,
        module_level_executable_statement_count=executable_count,
        module_level_calls=tuple(
            reference.expression
            for reference in file_analysis.call_references
            if reference.scope_kind == "module"
        ),
        io_operations=_operations(module_scoped, "io"),
        process_operations=_operations(module_scoped, "process"),
        environment_operations=_operations(module_scoped, "environment"),
        network_operations=_operations(module_scoped, "network"),
        logging_operations=_operations(module_scoped, "logging"),
    )


def extract_project_facts(analysis: ProjectAnalysis) -> tuple[ModuleFacts, ...]:
    """Extract deterministically ordered module facts for a project analysis."""
    return tuple(
        extract_module_facts(analysis, module)
        for module in sorted(
            analysis.module_identities,
            key=lambda item: (
                item.dotted_name.casefold(),
                item.dotted_name,
                item.path.as_posix(),
            ),
        )
    )
