"""Reconstruct structured explanations from existing callable CFGs."""

from __future__ import annotations

from collections.abc import Iterable

from pysynoptic.insights.flow_explanation.models import (
    FlowDecision,
    FlowException,
    FlowExplanation,
    FlowExplanationReliability,
    FlowLoop,
    FlowStep,
    InsightSource,
)
from pysynoptic.insights.flow_explanation.narration import _FlowNarration
from pysynoptic.models import CallableFlowGraph, FlowEdge, FlowNode

_MAX_STEPS = 18


def _node_key(node: FlowNode) -> tuple[int, int, int, str]:
    kind_order = {"entry": -2, "try": -1, "finally": 1, "exit": 2}
    return (node.line, node.column, kind_order.get(node.kind, 0), node.node_id)


def _ordered_ids(nodes: Iterable[FlowNode]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for node in sorted(nodes, key=_node_key):
        if node.node_id not in seen:
            ordered.append(node.node_id)
            seen.add(node.node_id)
    return tuple(ordered)


class _FlowExplanationBuilder:
    def __init__(self, flow: CallableFlowGraph, insights: InsightSource) -> None:
        self.flow = flow
        self.nodes = {node.node_id: node for node in flow.nodes}
        self.ordered_nodes = tuple(sorted(flow.nodes, key=_node_key))
        self.outgoing: dict[str, tuple[FlowEdge, ...]] = {}
        for node_id in self.nodes:
            self.outgoing[node_id] = tuple(
                sorted(
                    (edge for edge in flow.edges if edge.source_id == node_id),
                    key=lambda edge: (
                        edge.kind,
                        self.nodes[edge.target_id].line,
                        self.nodes[edge.target_id].column,
                        edge.target_id,
                    ),
                )
            )
        self.narration = _FlowNarration(flow, insights, self.ordered_nodes)
        self._loop_cache: dict[str, frozenset[str]] = {}
        self._decision_cache: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
        self._decisions: dict[str, FlowDecision] = {}
        self._loops: dict[str, FlowLoop] = {}
        self._exceptions: dict[str, FlowException] = {}
        self._active_structures: set[str] = set()

    def build(self) -> FlowExplanation:
        semantic_ids = {
            node.node_id
            for node in self.ordered_nodes
            if node.kind not in {"entry", "exit"}
        }
        steps = self._steps_from_ids(semantic_ids)
        outcomes = tuple(
            self.narration._outcome(node)
            for node in self.ordered_nodes
            if node.kind in {"return", "raise"}
        )
        summary = self.narration._summary(steps, outcomes)
        supporting = _ordered_ids(
            self.nodes[node_id]
            for step in steps
            for node_id in self._all_step_ids(step)
        )
        reliability = self.narration._reliability(steps, summary)
        if reliability is FlowExplanationReliability.UNKNOWN:
            summary = None
        return FlowExplanation(
            callable_identity=self.flow.symbol_id,
            summary=summary,
            steps=steps,
            decisions=tuple(
                self._decisions[node.node_id]
                for node in self.ordered_nodes
                if node.node_id in self._decisions
            ),
            loops=tuple(
                self._loops[node.node_id]
                for node in self.ordered_nodes
                if node.node_id in self._loops
            ),
            exceptions=tuple(
                self._exceptions[node.node_id]
                for node in self.ordered_nodes
                if node.node_id in self._exceptions
            ),
            outcomes=outcomes,
            reliability=reliability,
            supporting_node_ids=supporting,
        )

    @staticmethod
    def _all_step_ids(step: FlowStep) -> tuple[str, ...]:
        return step.source_node_ids + tuple(
            node_id
            for child in step.child_steps
            for node_id in _FlowExplanationBuilder._all_step_ids(child)
        )

    def _steps_from_ids(self, node_ids: Iterable[str]) -> tuple[FlowStep, ...]:
        available = set(node_ids)
        consumed: set[str] = set()
        raw: list[FlowStep] = []
        for node in self.ordered_nodes:
            if node.node_id not in available or node.node_id in consumed:
                continue
            if node.kind in {"entry", "exit", "except", "finally"}:
                consumed.add(node.node_id)
                continue
            step, owned = self._step_for_node(node, available)
            consumed.update(owned)
            if step is not None:
                raw.append(step)
        compacted = self.narration._compact_steps(tuple(raw))
        if len(compacted) > _MAX_STEPS:
            middle = compacted[8:-8]
            synthetic = FlowStep(
                order=0,
                kind="sequence",
                text="Process additional intermediate operations.",
                source_node_ids=tuple(
                    node_id for step in middle for node_id in step.source_node_ids
                ),
                child_steps=tuple(
                    child for step in middle for child in step.child_steps
                ),
            )
            compacted = compacted[:8] + (synthetic,) + compacted[-8:]
        return tuple(
            FlowStep(
                order=index,
                kind=step.kind,
                text=step.text,
                source_node_ids=step.source_node_ids,
                child_steps=step.child_steps,
            )
            for index, step in enumerate(compacted, start=1)
        )

    def _step_for_node(
        self,
        node: FlowNode,
        available: set[str],
    ) -> tuple[FlowStep | None, set[str]]:
        if (
            node.kind in {"loop", "if", "try"}
            and node.node_id in self._active_structures
        ):
            return None, {node.node_id}
        if node.kind == "loop":
            members = set(self._loop_members(node)) & available
            child_ids = members - {node.node_id}
            self._active_structures.add(node.node_id)
            try:
                children = self._steps_from_ids(child_ids)
            finally:
                self._active_structures.discard(node.node_id)
            text = self.narration._loop_text(node, children)
            loop = FlowLoop(
                header=node.label,
                body_summary=self.narration._steps_summary(children),
                body_steps=children,
                source_node_ids=_ordered_ids(self.nodes[item] for item in members),
            )
            self._loops[node.node_id] = loop
            return (
                FlowStep(0, "loop", text, (node.node_id,), children),
                members,
            )
        if node.kind == "if":
            true_ids, false_ids = self._decision_members(node)
            true_ids = set(true_ids) & available
            false_ids = set(false_ids) & available
            true_ids.discard(node.node_id)
            false_ids.discard(node.node_id)
            self._active_structures.add(node.node_id)
            try:
                true_steps = self._steps_from_ids(true_ids)
                false_steps = self._steps_from_ids(false_ids)
            finally:
                self._active_structures.discard(node.node_id)
            condition = node.label.removeprefix("if ").strip()
            text = self.narration._decision_text(condition, true_steps, false_steps)
            owned = {node.node_id} | true_ids | false_ids
            decision = FlowDecision(
                condition=condition,
                true_path=true_steps,
                false_path=false_steps,
                source_node_ids=_ordered_ids(self.nodes[item] for item in owned),
            )
            self._decisions[node.node_id] = decision
            return (
                FlowStep(
                    0,
                    "decision",
                    text,
                    (node.node_id,),
                    true_steps + false_steps,
                ),
                owned,
            )
        if node.kind == "try":
            self._active_structures.add(node.node_id)
            try:
                return self._exception_step(node, available)
            finally:
                self._active_structures.discard(node.node_id)
        if node.kind in {"return", "raise"}:
            outcome = self.narration._outcome(node)
            return (
                FlowStep(0, node.kind, outcome.text, (node.node_id,)),
                {node.node_id},
            )
        if node.kind in {"break", "continue"}:
            text = (
                "Stop processing the loop."
                if node.kind == "break"
                else "Continue with the next item."
            )
            return FlowStep(0, node.kind, text, (node.node_id,)), {node.node_id}
        text, kind = self.narration._describe_node(node)
        if text is None:
            return None, {node.node_id}
        return FlowStep(0, kind, text, (node.node_id,)), {node.node_id}

    def _reachable(
        self,
        start_id: str,
        *,
        stop_ids: frozenset[str] = frozenset(),
    ) -> frozenset[str]:
        found: set[str] = set()
        pending = [start_id]
        while pending:
            node_id = pending.pop()
            if node_id in found or node_id in stop_ids or node_id not in self.nodes:
                continue
            found.add(node_id)
            pending.extend(edge.target_id for edge in self.outgoing[node_id])
        return frozenset(found)

    def _loop_members(self, node: FlowNode) -> frozenset[str]:
        cached = self._loop_cache.get(node.node_id)
        if cached is not None:
            return cached
        exit_targets = frozenset(
            edge.target_id
            for edge in self.outgoing[node.node_id]
            if edge.kind == "exit-loop"
        )
        body_targets = tuple(
            edge.target_id
            for edge in self.outgoing[node.node_id]
            if edge.kind != "exit-loop"
        )
        stop = exit_targets | {node.node_id}
        members = {node.node_id}
        for target in body_targets:
            members.update(self._reachable(target, stop_ids=stop))
        result = frozenset(members)
        self._loop_cache[node.node_id] = result
        return result

    def _decision_members(
        self,
        node: FlowNode,
    ) -> tuple[frozenset[str], frozenset[str]]:
        cached = self._decision_cache.get(node.node_id)
        if cached is not None:
            return cached
        true_targets = tuple(
            edge.target_id
            for edge in self.outgoing[node.node_id]
            if edge.kind == "true"
        )
        false_targets = tuple(
            edge.target_id
            for edge in self.outgoing[node.node_id]
            if edge.kind == "false"
        )
        false_is_continuation = (
            len(false_targets) == 1
            and self.nodes[false_targets[0]].column <= node.column
            and self.nodes[false_targets[0]].kind != "if"
        )
        containing_loops = tuple(
            candidate
            for candidate in self.ordered_nodes
            if candidate.kind == "loop"
            and node.node_id in self._loop_members(candidate)
        )
        stop_ids = (
            frozenset(
                {
                    min(
                        containing_loops,
                        key=lambda candidate: len(self._loop_members(candidate)),
                    ).node_id
                }
            )
            if containing_loops
            else frozenset()
        )
        if false_is_continuation:
            stop_ids |= frozenset(false_targets)
        true_reach = (
            set().union(
                *(self._reachable(target, stop_ids=stop_ids) for target in true_targets)
            )
            if true_targets
            else set()
        )
        false_reach = (
            set().union(
                *(
                    self._reachable(target, stop_ids=stop_ids)
                    for target in false_targets
                )
            )
            if false_targets and not false_is_continuation
            else set()
        )
        true_reach.discard(node.node_id)
        false_reach.discard(node.node_id)
        common = true_reach & false_reach
        result = (
            frozenset(true_reach - common),
            frozenset(false_reach - common),
        )
        self._decision_cache[node.node_id] = result
        return result

    def _indented_path(self, start_id: str, parent_column: int) -> frozenset[str]:
        found: set[str] = set()
        pending = [start_id]
        while pending:
            node_id = pending.pop()
            if node_id in found:
                continue
            node = self.nodes[node_id]
            if node.column <= parent_column or node.kind == "exit":
                continue
            found.add(node_id)
            pending.extend(edge.target_id for edge in self.outgoing[node_id])
        return frozenset(found)

    def _exception_step(
        self,
        node: FlowNode,
        available: set[str],
    ) -> tuple[FlowStep, set[str]]:
        body_target = next(
            (
                edge.target_id
                for edge in self.outgoing[node.node_id]
                if edge.kind == "next"
            ),
            None,
        )
        handler_nodes = tuple(
            self.nodes[edge.target_id]
            for edge in self.outgoing[node.node_id]
            if edge.kind == "except"
        )
        body_ids = (
            set(self._indented_path(body_target, node.column)) & available
            if body_target
            else set()
        )
        body_steps = self._steps_from_ids(body_ids)
        handlers: list[str] = []
        owned = {node.node_id} | body_ids
        child_steps = list(body_steps)
        for handler in handler_nodes:
            handlers.append(handler.label.removeprefix("except ").strip())
            owned.add(handler.node_id)
            handler_target = next(
                (
                    edge.target_id
                    for edge in self.outgoing[handler.node_id]
                    if edge.kind == "next"
                ),
                None,
            )
            if handler_target:
                handler_ids = (
                    set(self._indented_path(handler_target, handler.column)) & available
                )
                owned.update(handler_ids)
                child_steps.extend(self._steps_from_ids(handler_ids))
        finally_nodes = tuple(
            candidate
            for candidate in self.ordered_nodes
            if candidate.kind == "finally"
            and candidate.line == node.line
            and candidate.column == node.column
        )
        finally_steps: tuple[FlowStep, ...] = ()
        if finally_nodes:
            final = finally_nodes[0]
            owned.add(final.node_id)
            target = next(
                (edge.target_id for edge in self.outgoing[final.node_id]), None
            )
            if target:
                final_ids = set(self._indented_path(target, final.column)) & available
                owned.update(final_ids)
                finally_steps = self._steps_from_ids(final_ids)
                child_steps.extend(finally_steps)
        handler_text = " and ".join(handlers)
        if handler_text:
            text = f"Attempt the operation and handle {handler_text} separately."
        else:
            text = "Attempt the protected operation."
        if finally_steps:
            text = f"{text[:-1]} and always execute the finalization path."
        exception = FlowException(
            protected_summary=self.narration._steps_summary(body_steps),
            handlers=tuple(handlers),
            finally_summary=self.narration._steps_summary(finally_steps),
            source_node_ids=_ordered_ids(self.nodes[item] for item in owned),
        )
        self._exceptions[node.node_id] = exception
        return (
            FlowStep(
                0,
                "exception",
                text,
                (node.node_id,),
                tuple(child_steps),
            ),
            owned,
        )


__all__ = ["_FlowExplanationBuilder"]
