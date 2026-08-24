"""Deterministic short-purpose generation from classified static Evidence."""

from __future__ import annotations

import re
from collections.abc import Iterable

from pysynoptic.insights.models import (
    CallableFacts,
    ClassFacts,
    EvidenceCategory,
    InsightEvidence,
    InsightRole,
    ModuleFacts,
    PurposeResult,
    PurposeSource,
    RoleClassification,
)

_MAX_PURPOSE_LENGTH = 160
_ACTION_TOKENS = {
    InsightRole.ORCHESTRATOR: {"execute", "main", "process", "run"},
    InsightRole.ANALYZER: {"analysis", "analyze", "analyzer", "inspect"},
    InsightRole.PARSER: {"parse", "parser"},
    InsightRole.RENDERER: {"format", "render", "renderer", "serialize"},
    InsightRole.EXPORTER: {"dump", "export", "save"},
    InsightRole.LOADER: {"load", "loader"},
    InsightRole.READER: {"read", "reader"},
    InsightRole.WRITER: {"write", "writer"},
    InsightRole.VALIDATOR: {"check", "validate", "validator", "verify"},
    InsightRole.TRANSFORMER: {
        "convert",
        "map",
        "normalize",
        "transform",
        "transformer",
    },
    InsightRole.RESOLVER: {"resolution", "resolve", "resolver"},
    InsightRole.SCANNER: {"discover", "scan", "scanner", "walk"},
    InsightRole.GRAPH_BUILDER: {"build", "builder", "edge", "graph", "layout", "node"},
    InsightRole.CONTROLLER: {"control", "controller"},
    InsightRole.ADAPTER: {"adapt", "adapter"},
    InsightRole.MODEL: {"model"},
    InsightRole.FACTORY: {"create", "factory", "make"},
    InsightRole.UTILITY: {"utility"},
}
_ALL_ACTION_TOKENS = frozenset(
    token for tokens in _ACTION_TOKENS.values() for token in tokens
)
_DISPLAY_TERMS = {
    "api": "API",
    "ast": "AST",
    "cli": "CLI",
    "csv": "CSV",
    "gui": "GUI",
    "html": "HTML",
    "http": "HTTP",
    "https": "HTTPS",
    "json": "JSON",
    "markdown": "Markdown",
    "powershell": "PowerShell",
    "python": "Python",
    "sql": "SQL",
    "tkinter": "Tkinter",
    "url": "URL",
    "xml": "XML",
    "yaml": "YAML",
}
_OUTPUT_FORMATS = frozenset(
    {"csv", "html", "json", "markdown", "powershell", "xml", "yaml"}
)
_ARTICLE_SUBJECTS = frozenset(
    {
        "callable",
        "class",
        "directory",
        "file",
        "function",
        "module",
        "package",
        "path",
        "project",
        "reference",
        "source",
    }
)
_SUBJECT_EDGE_WORDS = frozenset({"by", "for", "from", "in", "of", "on", "to", "with"})
_UNHELPFUL_DOCSTRINGS = frozenset(
    {"fixme", "helper", "pass", "tbd", "todo", "unknown", "utility"}
)


def _evidence_key(item: InsightEvidence) -> tuple[str, str, str, str, int, str]:
    return (
        item.category.value,
        item.code,
        item.description,
        item.reference or "",
        item.source_line if item.source_line is not None else -1,
        item.strength.value,
    )


def _ordered(items: Iterable[InsightEvidence]) -> tuple[InsightEvidence, ...]:
    return tuple(sorted(set(items), key=_evidence_key))


def _sentence(text: str) -> str:
    normalized = " ".join(text.split())
    if len(normalized) > _MAX_PURPOSE_LENGTH:
        normalized = f"{normalized[: _MAX_PURPOSE_LENGTH - 1].rstrip()}…"
    if normalized and normalized[-1] not in ".!?…":
        normalized = f"{normalized}."
    return normalized


