"""Conservative, on-demand AST control-flow construction."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pysynoptic.models import CallableFlowGraph, CallableSymbol, FlowEdge, FlowNode
from pysynoptic.models.flow import FlowEdgeKind, FlowNodeKind

_MAX_LABEL_LENGTH = 48


def _source(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except ValueError:
        return node.__class__.__name__


def _shorten(text: str) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= _MAX_LABEL_LENGTH:
        return normalized
    return f"{normalized[: _MAX_LABEL_LENGTH - 1]}…"


def _call_label(call: ast.Call) -> str:
    return _shorten(f"{_source(call.func)}()")


@dataclass(frozen=True, slots=True)
class _Continuation:
    node_id: str
    kind: FlowEdgeKind = "next"
    label: str = "next"


@dataclass(frozen=True, slots=True)
class _LoopTargets:
    break_id: str
    continue_id: str


class _FunctionFlowBuilder:
    def __init__(self, path: Path, symbol: CallableSymbol) -> None:
        self.path = path
        self.symbol = symbol
        self.nodes: list[FlowNode] = []
        self.edges: set[FlowEdge] = set()
        self._counter = 0
        self._exit_id = ""

    def _add_node(
        self,
        label: str,
        kind: FlowNodeKind,
        node: ast.AST,
        *,
        detail: str | None = None,
    ) -> str:
        self._counter += 1
        node_id = f"{self.symbol.symbol_id}:flow:{self._counter}"
        self.nodes.append(
            FlowNode(
                node_id=node_id,
                label=_shorten(label),
                kind=kind,
                line=getattr(node, "lineno", self.symbol.line),
                column=getattr(node, "col_offset", self.symbol.column),
                detail=detail or _source(node),
            )
        )
        return node_id

    def _edge(
        self,
        source_id: str,
        target_id: str,
        kind: FlowEdgeKind = "next",
        label: str | None = None,
    ) -> None:
        self.edges.add(FlowEdge(source_id, target_id, kind, label or kind))

    def _connect(self, source_id: str, continuation: _Continuation) -> None:
        self._edge(
            source_id,
            continuation.node_id,
            continuation.kind,
            continuation.label,
        )

    def build(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> CallableFlowGraph:
        self._exit_id = self._add_node("EXIT", "exit", node, detail="Function exit")
        body_entry = self._build_block(node.body, _Continuation(self._exit_id))
        entry_id = self._add_node(
            f"START {self.symbol.name}()",
            "entry",
            node,
            detail=self.symbol.qualified_name,
        )
        self._edge(entry_id, body_entry)
        return CallableFlowGraph(
            symbol_id=self.symbol.symbol_id,
            path=self.path,
            name=self.symbol.name,
            qualified_name=self.symbol.qualified_name,
            line=self.symbol.line,
            nodes=tuple(self.nodes),
            edges=tuple(
                sorted(
                    self.edges,
                    key=lambda edge: (
                        edge.source_id,
                        edge.target_id,
                        edge.kind,
                        edge.label,
                    ),
                )
            ),
        )

    def _build_block(
        self,
        statements: Iterable[ast.stmt],
        continuation: _Continuation,
        loop: _LoopTargets | None = None,
    ) -> str:
        groups = self._statement_groups(tuple(statements))
        entry = continuation.node_id
        next_step = continuation
        for group in reversed(groups):
            if len(group) > 1:
                entry = self._build_repeated_calls(group, next_step)
            else:
                entry = self._build_statement(group[0], next_step, loop)
            next_step = _Continuation(entry)
        return entry

    @staticmethod
    def _repeated_call_key(statement: ast.stmt) -> str | None:
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            function = statement.value.func
            if isinstance(function, ast.Attribute) and function.attr in {
                "append",
                "extend",
            }:
                return f"{_source(function.value)}.__output__"
            return _source(function)
        return None

    def _statement_groups(
        self, statements: tuple[ast.stmt, ...]
    ) -> tuple[tuple[ast.stmt, ...], ...]:
        groups: list[tuple[ast.stmt, ...]] = []
        current: list[ast.stmt] = []
        current_key: str | None = None
        for statement in statements:
            key = self._repeated_call_key(statement)
            if key is not None and key == current_key:
                current.append(statement)
                continue
            if current:
                groups.append(tuple(current))
            current = [statement]
            current_key = key
        if current:
            groups.append(tuple(current))
        return tuple(groups)

    def _build_repeated_calls(
        self,
        statements: tuple[ast.stmt, ...],
        continuation: _Continuation,
    ) -> str:
        first = statements[0]
        assert isinstance(first, ast.Expr)
        assert isinstance(first.value, ast.Call)
        target = _source(first.value.func)
        count = len(statements)
        functions = tuple(
            statement.value.func
            for statement in statements
            if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
        )
        collection_receiver = (
            _source(functions[0].value)
            if functions
            and isinstance(functions[0], ast.Attribute)
            and all(
                isinstance(function, ast.Attribute)
                and function.attr in {"append", "extend"}
                and _source(function.value) == _source(functions[0].value)
                for function in functions
            )
            else None
        )
        if collection_receiver is not None:
            label = f"Build {collection_receiver} output ({count} steps)"
        elif target == "print":
            label = f"Print {count} messages"
        elif target.endswith(".add_argument"):
            label = f"Add {count} arguments"
        else:
            label = f"{target}() × {count}"
        node_id = self._add_node(
            label,
            "call",
            first,
            detail="\n".join(_source(statement) for statement in statements),
        )
        self._connect(node_id, continuation)
        return node_id

    def _build_statement(
        self,
        statement: ast.stmt,
        continuation: _Continuation,
        loop: _LoopTargets | None,
    ) -> str:
        if isinstance(statement, ast.If):
            node_id = self._add_node(f"if {_source(statement.test)}", "if", statement)
            true_entry = self._build_block(statement.body, continuation, loop)
            false_entry = self._build_block(statement.orelse, continuation, loop)
            self._edge(node_id, true_entry, "true")
            self._edge(node_id, false_entry, "false")
            return node_id

        if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
            label = (
                f"while {_source(statement.test)}"
                if isinstance(statement, ast.While)
                else f"for {_source(statement.target)} in {_source(statement.iter)}"
            )
            node_id = self._add_node(label, "loop", statement)
            after_loop = self._build_block(statement.orelse, continuation, loop)
            body_entry = self._build_block(
                statement.body,
                _Continuation(node_id, "loop", "loop"),
                _LoopTargets(after_loop, node_id),
            )
            self._edge(node_id, body_entry, "next", "next item")
            if not statement.orelse and continuation.kind != "next":
                self._edge(
                    node_id,
                    after_loop,
                    continuation.kind,
                    continuation.label,
                )
            else:
                self._edge(node_id, after_loop, "exit-loop", "done")
            return node_id

        if isinstance(statement, (ast.Try, ast.TryStar)):
            node_id = self._add_node("try", "try", statement)
            if statement.finalbody:
                final_body = self._build_block(statement.finalbody, continuation, loop)
                final_id = self._add_node("finally", "finally", statement)
                self._edge(final_id, final_body, "finally")
                normal_continuation = _Continuation(final_id, "finally", "finally")
            else:
                normal_continuation = continuation
            else_entry = self._build_block(statement.orelse, normal_continuation, loop)
            body_entry = self._build_block(
                statement.body, _Continuation(else_entry), loop
            )
            self._edge(node_id, body_entry, "next", "try")
            for handler in statement.handlers:
                exception_name = _source(handler.type) if handler.type else "Exception"
                handler_id = self._add_node(
                    f"except {exception_name}", "except", handler
                )
                handler_entry = self._build_block(
                    handler.body, normal_continuation, loop
                )
                self._edge(node_id, handler_id, "except")
                self._edge(handler_id, handler_entry, "next", "handle")
            return node_id

        if isinstance(statement, (ast.With, ast.AsyncWith)):
            node_id = self._add_node(
                _source(statement).partition(":")[0], "statement", statement
            )
            body_entry = self._build_block(statement.body, continuation, loop)
            self._edge(node_id, body_entry, "next", "body")
            return node_id

        if isinstance(statement, ast.Match):
            node_id = self._add_node(
                f"match {_source(statement.subject)}", "if", statement
            )
            for case in statement.cases:
                case_entry = self._build_block(case.body, continuation, loop)
                self._edge(
                    node_id,
                    case_entry,
                    "true",
                    f"case {_shorten(_source(case.pattern))}",
                )
            return node_id

        if isinstance(statement, ast.Return):
            label = (
                "return"
                if statement.value is None
                else f"return {_source(statement.value)}"
            )
            node_id = self._add_node(label, "return", statement)
            self._edge(node_id, self._exit_id, "return")
            return node_id

        if isinstance(statement, ast.Raise):
            label = (
                "raise" if statement.exc is None else f"raise {_source(statement.exc)}"
            )
            node_id = self._add_node(label, "raise", statement)
            self._edge(node_id, self._exit_id, "return", "raise")
            return node_id

        if isinstance(statement, ast.Break) and loop is not None:
            node_id = self._add_node("break", "break", statement)
            self._edge(node_id, loop.break_id, "break")
            return node_id

        if isinstance(statement, ast.Continue) and loop is not None:
            node_id = self._add_node("continue", "continue", statement)
            self._edge(node_id, loop.continue_id, "continue")
            return node_id

        label, kind = self._statement_label(statement)
        node_id = self._add_node(label, kind, statement)
        self._connect(node_id, continuation)
        return node_id

    @staticmethod
    def _statement_label(statement: ast.stmt) -> tuple[str, FlowNodeKind]:
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            return _call_label(statement.value), "call"
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            value = statement.value
            target = (
                ", ".join(_source(item) for item in statement.targets)
                if isinstance(statement, ast.Assign)
                else _source(statement.target)
            )
            if isinstance(value, ast.Call):
                return f"{target} = {_call_label(value)}", "call"
            if isinstance(value, (ast.List, ast.Set, ast.Tuple)) and not value.elts:
                return f"Initialize {target}", "statement"
            if isinstance(value, ast.Dict):
                return f"Build {target} mapping", "statement"
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return f"define {statement.name}()", "statement"
        if isinstance(statement, ast.ClassDef):
            return f"define class {statement.name}", "statement"
        return _source(statement), "statement"


def _find_callable_node(
    tree: ast.Module, symbol: CallableSymbol
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    return next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.lineno == symbol.line
            and node.col_offset == symbol.column
            and node.name == symbol.name
        ),
        None,
    )


def analyze_callable_flow(path: Path, symbol: CallableSymbol) -> CallableFlowGraph:
    """Build one callable CFG from source without importing or executing it."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    node = _find_callable_node(tree, symbol)
    if node is None:
        raise ValueError(f"Callable source not found: {symbol.qualified_name}")
    return _FunctionFlowBuilder(path, symbol).build(node)
