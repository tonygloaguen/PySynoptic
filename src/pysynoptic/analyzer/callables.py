"""AST collection of callable identities and unresolved call references."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from pysynoptic.models.symbols import (
    BindingKind,
    CallableSymbol,
    CallKind,
    CallReference,
    NameBinding,
)

_ScopeKind: TypeAlias = Literal["callable", "class", "module"]


@dataclass(frozen=True, slots=True)
class _Scope:
    kind: _ScopeKind
    qualified_name: str
    symbol_id: str | None = None


def _symbol_id(path: Path, qualified_name: str, line: int, column: int) -> str:
    return f"{path.as_posix()}::{qualified_name}@{line}:{column}"


def _static_call_target(node: ast.expr) -> tuple[str | None, CallKind]:
    if isinstance(node, ast.Name):
        return node.id, "name"
    if not isinstance(node, ast.Attribute):
        return None, "dynamic"

    parts = [node.attr]
    value = node.value
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if not isinstance(value, ast.Name):
        return None, "dynamic"
    parts.append(value.id)
    return ".".join(reversed(parts)), "attribute"


class _CallableVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.scopes = [_Scope("module", "<module>")]
        self.symbols: list[CallableSymbol] = []
        self.calls: list[CallReference] = []
        self.bindings: list[NameBinding] = []

    @property
    def scope(self) -> _Scope:
        return self.scopes[-1]

    def _qualified_definition_name(self, name: str) -> str:
        scope = self.scope
        if scope.kind == "module":
            return name
        separator = ".<locals>." if scope.kind == "callable" else "."
        return f"{scope.qualified_name}{separator}{name}"

    def _enclosing_callable_id(self) -> str | None:
        return next(
            (
                scope.symbol_id
                for scope in reversed(self.scopes)
                if scope.kind == "callable"
            ),
            None,
        )

    def _add_binding(
        self,
        name: str,
        kind: BindingKind,
        node: ast.AST,
    ) -> None:
        self.bindings.append(
            NameBinding(
                path=self.path,
                name=name,
                kind=kind,
                line=node.lineno,
                column=node.col_offset,
                scope_kind=self.scope.kind,
                scope_name=self.scope.qualified_name,
                scope_symbol_id=self.scope.symbol_id,
            )
        )

    @staticmethod
    def _bound_names(node: ast.expr) -> tuple[str, ...]:
        if isinstance(node, ast.Name):
            return (node.id,)
        if isinstance(node, (ast.List, ast.Tuple)):
            return tuple(
                name
                for element in node.elts
                for name in _CallableVisitor._bound_names(element)
            )
        if isinstance(node, ast.Starred):
            return _CallableVisitor._bound_names(node.value)
        return ()

    def _visit_type_parameters(self, node: ast.AST) -> None:
        for type_parameter in getattr(node, "type_params", ()):  # Python 3.12+
            self.visit(type_parameter)

    def _visit_arguments(self, arguments: ast.arguments) -> None:
        positional = (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
        for argument in positional:
            if argument.annotation is not None:
                self.visit(argument.annotation)
        for argument in (arguments.vararg, arguments.kwarg):
            if argument is not None and argument.annotation is not None:
                self.visit(argument.annotation)
        for default in arguments.defaults:
            self.visit(default)
        for default in arguments.kw_defaults:
            if default is not None:
                self.visit(default)

    def _add_argument_bindings(self, arguments: ast.arguments) -> None:
        positional = (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
        for argument in positional:
            self._add_binding(argument.arg, "argument", argument)
        for argument in (arguments.vararg, arguments.kwarg):
            if argument is not None:
                self._add_binding(argument.arg, "argument", argument)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualified_name = self._qualified_definition_name(node.name)
        symbol_id = _symbol_id(
            self.path,
            qualified_name,
            node.lineno,
            node.col_offset,
        )
        symbol = CallableSymbol(
            symbol_id=symbol_id,
            path=self.path,
            name=node.name,
            qualified_name=qualified_name,
            kind="method" if self.scope.kind == "class" else "function",
            is_async=isinstance(node, ast.AsyncFunctionDef),
            line=node.lineno,
            column=node.col_offset,
            parent_symbol_id=self._enclosing_callable_id(),
        )
        self.symbols.append(symbol)

        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_arguments(node.args)
        if node.returns is not None:
            self.visit(node.returns)
        self._visit_type_parameters(node)

        self.scopes.append(_Scope("callable", qualified_name, symbol_id))
        self._add_argument_bindings(node.args)
        for statement in node.body:
            self.visit(statement)
        self.scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualified_name = self._qualified_definition_name(node.name)
        self._add_binding(node.name, "class", node)
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        self._visit_type_parameters(node)

        self.scopes.append(_Scope("class", qualified_name))
        for statement in node.body:
            self.visit(statement)
        self.scopes.pop()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname or alias.name.partition(".")[0]
            self._add_binding(name, "import", node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name != "*":
                self._add_binding(alias.asname or alias.name, "import", node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            for name in self._bound_names(target):
                self._add_binding(name, "assignment", target)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        for name in self._bound_names(node.target):
            self._add_binding(name, "assignment", node.target)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        for name in self._bound_names(node.target):
            self._add_binding(name, "assignment", node.target)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        for name in self._bound_names(node.target):
            self._add_binding(name, "assignment", node.target)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        for name in self._bound_names(node.target):
            self._add_binding(name, "assignment", node.target)
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        for name in self._bound_names(node.target):
            self._add_binding(name, "assignment", node.target)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        target, kind = _static_call_target(node.func)
        self.calls.append(
            CallReference(
                path=self.path,
                expression=ast.unparse(node.func),
                target=target,
                kind=kind,
                line=node.lineno,
                column=node.col_offset,
                scope_kind=self.scope.kind,
                scope_name=self.scope.qualified_name,
                caller_symbol_id=self._enclosing_callable_id(),
            )
        )
        self.generic_visit(node)


def analyze_callables(
    tree: ast.Module,
    path: Path,
) -> tuple[
    tuple[CallableSymbol, ...],
    tuple[CallReference, ...],
    tuple[NameBinding, ...],
]:
    """Collect stable callable symbols and unresolved calls from an AST."""
    visitor = _CallableVisitor(path)
    visitor.visit(tree)
    symbols = tuple(
        sorted(
            visitor.symbols,
            key=lambda symbol: (
                symbol.line,
                symbol.column,
                symbol.qualified_name,
                symbol.symbol_id,
            ),
        )
    )
    calls = tuple(
        sorted(
            visitor.calls,
            key=lambda call: (
                call.line,
                call.column,
                call.kind,
                call.expression,
                call.scope_name,
            ),
        )
    )
    bindings = tuple(
        sorted(
            visitor.bindings,
            key=lambda binding: (
                binding.line,
                binding.column,
                binding.scope_name,
                binding.name,
                binding.kind,
            ),
        )
    )
    return symbols, calls, bindings
