"""Deterministic human explanations derived from existing callable CFGs."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, TypeAlias

from pysynoptic.insights.models import CallableInsight, InsightAnalysis
from pysynoptic.models import CallableFlowGraph, FlowEdge, FlowNode

FlowStepKind: TypeAlias = Literal[
    "break",
    "call",
    "continue",
    "decision",
    "exception",
    "loop",
    "raise",
    "return",
    "sequence",
    "statement",
]
FlowOutcomeKind: TypeAlias = Literal["raise", "return"]

_SENTENCE_LIMIT = 500
_MAX_STEPS = 18
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CALL_RE = re.compile(r"(?:^|=\s*)([A-Za-z_][A-Za-z0-9_.]*)\s*\(")
_ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]*)\s*=")
_BUILD_OUTPUT_RE = re.compile(r"^Build ([A-Za-z_][A-Za-z0-9_.]*) output")


class FlowExplanationReliability(StrEnum):
    """Qualitative reliability of one deterministic flow explanation."""

    HIGH = "high"
    MEDIUM = "medium"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FlowStep:
    """One compact, source-traceable step in a flow explanation."""

    order: int
    kind: FlowStepKind
    text: str
    source_node_ids: tuple[str, ...]
    child_steps: tuple[FlowStep, ...] = ()


@dataclass(frozen=True, slots=True)
class FlowDecision:
    """One CFG decision with its true and false paths kept distinct."""

    condition: str
    true_path: tuple[FlowStep, ...]
    false_path: tuple[FlowStep, ...]
    source_node_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FlowLoop:
    """One loop and the compact explanation of its nested body."""

    header: str
    body_summary: str | None
    body_steps: tuple[FlowStep, ...]
    source_node_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FlowException:
    """One try region, its handlers, and an optional finalization path."""

    protected_summary: str | None
    handlers: tuple[str, ...]
    finally_summary: str | None
    source_node_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FlowOutcome:
    """One statically visible return or raise outcome."""

    kind: FlowOutcomeKind
    text: str
    source_node_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FlowExplanation:
    """Deterministic explanation of one existing CallableFlowGraph."""

    callable_identity: str
    summary: str | None
    steps: tuple[FlowStep, ...]
    decisions: tuple[FlowDecision, ...]
    loops: tuple[FlowLoop, ...]
    exceptions: tuple[FlowException, ...]
    outcomes: tuple[FlowOutcome, ...]
    reliability: FlowExplanationReliability
    supporting_node_ids: tuple[str, ...]


InsightSource: TypeAlias = (
    InsightAnalysis | Iterable[CallableInsight] | Mapping[str, CallableInsight] | None
)


def _sentence(text: str) -> str:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return ""
    normalized = normalized[0].upper() + normalized[1:]
    return normalized if normalized.endswith((".", "!", "?")) else f"{normalized}."


def _lower_sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    lowered = text[0].lower() + text[1:]
    return lowered[:-1] if lowered.endswith(".") else lowered


def _human_name(text: str) -> str:
    """Normalize a visible source name without claiming hidden semantics."""
    stripped = text.strip().strip("()")
    stripped = stripped.rsplit(".", 1)[-1]
    words = [word for word in stripped.replace("-", "_").split("_") if word]
    return " ".join(words) or stripped


def _singular(text: str) -> str:
    if text.endswith("ies") and len(text) > 3:
        return f"{text[:-3]}y"
    if text.endswith("s") and not text.endswith("ss") and len(text) > 1:
        return text[:-1]
    return text


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
        self.callable_insights = self._callable_insights(insights)
        self.caller = next(
            (
                insight
                for insight in self.callable_insights
                if insight.symbol_id == flow.symbol_id
            ),
            None,
        )
        self.purpose_by_call_name = self._purpose_index()
        self._loop_cache: dict[str, frozenset[str]] = {}
        self._decision_cache: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
        self._decisions: dict[str, FlowDecision] = {}
        self._loops: dict[str, FlowLoop] = {}
        self._exceptions: dict[str, FlowException] = {}
        self._active_structures: set[str] = set()

    @staticmethod
    def _callable_insights(insights: InsightSource) -> tuple[CallableInsight, ...]:
        if insights is None:
            return ()
        if isinstance(insights, InsightAnalysis):
            return insights.callables
        if isinstance(insights, Mapping):
            return tuple(insights.values())
        return tuple(insights)

    def _purpose_index(self) -> dict[str, str]:
        if self.caller is None:
            return {}
        allowed = set(self.caller.callees)
        candidates: dict[str, list[str]] = {}
        for insight in self.callable_insights:
            if insight.identity not in allowed or not insight.purpose:
                continue
            short_name = insight.qualified_name.rsplit(".", 1)[-1]
            candidates.setdefault(short_name, []).append(insight.purpose)
        return {
            name: values[0]
            for name, values in candidates.items()
            if len(set(values)) == 1
        }

    def build(self) -> FlowExplanation:
        semantic_ids = {
            node.node_id
            for node in self.ordered_nodes
            if node.kind not in {"entry", "exit"}
        }
        steps = self._steps_from_ids(semantic_ids)
        outcomes = tuple(
            self._outcome(node)
            for node in self.ordered_nodes
            if node.kind in {"return", "raise"}
        )
        summary = self._summary(steps, outcomes)
        supporting = _ordered_ids(
            self.nodes[node_id]
            for step in steps
            for node_id in self._all_step_ids(step)
        )
        reliability = self._reliability(steps, summary)
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
        compacted = self._compact_steps(tuple(raw))
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
            text = self._loop_text(node, children)
            loop = FlowLoop(
                header=node.label,
                body_summary=self._steps_summary(children),
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
            text = self._decision_text(condition, true_steps, false_steps)
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
            outcome = self._outcome(node)
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
        text, kind = self._describe_node(node)
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
            protected_summary=self._steps_summary(body_steps),
            handlers=tuple(handlers),
            finally_summary=self._steps_summary(finally_steps),
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

    def _call_name(self, node: FlowNode) -> str | None:
        match = _CALL_RE.search(node.detail)
        return match.group(1) if match else None

    def _resolved_purpose(self, node: FlowNode) -> str | None:
        call_name = self._call_name(node)
        if not call_name:
            return None
        return self.purpose_by_call_name.get(call_name.rsplit(".", 1)[-1])

    def _describe_node(
        self,
        node: FlowNode,
    ) -> tuple[str | None, FlowStepKind]:
        label = node.label
        detail = node.detail.strip()
        if label == "pass":
            return None, "statement"
        if len(detail) >= 2 and detail[0] in {"'", '"'} and detail[-1] == detail[0]:
            return None, "statement"
        if label.startswith("Initialize "):
            target = label.removeprefix("Initialize ").strip()
            if _human_name(target) in {"lines", "output", "outputs", "result"}:
                return "Initialize the output.", "statement"
            return _sentence(f"Initialize {_human_name(target)}"), "statement"
        output_match = _BUILD_OUTPUT_RE.match(label)
        if output_match:
            return "Build the output text.", "sequence"
        if label.startswith("Print "):
            return "Print summary messages.", "call"
        if label.startswith("Add ") and label.endswith(" arguments"):
            return "Configure command-line arguments.", "call"
        if "write_text(" in detail:
            return "Write the generated output.", "call"
        if ".append(" in detail or ".extend(" in detail:
            receiver_match = re.search(
                r"([A-Za-z_][A-Za-z0-9_.]*)\.(?:append|extend)\(", detail
            )
            receiver = _human_name(receiver_match.group(1)) if receiver_match else ""
            if receiver in {"lines", "output", "outputs", "result"}:
                return "Append generated content to the output.", "call"
            if receiver:
                return _sentence(f"Add an item to {receiver}"), "call"
            return "Append an item to the collection.", "call"
        if ".sort(" in detail:
            receiver = detail.partition(".sort(")[0].rsplit("\n", 1)[-1]
            return _sentence(f"Sort {_human_name(receiver)}"), "call"
        purpose = self._resolved_purpose(node)
        if purpose:
            return _sentence(purpose), "call"
        assignment = _ASSIGNMENT_RE.match(detail)
        call_name = self._call_name(node)
        if assignment and call_name:
            target = _human_name(assignment.group(1))
            if call_name in {"dict", "list", "set", "tuple"}:
                return _sentence(f"Initialize {target}"), "statement"
            if call_name.endswith(".get"):
                receiver = _human_name(call_name.rpartition(".")[0])
                return _sentence(f"Retrieve {target} from {receiver}"), "call"
            if call_name.rsplit(".", 1)[-1] == "sum":
                return _sentence(f"Calculate {target}"), "call"
            if call_name.endswith(".parse_args"):
                return "Parse command-line arguments.", "call"
            if call_name.endswith(".getroot"):
                return "Retrieve the parsed root.", "call"
            return _sentence(f"Set {target} from {call_name}()"), "call"
        if call_name:
            return _sentence(f"Call {call_name}()"), "call"
        if label.startswith("Build ") and label.endswith(" mapping"):
            target = label.removeprefix("Build ").removesuffix(" mapping")
            return _sentence(f"Build the {_human_name(target)} mapping"), "statement"
        if assignment:
            return _sentence(f"Set {_human_name(assignment.group(1))}"), "statement"
        if label.startswith("define "):
            return _sentence(label), "statement"
        if detail:
            short = " ".join(detail.split())
            if len(short) <= 80:
                return _sentence(short), "statement"
        return None, "statement"

    def _loop_text(self, node: FlowNode, children: tuple[FlowStep, ...]) -> str:
        label = node.detail.partition(":")[0].strip() or node.label
        if label.startswith("while "):
            condition = label.removeprefix("while ")
            return _sentence(f"Repeat while {condition}")
        match = re.match(r"for (.+?) in (.+)", label)
        if not match:
            return "Process each loop item."
        target, iterable = match.groups()
        simple_iterable = re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", iterable)
        iterable_name = _human_name(iterable) if simple_iterable else ""
        item = _human_name(target)
        if iterable_name and (len(item) <= 3 or item in {"item", "value"}):
            item = _singular(iterable_name)
        has_output_mutation = any(
            "output" in child.text.casefold() for child in children
        )
        if has_output_mutation and iterable_name in {
            "controls",
            "safe fixes",
            "manual fixes",
        }:
            noun = {
                "controls": "control command",
                "safe fixes": "safe fix",
                "manual fixes": "manual fix",
            }[iterable_name]
            return _sentence(f"Add each {noun} to the output")
        if not iterable_name:
            call = re.match(r"([A-Za-z_][A-Za-z0-9_.]*)\(", iterable)
            if call:
                return _sentence(f"Process each item returned by {call.group(1)}()")
            return _sentence(f"Process each item in {iterable}")
        return _sentence(f"Process each {item}")

    def _condition_text(self, condition: str) -> str:
        normalized = condition.strip()
        if "…" in normalized or len(normalized) > 100:
            return "a branch condition"
        parts = re.split(r"\s+and\s+", normalized)
        if len(parts) > 1:
            return " and ".join(self._condition_text(part) for part in parts)
        if normalized.startswith("not "):
            negated = normalized.removeprefix("not ")
            if negated.endswith(")"):
                return f"{negated} is false"
            name = _human_name(negated)
            verb = "are" if name.endswith("s") else "is"
            return f"{name} {verb} not available"
        if normalized.startswith("(") and normalized.endswith(")"):
            return self._condition_text(normalized[1:-1])
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", normalized):
            name = _human_name(normalized)
            if name.endswith(("fixes", "items", "controls", "values")):
                return f"{name} are available"
            return f"{name} is true"
        return normalized

    def _decision_text(
        self,
        condition: str,
        true_steps: tuple[FlowStep, ...],
        false_steps: tuple[FlowStep, ...],
    ) -> str:
        condition_text = self._condition_text(condition)
        true_summary = self._steps_summary(true_steps, limit=2)
        false_summary = self._steps_summary(false_steps, limit=2)
        if true_summary:
            text = f"If {condition_text}, {_lower_sentence(true_summary)}"
        else:
            text = f"Check whether {condition_text}"
        if false_summary:
            text = f"{text.rstrip('.')}. Otherwise, {_lower_sentence(false_summary)}"
        return _sentence(text)

    def _outcome(self, node: FlowNode) -> FlowOutcome:
        if node.kind == "raise":
            expression = node.detail.removeprefix("raise ").strip()
            exception = _WORD_RE.match(expression)
            text = (
                f"Raise {exception.group(0)}."
                if exception
                else "Follow a path that raises an exception."
            )
            return FlowOutcome("raise", text, (node.node_id,))
        expression = node.detail.removeprefix("return").strip()
        if not expression:
            text = "Return None."
        elif re.search(r"['\"]\\n['\"]\.join\(([^)]+)\)", expression):
            collection = re.search(r"['\"]\\n['\"]\.join\(([^)]+)\)", expression).group(
                1
            )
            text = f"Join {_human_name(collection)} and return the resulting text."
        elif expression == "None":
            text = "Return None."
        elif re.fullmatch(r"-?\d+(?:\.\d+)?", expression) or re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_.]*", expression
        ):
            text = f"Return {expression}."
        elif "(" in expression or len(expression) > 80:
            text = "Return the generated value."
        elif re.fullmatch(r"[-+*/% A-Za-z0-9_.]+", expression):
            text = f"Return the result of {expression}."
        else:
            text = f"Return {expression}."
        return FlowOutcome("return", _sentence(text), (node.node_id,))

    def _compact_steps(self, steps: tuple[FlowStep, ...]) -> tuple[FlowStep, ...]:
        compacted: list[FlowStep] = []
        index = 0
        while index < len(steps):
            current = steps[index]
            group = [current]
            cursor = index + 1
            while cursor < len(steps) and steps[cursor].text == current.text:
                group.append(steps[cursor])
                cursor += 1
            if len(group) > 1:
                text = (
                    "Write the generated outputs."
                    if current.text == "Write the generated output."
                    else current.text
                )
                compacted.append(
                    FlowStep(
                        0,
                        "sequence",
                        text,
                        tuple(
                            node_id
                            for step in group
                            for node_id in step.source_node_ids
                        ),
                        tuple(child for step in group for child in step.child_steps),
                    )
                )
                index = cursor
                continue
            if current.text.startswith("Write the generated output"):
                writes = [current]
                cursor = index + 1
                while cursor < len(steps) and steps[cursor].text.startswith(
                    "Write the generated output"
                ):
                    writes.append(steps[cursor])
                    cursor += 1
                if len(writes) > 1:
                    compacted.append(
                        FlowStep(
                            0,
                            "sequence",
                            "Write the generated outputs.",
                            tuple(
                                node_id
                                for step in writes
                                for node_id in step.source_node_ids
                            ),
                        )
                    )
                    index = cursor
                    continue
            if current.text.startswith("Calculate "):
                calculations = [current]
                cursor = index + 1
                while cursor < len(steps) and steps[cursor].text.startswith(
                    "Calculate "
                ):
                    calculations.append(steps[cursor])
                    cursor += 1
                if len(calculations) > 1:
                    compacted.append(
                        FlowStep(
                            0,
                            "sequence",
                            "Calculate summary values.",
                            tuple(
                                node_id
                                for step in calculations
                                for node_id in step.source_node_ids
                            ),
                        )
                    )
                    index = cursor
                    continue
            compacted.append(current)
            index += 1
        return tuple(compacted)

    @staticmethod
    def _steps_summary(
        steps: tuple[FlowStep, ...],
        *,
        limit: int = 5,
    ) -> str | None:
        texts: list[str] = []
        for step in steps:
            if step.text not in texts:
                texts.append(step.text)
            if len(texts) >= limit:
                break
        if not texts:
            return None
        return " ".join(texts)

    @staticmethod
    def _steps_clause_summary(
        steps: tuple[FlowStep, ...],
        *,
        limit: int,
    ) -> str | None:
        clauses: list[str] = []
        for step in steps:
            text = _lower_sentence(step.text)
            text = re.sub(r"\.\s+Otherwise,\s*", "; otherwise, ", text)
            text = re.sub(r"\.\s+", "; then ", text)
            text = re.sub(
                r"(; (?:otherwise, |then ))([A-Z])",
                lambda match: f"{match.group(1)}{match.group(2).lower()}",
                text,
            )
            if text not in clauses:
                clauses.append(text)
            if len(clauses) >= limit:
                break
        return "; then ".join(clauses) if clauses else None

    def _summary(
        self,
        steps: tuple[FlowStep, ...],
        outcomes: tuple[FlowOutcome, ...],
    ) -> str | None:
        if not steps:
            return None
        structures = [
            step for step in steps if step.kind in {"loop", "decision", "exception"}
        ]
        sentences: list[str] = []

        def add_sentence(text: str) -> None:
            normalized = _sentence(text)
            if normalized and normalized not in sentences:
                sentences.append(normalized)

        if structures:
            first_structure = steps.index(structures[0])
            setup = steps[:first_structure]
            if setup:
                setup_text = self._steps_clause_summary(setup, limit=2)
                if setup_text:
                    add_sentence(setup_text)
            for structure in structures[:2]:
                add_sentence(structure.text)
                if structure.kind == "loop" and structure.child_steps:
                    body = self._steps_clause_summary(
                        structure.child_steps,
                        limit=5,
                    )
                    if body:
                        add_sentence(f"Within each iteration, {_lower_sentence(body)}.")
        else:
            purpose_texts = {
                _sentence(purpose) for purpose in self.purpose_by_call_name.values()
            }
            purposeful = [step for step in steps if step.text in purpose_texts]
            if purposeful:
                for step in purposeful[:3]:
                    add_sentence(step.text)
            else:
                for step in steps[:3]:
                    add_sentence(step.text)
        if outcomes:
            outcome_text = outcomes[-1].text
            if not any(outcome_text in sentence for sentence in sentences):
                add_sentence(outcome_text)
        if outcomes and len(sentences) > 4:
            sentences = [*sentences[:3], sentences[-1]]
        summary = " ".join(sentences[:4])
        if len(summary) <= _SENTENCE_LIMIT:
            return summary
        shortened = summary[: _SENTENCE_LIMIT - 1].rsplit(" ", 1)[0]
        return f"{shortened}…"

    def _reliability(
        self,
        steps: tuple[FlowStep, ...],
        summary: str | None,
    ) -> FlowExplanationReliability:
        if not summary or not steps:
            return FlowExplanationReliability.UNKNOWN
        all_steps = tuple(
            step for parent in steps for step in self._flatten_steps(parent)
        )
        opaque = sum(
            step.text == "Process additional intermediate operations."
            or step.text == "Return the generated value."
            or step.text.startswith("Set ")
            for step in all_steps
        )
        structured = any(
            step.kind in {"decision", "exception", "loop", "return", "raise"}
            for step in all_steps
        )
        semantic_nodes = sum(
            node.kind not in {"entry", "exit"} for node in self.ordered_nodes
        )
        if semantic_nodes > 20 and len(steps) <= 2:
            return FlowExplanationReliability.UNKNOWN
        if opaque == 0 and (structured or len(steps) <= 4):
            return FlowExplanationReliability.HIGH
        if opaque < len(all_steps):
            return FlowExplanationReliability.MEDIUM
        return FlowExplanationReliability.UNKNOWN

    @staticmethod
    def _flatten_steps(step: FlowStep) -> tuple[FlowStep, ...]:
        return (step,) + tuple(
            descendant
            for child in step.child_steps
            for descendant in _FlowExplanationBuilder._flatten_steps(child)
        )


def explain_callable_flow(
    flow: CallableFlowGraph,
    insights: InsightSource = None,
) -> FlowExplanation:
    """Explain an existing CFG without reading, importing, or executing source."""
    return _FlowExplanationBuilder(flow, insights).build()


analyze_flow_explanation = explain_callable_flow


__all__ = [
    "FlowDecision",
    "FlowException",
    "FlowExplanation",
    "FlowExplanationReliability",
    "FlowLoop",
    "FlowOutcome",
    "FlowStep",
    "analyze_flow_explanation",
    "explain_callable_flow",
]
