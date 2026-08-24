"""Structured Insights presentation and Tk panel without analysis heuristics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from tkinter.scrolledtext import ScrolledText
from typing import TypeAlias

import ttkbootstrap as ttk

from pysynoptic.gui.flow_explanations import FlowExplanationCache
from pysynoptic.gui.state import InsightSubjectKind
from pysynoptic.insights import (
    CallableInsight,
    ClassInsight,
    FlowExplanation,
    FlowExplanationReliability,
    FlowStep,
    InsightAnalysis,
    InsightConfidence,
    InsightEvidence,
    InsightInput,
    ModuleInsight,
    PurposeSource,
)

InsightSubject: TypeAlias = ModuleInsight | ClassInsight | CallableInsight

_PURPOSE_SOURCE_LABELS = {
    PurposeSource.DOCSTRING: "Declared by docstring",
    PurposeSource.ROLE_TEMPLATE: "Statically inferred",
    PurposeSource.STRUCTURE: "Structural summary",
    PurposeSource.NONE: "No reliable purpose identified",
}
_CONFIDENCE_DESCRIPTIONS = {
    InsightConfidence.HIGH: "Multiple converging static signals",
    InsightConfidence.MEDIUM: "Useful static evidence, with limitations",
    InsightConfidence.UNKNOWN: "Insufficient evidence for a reliable role",
}


@dataclass(frozen=True, slots=True)
class InsightSelection:
    """Stable selection key stored without copying an Insight."""

    kind: InsightSubjectKind
    identity: str


@dataclass(frozen=True, slots=True)
class InsightSection:
    """One deterministic section of an Insight presentation."""

    title: str
    items: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InsightPresentation:
    """Headless-safe content rendered by the Tk panel."""

    selection: InsightSelection
    title: str
    subject_type: str
    role: str
    confidence: str
    confidence_description: str
    purpose: str
    purpose_source: str
    sections: tuple[InsightSection, ...]
    evidence: tuple[InsightEvidence, ...]
    callable_symbol_id: str | None = None
    flow_explanation: FlowExplanation | None = None


@dataclass(frozen=True, slots=True)
class FlowStepPresentation:
    """One root or nested Key Step rendered without flattening its hierarchy."""

    marker: str
    text: str
    depth: int
    source_node_ids: tuple[str, ...]


class InsightCatalog:
    """Fast identity lookup holding references to one immutable analysis."""

    def __init__(self, analysis: InsightAnalysis | None) -> None:
        self.analysis = analysis
        self._subjects: dict[tuple[str, str], InsightSubject] = {}
        self._callables_by_symbol: dict[str, CallableInsight] = {}
        if analysis is None:
            return
        for item in analysis.modules:
            self._subjects[("module", item.identity)] = item
        for item in analysis.classes:
            self._subjects[("class", item.identity)] = item
        for item in analysis.callables:
            self._subjects[("callable", item.identity)] = item
            self._callables_by_symbol[item.symbol_id] = item

    def find(self, selection: InsightSelection) -> InsightSubject | None:
        """Return an existing Insight by stable kind and identity."""
        return self._subjects.get((selection.kind, selection.identity))

    def callable_for_symbol(self, symbol_id: str) -> CallableInsight | None:
        """Return a callable Insight by the existing navigation symbol ID."""
        return self._callables_by_symbol.get(symbol_id)


def _input_item(item: InsightInput) -> str:
    lines = [item.name]
    if item.annotation:
        lines.append(f"Type: {item.annotation}")
    if item.default is not None:
        lines.append(f"Default: {item.default}")
    return "\n  ".join(lines)


def _short_callable(identity: str) -> str:
    return identity.partition("::")[2] or identity


def _items_or_none(items: tuple[str, ...], message: str) -> tuple[str, ...]:
    return items or (message,)


def _module_sections(insight: ModuleInsight) -> tuple[InsightSection, ...]:
    return (
        InsightSection(
            "Responsibilities",
            _items_or_none(insight.responsibilities, "None statically identified"),
        ),
        InsightSection(
            "Side effects",
            _items_or_none(insight.side_effects, "None statically identified"),
        ),
    )


def _class_sections(insight: ClassInsight) -> tuple[InsightSection, ...]:
    structure = (
        f"{insight.field_count} field{'s' if insight.field_count != 1 else ''}",
        f"{insight.method_count} method{'s' if insight.method_count != 1 else ''}",
        *(("Dataclass",) if insight.is_dataclass else ()),
    )
    return (
        InsightSection("Structure", structure),
        InsightSection(
            "Responsibilities",
            _items_or_none(insight.responsibilities, "None statically identified"),
        ),
    )


def _callable_sections(insight: CallableInsight) -> tuple[InsightSection, ...]:
    inputs = insight.inputs
    receiver = tuple(
        _input_item(item) for item in inputs[:1] if item.name in {"self", "cls"}
    )
    if receiver:
        inputs = inputs[1:]
    sections = []
    if receiver:
        sections.append(InsightSection("Receiver", receiver))
    sections.extend(
        (
            InsightSection(
                "Responsibilities",
                _items_or_none(insight.responsibilities, "None statically identified"),
            ),
            InsightSection(
                "Inputs",
                _items_or_none(tuple(_input_item(item) for item in inputs), "None"),
            ),
            InsightSection(
                "Outputs",
                _items_or_none(insight.outputs, "None statically identified"),
            ),
            InsightSection(
                "Side effects",
                _items_or_none(insight.side_effects, "None statically identified"),
            ),
            InsightSection(
                "Called by",
                _items_or_none(
                    tuple(_short_callable(item) for item in insight.callers), "None"
                ),
            ),
            InsightSection(
                "Calls",
                _items_or_none(
                    tuple(_short_callable(item) for item in insight.callees), "None"
                ),
            ),
        )
    )
    return tuple(sections)


def present_insight(
    selection: InsightSelection,
    insight: InsightSubject,
    flow_explanation: FlowExplanation | None = None,
) -> InsightPresentation:
    """Build a display-only representation without changing engine text."""
    if isinstance(insight, CallableInsight):
        subject_type = "Async " if insight.is_async else ""
        subject_type += "Method" if insight.kind == "method" else "Function"
        sections = _callable_sections(insight)
        symbol_id = insight.symbol_id
    elif isinstance(insight, ClassInsight):
        subject_type = "Class"
        sections = _class_sections(insight)
        symbol_id = None
    else:
        subject_type = "Module"
        sections = _module_sections(insight)
        symbol_id = None
    return InsightPresentation(
        selection=selection,
        title=insight.display_name,
        subject_type=subject_type,
        role=insight.role.value.upper(),
        confidence=insight.confidence.value.upper(),
        confidence_description=_CONFIDENCE_DESCRIPTIONS[insight.confidence],
        purpose=insight.purpose or "No reliable purpose identified.",
        purpose_source=_PURPOSE_SOURCE_LABELS[insight.purpose_source],
        sections=sections,
        evidence=insight.evidence,
        callable_symbol_id=symbol_id,
        flow_explanation=flow_explanation if symbol_id is not None else None,
    )


def flow_step_presentations(
    steps: tuple[FlowStep, ...],
) -> tuple[FlowStepPresentation, ...]:
    """Preserve root order and child hierarchy for the Insights text view."""
    rows: list[FlowStepPresentation] = []

    def append(children: tuple[FlowStep, ...], depth: int) -> None:
        for index, step in enumerate(children, start=1):
            rows.append(
                FlowStepPresentation(
                    marker=f"{index}." if depth == 0 else "•",
                    text=step.text,
                    depth=depth,
                    source_node_ids=step.source_node_ids,
                )
            )
            append(step.child_steps, depth + 1)

    append(steps, 0)
    return tuple(rows)


def flow_summary_text(explanation: FlowExplanation | None) -> str:
    """Return exact engine text or the single approved UNKNOWN fallback."""
    if explanation is None or explanation.summary is None:
        return "No reliable flow explanation available."
    return explanation.summary


def evidence_lines(evidence: tuple[InsightEvidence, ...]) -> tuple[str, ...]:
    """Group exact Evidence descriptions for a secondary display panel."""
    lines = []
    current_category = None
    for item in evidence:
        if item.category is not current_category:
            current_category = item.category
            if lines:
                lines.append("")
            lines.append(item.category.value.replace("_", " ").title())
        lines.append(f"[{item.strength.value.upper()}] {item.description}")
    return tuple(lines)


class InsightsPanel(ttk.Frame):
    """Display one selected Structured Insight and navigation actions."""

    def __init__(
        self,
        master,
        *,
        on_show_calls=None,
        on_open_flow=None,
        on_open_flow_step: Callable[[str, tuple[str, ...]], None] | None = None,
        flow_explanations: FlowExplanationCache | None = None,
    ) -> None:
        super().__init__(master, padding=10)
        self._catalog = InsightCatalog(None)
        self._selection: InsightSelection | None = None
        self._presentation: InsightPresentation | None = None
        self._analysis: InsightAnalysis | None = None
        self._error_message: str | None = None
        self._evidence_expanded = False
        self._on_show_calls = on_show_calls
        self._on_open_flow = on_open_flow
        self._on_open_flow_step = on_open_flow_step
        self._flow_explanations = flow_explanations
        self._flow_step_links: dict[str, tuple[str, ...]] = {}
        self._selected_step_node_ids: tuple[str, ...] | None = None

        actions = ttk.Frame(self)
        actions.pack(fill="x", pady=(0, 8))
        self.calls_button = ttk.Button(
            actions,
            text="Show in Calls",
            command=self._show_calls,
            state="disabled",
            bootstyle="secondary-outline",
        )
        self.calls_button.pack(side="left", padx=(0, 6))
        self.flow_button = ttk.Button(
            actions,
            text="Open Flow",
            command=self._open_flow,
            state="disabled",
            bootstyle="secondary-outline",
        )
        self.flow_button.pack(side="left")

        self.summary = ScrolledText(
            self,
            wrap="word",
            borderwidth=0,
            padx=12,
            pady=10,
            height=18,
        )
        self.summary.pack(fill="both", expand=True)
        self.summary.tag_configure("title", font=("TkDefaultFont", 15, "bold"))
        self.summary.tag_configure("heading", font=("TkDefaultFont", 10, "bold"))
        self.summary.tag_configure("step-link", foreground="#0d6efd", underline=True)
        self.summary.configure(state="disabled")

        evidence_header = ttk.Frame(self)
        evidence_header.pack(fill="x", pady=(8, 0))
        self.evidence_button = ttk.Button(
            evidence_header,
            text="Evidence (0)",
            command=self._toggle_evidence,
            state="disabled",
            bootstyle="link",
        )
        self.evidence_button.pack(side="left")
        self.evidence_text = ScrolledText(
            self,
            wrap="word",
            borderwidth=1,
            padx=10,
            pady=8,
            height=9,
        )
        self.evidence_text.configure(state="disabled")
        self._render_empty()

    @property
    def selection(self) -> InsightSelection | None:
        return self._selection

    @property
    def selected_callable_symbol_id(self) -> str | None:
        return self._presentation.callable_symbol_id if self._presentation else None

    @property
    def flow_explanation(self) -> FlowExplanation | None:
        """Return the explanation currently presented for a callable."""
        return self._presentation.flow_explanation if self._presentation else None

    def set_analysis(
        self,
        analysis: InsightAnalysis | None,
        *,
        error_message: str | None = None,
    ) -> None:
        """Index one completed analysis once and reset stale presentation."""
        if analysis is self._analysis and error_message == self._error_message:
            return
        self._analysis = analysis
        self._error_message = error_message
        self._catalog = InsightCatalog(analysis)
        self._selection = None
        self._presentation = None
        self._evidence_expanded = False
        self._flow_step_links.clear()
        self._selected_step_node_ids = None
        self.evidence_text.pack_forget()
        self._render_empty()

    def select(self, kind: InsightSubjectKind, identity: str) -> bool:
        """Display an Insight by stable identity without recalculation."""
        selection = InsightSelection(kind, identity)
        insight = self._catalog.find(selection)
        if insight is None:
            return False
        previous_symbol_id = self.selected_callable_symbol_id
        flow_explanation = None
        if isinstance(insight, CallableInsight) and self._flow_explanations is not None:
            try:
                cached = self._flow_explanations.get(insight.symbol_id)
            except (OSError, SyntaxError, ValueError):
                cached = None
            if cached is not None:
                flow_explanation = cached.explanation
        if previous_symbol_id != getattr(insight, "symbol_id", None):
            self._selected_step_node_ids = None
        self._selection = selection
        self._presentation = present_insight(selection, insight, flow_explanation)
        self._render_presentation()
        return True

    def select_callable(self, symbol_id: str) -> bool:
        """Display a callable selected by Calls, Flow, or the project tree."""
        insight = self._catalog.callable_for_symbol(symbol_id)
        return bool(insight is not None and self.select("callable", insight.identity))

    def _render_empty(self) -> None:
        if self._error_message:
            message = self._error_message
        elif self._analysis is None:
            message = "Select and analyze a Python file or project."
        else:
            message = "Select a module, class, function or method to inspect its role."
        self._set_text(self.summary, message)
        self._set_text(self.evidence_text, "")
        self.evidence_button.configure(text="Evidence (0)", state="disabled")
        self.calls_button.configure(state="disabled")
        self.flow_button.configure(state="disabled")

    def _render_presentation(self) -> None:
        presentation = self._presentation
        if presentation is None:
            self._render_empty()
            return
        self.summary.configure(state="normal")
        self.summary.delete("1.0", "end")
        self._flow_step_links.clear()
        self.summary.insert("end", f"{presentation.title}\n", "title")
        self.summary.insert("end", f"{presentation.subject_type}\n\n")
        self._summary_field("Role", presentation.role)
        self._summary_field(
            (
                "Insight confidence"
                if presentation.callable_symbol_id is not None
                else "Confidence"
            ),
            f"{presentation.confidence}\n{presentation.confidence_description}",
        )
        self._summary_field("Purpose", presentation.purpose)
        if presentation.callable_symbol_id is not None:
            explanation = presentation.flow_explanation
            self._summary_field(
                "How it works",
                flow_summary_text(explanation),
            )
            if explanation is not None:
                self._summary_field(
                    "Flow explanation reliability",
                    explanation.reliability.value.upper(),
                )
                if (
                    explanation.reliability is not FlowExplanationReliability.UNKNOWN
                    and explanation.steps
                ):
                    self._render_key_steps(explanation.steps)
        self._summary_field("Purpose source", presentation.purpose_source)
        for section in presentation.sections:
            self.summary.insert("end", f"{section.title}\n", "heading")
            for item in section.items:
                self.summary.insert("end", f"• {item}\n")
            self.summary.insert("end", "\n")
        self.summary.configure(state="disabled")

        count = len(presentation.evidence)
        self.evidence_button.configure(
            text=f"{'Hide' if self._evidence_expanded else 'Show'} Evidence ({count})",
            state="normal" if count else "disabled",
        )
        callable_state = "normal" if presentation.callable_symbol_id else "disabled"
        self.calls_button.configure(state=callable_state)
        self.flow_button.configure(state=callable_state)
        self._render_evidence()

    def _render_key_steps(self, steps: tuple[FlowStep, ...]) -> None:
        self.summary.insert("end", "Key steps\n", "heading")
        for index, row in enumerate(flow_step_presentations(steps)):
            tag = f"flow-step-{index}"
            self._flow_step_links[tag] = row.source_node_ids
            prefix = f"{'   ' * row.depth}{row.marker} "
            self.summary.insert("end", prefix)
            self.summary.insert("end", f"{row.text}\n", ("step-link", tag))
            self.summary.tag_bind(
                tag,
                "<Button-1>",
                lambda _event, step_tag=tag: self._open_flow_step(step_tag),
            )
        self.summary.insert("end", "\n")

    def _summary_field(self, label: str, value: str) -> None:
        self.summary.insert("end", f"{label}\n", "heading")
        self.summary.insert("end", f"{value}\n\n")

    def _toggle_evidence(self) -> None:
        self._evidence_expanded = not self._evidence_expanded
        if self._evidence_expanded:
            self.evidence_text.pack(fill="both", expand=False, pady=(4, 0))
        else:
            self.evidence_text.pack_forget()
        self._render_presentation()

    def _render_evidence(self) -> None:
        presentation = self._presentation
        if presentation is None:
            return
        self._set_text(
            self.evidence_text,
            "\n".join(evidence_lines(presentation.evidence)),
        )

    @staticmethod
    def _set_text(widget: ScrolledText, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    def _show_calls(self) -> None:
        symbol_id = self.selected_callable_symbol_id
        if symbol_id is not None and self._on_show_calls is not None:
            self._on_show_calls(symbol_id)

    def _open_flow(self) -> None:
        symbol_id = self.selected_callable_symbol_id
        if symbol_id is not None and self._on_open_flow is not None:
            self._on_open_flow(symbol_id)

    def _open_flow_step(self, tag: str) -> None:
        symbol_id = self.selected_callable_symbol_id
        node_ids = self._flow_step_links.get(tag)
        if symbol_id is not None and node_ids and self._on_open_flow_step is not None:
            self._selected_step_node_ids = node_ids
            self._on_open_flow_step(symbol_id, node_ids)