def _useful_docstring(evidence: tuple[InsightEvidence, ...]) -> PurposeResult | None:
    candidates = tuple(item for item in evidence if item.code == "docstring_summary")
    if not candidates:
        return None
    item = candidates[0]
    summary = " ".join((item.reference or "").split())
    words = re.findall(r"[A-Za-z0-9]+", summary.casefold())
    if not summary or len(words) < 2 or words[0] in _UNHELPFUL_DOCSTRINGS:
        return None
    return PurposeResult(
        text=_sentence(summary),
        source=PurposeSource.DOCSTRING,
        supporting_evidence=(item,),
    )


def _identifier_tokens(value: str) -> tuple[str, ...]:
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return tuple(
        token.casefold()
        for token in re.split(r"[^A-Za-z0-9]+", value)
        if token and token.casefold() != "locals"
    )


def _name_parts(
    facts: ModuleFacts | ClassFacts | CallableFacts,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if isinstance(facts, ModuleFacts):
        direct = _identifier_tokens(facts.module.rpartition(".")[2])
        return direct, ()
    if isinstance(facts, ClassFacts):
        return _identifier_tokens(facts.name), ()

    direct = _identifier_tokens(facts.name)
    parent_parts = facts.qualified_name.rsplit(".", 1)
    if len(parent_parts) == 1:
        return direct, ()
    parent = parent_parts[0].rsplit(".", 1)[-1]
    return direct, _identifier_tokens(parent)


def _subject_tokens(
    facts: ModuleFacts | ClassFacts | CallableFacts,
    role: InsightRole,
) -> tuple[str, ...]:
    direct, parent = _name_parts(facts)
    action_tokens = _ACTION_TOKENS.get(role, set())
    subject = tuple(token for token in direct if token not in action_tokens)
    if subject:
        if role is InsightRole.ORCHESTRATOR:
            subject = tuple(
                token for token in subject if token not in _ALL_ACTION_TOKENS
            )
        while subject and subject[0] in _SUBJECT_EDGE_WORDS:
            subject = subject[1:]
        while subject and subject[-1] in _SUBJECT_EDGE_WORDS:
            subject = subject[:-1]
        if (
            role is InsightRole.ANALYZER
            and len(subject) == 1
            and subject[0].endswith("ed")
        ):
            return ()
        return subject
    return tuple(
        token
        for token in parent
        if token not in _ALL_ACTION_TOKENS and token not in _SUBJECT_EDGE_WORDS
    )


def _display_token(token: str) -> str:
    if token in _DISPLAY_TERMS:
        return _DISPLAY_TERMS[token]
    return token


def _subject_text(tokens: tuple[str, ...]) -> str:
    return " ".join(_display_token(token) for token in tokens)


def _with_article(tokens: tuple[str, ...]) -> str:
    text = _subject_text(tokens)
    if len(tokens) == 1 and tokens[0] in _ARTICLE_SUBJECTS:
        return f"a {text}"
    return text


def _plural_subject(tokens: tuple[str, ...]) -> str:
    if not tokens:
        return "references"
    values = list(tokens)
    last = values[-1]
    if last == "identity":
        values[-1] = "identities"
    elif last == "analysis":
        values[-1] = "analyses"
    elif not last.endswith("s"):
        values[-1] = f"{last}s"
    return _subject_text(tuple(values))


def _role_text(
    role: InsightRole,
    subject: tuple[str, ...],
    evidence: tuple[InsightEvidence, ...],
) -> str | None:
    if role is InsightRole.UNKNOWN:
        return None
    if role is InsightRole.ORCHESTRATOR:
        calls = tuple(item for item in evidence if item.code.startswith("calls:"))
        if not subject and len(calls) >= 3:
            return "Coordinate the program workflow."
        if subject:
            return f"Coordinate the {_subject_text(subject)} workflow."
        return "Coordinate operations."
    if role is InsightRole.ANALYZER:
        return f"Analyze {_with_article(subject) if subject else 'code'}."
    if role is InsightRole.PARSER:
        return f"Parse {_subject_text(subject) if subject else 'input'}."
    if role is InsightRole.RENDERER:
        rendered = _subject_text(subject) if subject else "output"
        if subject and any(token in _OUTPUT_FORMATS for token in subject):
            rendered = f"{rendered} output"
        return f"Render {rendered}."
    if role is InsightRole.EXPORTER:
        return f"Export {_subject_text(subject) if subject else 'data'}."
    if role is InsightRole.LOADER:
        return f"Load {_with_article(subject) if subject else 'data'}."
    if role is InsightRole.READER:
        return f"Read {_with_article(subject) if subject else 'data'}."
    if role is InsightRole.WRITER:
        return f"Write {_subject_text(subject) if subject else 'data'}."
    if role is InsightRole.VALIDATOR:
        return f"Validate {_with_article(subject) if subject else 'data'}."
    if role is InsightRole.TRANSFORMER:
        return f"Transform {_subject_text(subject) if subject else 'data'}."
    if role is InsightRole.RESOLVER:
        return f"Resolve {_plural_subject(subject)}."
    if role is InsightRole.SCANNER:
        return f"Scan {_with_article(subject) if subject else 'source files'}."
    if role is InsightRole.GRAPH_BUILDER:
        graph_subject = _subject_text(subject) if subject else "graph"
        return f"Build {graph_subject} graph data."
    if role is InsightRole.CONTROLLER:
        controlled = _subject_text(subject) if subject else "component"
        return f"Coordinate {controlled} interactions."
    if role is InsightRole.ADAPTER:
        return f"Adapt {_subject_text(subject) if subject else 'data'}."
    if role is InsightRole.MODEL:
        represented = _subject_text(subject)
        if not represented or represented == "data":
            return "Represent data."
        return f"Represent {represented} data."
    if role is InsightRole.FACTORY:
        created = _subject_text(subject) if subject else ""
        return f"Create {created + ' ' if created else ''}objects."
    if role is InsightRole.UTILITY:
        provided = _subject_text(subject) if subject else "general"
        return f"Provide {provided} utility operations."
    return None


def _structural_unknown(
    facts: ModuleFacts | ClassFacts | CallableFacts,
    evidence: tuple[InsightEvidence, ...],
) -> PurposeResult:
    if isinstance(facts, ModuleFacts):
        parts = []
        support = []
        for code, count, singular in (
            ("function_count", len(facts.functions), "function"),
            ("class_count", len(facts.classes), "class"),
        ):
            if count:
                plural = "classes" if singular == "class" else f"{singular}s"
                parts.append(f"{count} {singular if count == 1 else plural}")
                support.extend(item for item in evidence if item.code == code)
        if parts:
            return PurposeResult(
                text=f"Defines {' and '.join(parts)}.",
                source=PurposeSource.STRUCTURE,
                supporting_evidence=_ordered(support),
            )
    elif isinstance(facts, ClassFacts) and facts.method_count:
        support = tuple(item for item in evidence if item.code == "method_count")
        label = "method" if facts.method_count == 1 else "methods"
        return PurposeResult(
            text=f"Defines {facts.method_count} {label}.",
            source=PurposeSource.STRUCTURE,
            supporting_evidence=_ordered(support),
        )
    return PurposeResult(None)


def generate_purpose(
    facts: ModuleFacts | ClassFacts | CallableFacts,
    classification: RoleClassification,
    evidence: Iterable[InsightEvidence],
) -> PurposeResult:
    """Generate a short purpose without reading or executing analyzed code."""
    normalized = _ordered(evidence)
    documented = _useful_docstring(normalized)
    if documented is not None:
        return documented

    if classification.primary_role is InsightRole.UNKNOWN:
        return _structural_unknown(facts, normalized)

    subject = _subject_tokens(facts, classification.primary_role)
    text = _role_text(classification.primary_role, subject, normalized)
    if text is None:
        return PurposeResult(None)
    naming = tuple(
        item for item in normalized if item.category is EvidenceCategory.NAMING
    )
    return PurposeResult(
        text=_sentence(text),
        source=PurposeSource.ROLE_TEMPLATE,
        supporting_evidence=_ordered((*classification.supporting_evidence, *naming)),
    )
