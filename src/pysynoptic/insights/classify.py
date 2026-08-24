"""Conservative deterministic role classification from Evidence only."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pysynoptic.insights.models import (
    EvidenceCategory,
    InsightEvidence,
    InsightRole,
    RoleClassification,
    RoleSupport,
)

_ROLE_PRIORITY = {
    role: index
    for index, role in enumerate(
        (
            InsightRole.MODEL,
            InsightRole.PARSER,
            InsightRole.RESOLVER,
            InsightRole.RENDERER,
            InsightRole.EXPORTER,
            InsightRole.LOADER,
            InsightRole.READER,
            InsightRole.WRITER,
            InsightRole.SCANNER,
            InsightRole.GRAPH_BUILDER,
            InsightRole.VALIDATOR,
            InsightRole.ANALYZER,
            InsightRole.TRANSFORMER,
            InsightRole.FACTORY,
            InsightRole.CONTROLLER,
            InsightRole.ADAPTER,
            InsightRole.ORCHESTRATOR,
            InsightRole.UTILITY,
        )
    )
}
_SECONDARY_COMPATIBILITY = {
    frozenset((InsightRole.RENDERER, InsightRole.EXPORTER)),
    frozenset((InsightRole.ANALYZER, InsightRole.ORCHESTRATOR)),
    frozenset((InsightRole.ANALYZER, InsightRole.GRAPH_BUILDER)),
    frozenset((InsightRole.ANALYZER, InsightRole.VALIDATOR)),
    frozenset((InsightRole.LOADER, InsightRole.READER)),
    frozenset((InsightRole.PARSER, InsightRole.LOADER)),
    frozenset((InsightRole.CONTROLLER, InsightRole.ORCHESTRATOR)),
}
_STRUCTURED_TYPE_TERMS = {
    "analysis",
    "dict",
    "graph",
    "identity",
    "list",
    "mapping",
    "model",
    "project",
    "resolution",
    "result",
    "sequence",
    "set",
    "tuple",
}


def _evidence_key(item: InsightEvidence) -> tuple[str, str, str, str, int, str]:
    return (
        item.category.value,
        item.code,
        item.description,
        item.reference or "",
        item.source_line if item.source_line is not None else -1,
        item.strength.value,
    )


def _normalize(evidence: Iterable[InsightEvidence]) -> tuple[InsightEvidence, ...]:
    return tuple(sorted(set(evidence), key=_evidence_key))


@dataclass(frozen=True, slots=True)
class _Candidate:
    role: InsightRole
    score: int
    evidence: tuple[InsightEvidence, ...]


class _Index:
    def __init__(self, evidence: tuple[InsightEvidence, ...]) -> None:
        self.evidence = evidence

    def exact(self, code: str) -> tuple[InsightEvidence, ...]:
        return tuple(item for item in self.evidence if item.code == code)

    def prefix(self, prefix: str) -> tuple[InsightEvidence, ...]:
        return tuple(item for item in self.evidence if item.code.startswith(prefix))

    def category(self, category: EvidenceCategory) -> tuple[InsightEvidence, ...]:
        return tuple(item for item in self.evidence if item.category is category)

    def tokens(self, *tokens: str) -> tuple[InsightEvidence, ...]:
        codes = {f"name_token:{token}" for token in tokens}
        return tuple(item for item in self.evidence if item.code in codes)

    def references_containing(
        self,
        prefix: str,
        *terms: str,
    ) -> tuple[InsightEvidence, ...]:
        lowered = tuple(term.casefold() for term in terms)
        return tuple(
            item
            for item in self.prefix(prefix)
            if item.reference
            and any(term in item.reference.casefold() for term in lowered)
        )

    def return_annotation(self, *terms: str) -> tuple[InsightEvidence, ...]:
        lowered = tuple(term.casefold() for term in terms)
        return tuple(
            item
            for item in self.exact("return_annotation")
            if item.reference
            and any(term in item.reference.casefold() for term in lowered)
        )

    def parameters(self, *names: str) -> tuple[InsightEvidence, ...]:
        expected = {name.casefold() for name in names}
        return tuple(
            item
            for item in self.prefix("parameter:")
            if item.reference and item.reference.casefold() in expected
        )


class _Score:
    def __init__(self, role: InsightRole) -> None:
        self.role = role
        self.value = 0
        self.evidence: list[InsightEvidence] = []

    def add(self, points: int, evidence: Iterable[InsightEvidence]) -> bool:
        items = tuple(evidence)
        if not items:
            return False
        self.value += points
        self.evidence.extend(items)
        return True

    def candidate(self, threshold: int, *, valid: bool = True) -> _Candidate | None:
        if not valid or self.value < threshold:
            return None
        return _Candidate(self.role, self.value, _normalize(self.evidence))


def _has_structured_return(index: _Index) -> tuple[InsightEvidence, ...]:
    return index.return_annotation(*sorted(_STRUCTURED_TYPE_TERMS))


def _has_structured_parameters(index: _Index) -> tuple[InsightEvidence, ...]:
    return tuple(
        item
        for item in index.prefix("parameter_annotation:")
        if item.reference
        and any(term in item.reference.casefold() for term in _STRUCTURED_TYPE_TERMS)
    )


def _parser(index: _Index) -> _Candidate | None:
    score = _Score(InsightRole.PARSER)
    name = index.tokens("parse", "parser")
    formats = index.tokens("csv", "html", "ini", "json", "toml", "xml", "yaml")
    path_input = index.parameters("data", "path", "source", "text", "xml_path")
    structured_return = _has_structured_return(index)
    loop = index.exact("loop_count")
    branch = index.exact("branch_count")
    try_blocks = index.exact("try_block_count")
    related_calls = index.references_containing(
        "calls:", "decode", "get_text", "load", "parse"
    )
    score.add(2, name)
    score.add(2, formats)
    score.add(1, path_input)
    score.add(2, structured_return)
    score.add(2, loop)
    score.add(1, branch)
    score.add(1, try_blocks)
    score.add(1, related_calls)
    context_count = sum(
        bool(items)
        for items in (
            formats,
            path_input,
            structured_return,
            loop,
            branch,
            related_calls,
        )
    )
    return score.candidate(6, valid=bool(name) and context_count >= 2)


def _renderer(index: _Index) -> _Candidate | None:
    score = _Score(InsightRole.RENDERER)
    name = index.tokens("format", "render", "renderer", "serialize")
    formats = index.tokens(
        "csv", "html", "json", "markdown", "powershell", "text", "xml", "yaml"
    )
    text_return = index.return_annotation("bytes", "str", "string", "text")
    loop = index.exact("loop_count")
    branch = index.exact("branch_count")
    related_calls = index.references_containing(
        "calls:", "escape", "format", "render", "serialize"
    )
    score.add(2, name)
    score.add(2, formats)
    score.add(3, text_return)
    score.add(1, loop)
    score.add(1, branch)
    score.add(1, related_calls)
    context = (
        bool(text_return) or bool(formats) and bool(loop or branch or related_calls)
    )
    return score.candidate(6, valid=bool(name) and context)


def _exporter(index: _Index) -> _Candidate | None:
    score = _Score(InsightRole.EXPORTER)
    name = index.tokens("dump", "export", "save", "write")
    formats = index.tokens("csv", "html", "json", "markdown", "xml", "yaml")
    writes = tuple(
        item
        for item in index.category(EvidenceCategory.FILESYSTEM)
        if "write" in item.code or "open" in item.code
    )
    structured_input = _has_structured_parameters(index)
    score.add(2, name)
    score.add(1, formats)
    score.add(4, writes)
    score.add(1, structured_input)
    return score.candidate(6, valid=bool(writes) and bool(name or formats))


def _writer(index: _Index) -> _Candidate | None:
    score = _Score(InsightRole.WRITER)
    name = index.tokens("save", "write", "writer")
    writes = tuple(
        item
        for item in index.category(EvidenceCategory.FILESYSTEM)
        if "write" in item.code or "open" in item.code
    )
    score.add(2, name)
    score.add(4, writes)
    score.add(1, index.exact("returns_none_explicitly"))
    return score.candidate(6, valid=bool(name) and bool(writes))


def _loader_or_reader(index: _Index, role: InsightRole) -> _Candidate | None:
    score = _Score(role)
    token = "load" if role is InsightRole.LOADER else "read"
    name = index.tokens(token, f"{token}er")
    reads = tuple(
        item
        for item in index.category(EvidenceCategory.FILESYSTEM)
        if "read" in item.code or "open" in item.code
    )
    score.add(2, name)
    score.add(3, reads)
    score.add(1, index.parameters("file", "path", "source"))
    score.add(2, _has_structured_return(index) or index.exact("returns_value_syntax"))
    return score.candidate(6, valid=bool(name) and bool(reads))


def _analyzer(index: _Index) -> _Candidate | None:
    score = _Score(InsightRole.ANALYZER)
    name = index.tokens("analysis", "analyze", "analyzer", "inspect")
    loops = index.exact("loop_count")
    branches = index.exact("branch_count")
    calls = index.prefix("calls:")
    analysis_calls = index.references_containing("calls:", "analyze", "resolve", "scan")
    score.add(2, name)
    score.add(2, loops)
    score.add(1, branches)
    score.add(2, _has_structured_return(index))
    score.add(2, calls if len(calls) >= 2 else ())
    score.add(1, analysis_calls)
    score.add(1, index.exact("returns_value_syntax"))
    context = bool(loops or branches or analysis_calls or len(calls) >= 2)
    return score.candidate(6, valid=bool(name) and context)


def _resolver(index: _Index) -> _Candidate | None:
    score = _Score(InsightRole.RESOLVER)
    name = index.tokens("resolution", "resolve", "resolver")
    branches = index.exact("branch_count")
    relevant_return = index.return_annotation(
        "identity", "resolution", "target", "tuple"
    )
    parameters = index.parameters("identity", "name", "reference", "target")
    related_calls = index.references_containing("calls:", "resolve")
    score.add(2, name)
    score.add(3, branches)
    score.add(2, relevant_return)
    score.add(1, parameters)
    score.add(1, related_calls)
    return score.candidate(
        6,
        valid=bool(name) and bool(branches or relevant_return),
    )


def _scanner(index: _Index) -> _Candidate | None:
    score = _Score(InsightRole.SCANNER)
    name = index.tokens("discover", "scan", "scanner", "walk")
    loops = index.exact("loop_count")
    branches = index.exact("branch_count")
    related_calls = index.references_containing("calls:", "discover", "scan", "walk")
    score.add(2, name)
    score.add(2, loops)
    score.add(1, branches)
    score.add(1, index.parameters("directory", "path", "root", "source"))
    score.add(2, _has_structured_return(index))
    score.add(1, index.category(EvidenceCategory.FILESYSTEM))
    score.add(1, index.prefix("calls:"))
    score.add(2, related_calls)
    return score.candidate(6, valid=bool(name) and bool(loops or related_calls))


def _validator(index: _Index) -> _Candidate | None:
    score = _Score(InsightRole.VALIDATOR)
    name = index.tokens("check", "validate", "validator", "verify")
    branches = index.exact("branch_count")
    raises = index.exact("raise_statement_count")
    bool_return = index.return_annotation("bool")
    exceptions = index.category(EvidenceCategory.EXCEPTIONS)
    score.add(2, name)
    score.add(2, branches)
    score.add(2, raises)
    score.add(2, bool_return)
    score.add(1, exceptions)
    context_count = sum(bool(items) for items in (branches, raises, bool_return))
    return score.candidate(6, valid=bool(name) and context_count >= 2)


def _transformer(index: _Index) -> _Candidate | None:
    score = _Score(InsightRole.TRANSFORMER)
    name = index.tokens("convert", "map", "normalize", "transform", "transformer")
    structured_input = _has_structured_parameters(index)
    structured_return = _has_structured_return(index)
    operations = tuple(
        item
        for category in (
            EvidenceCategory.FILESYSTEM,
            EvidenceCategory.PROCESS,
            EvidenceCategory.NETWORK,
        )
        for item in index.category(category)
    )
    score.add(2, name)
    score.add(1, structured_input)
    score.add(2, structured_return)
    score.add(1, index.exact("returns_value_syntax"))
    return score.candidate(
        6,
        valid=bool(name)
        and bool(structured_input)
        and bool(structured_return)
        and not operations,
    )


def _graph_builder(index: _Index) -> _Candidate | None:
    score = _Score(InsightRole.GRAPH_BUILDER)
    build_name = index.tokens("build", "builder", "layout")
    graph_name = index.tokens("edge", "graph", "node")
    graph_return = index.return_annotation("edge", "graph", "layout", "node")
    graph_calls = index.references_containing(
        "calls:", "edge", "graph", "layout", "node"
    )
    score.add(2, build_name)
    score.add(2, graph_name)
    score.add(3, graph_return)
    score.add(2, graph_calls)
    score.add(1, index.exact("loop_count") or index.exact("branch_count"))
    context = bool(graph_return or graph_calls or graph_name)
    return score.candidate(6, valid=bool(build_name) and context)


def _factory(index: _Index) -> _Candidate | None:
    score = _Score(InsightRole.FACTORY)
    name = index.tokens("create", "factory", "make")
    return_annotation = index.exact("return_annotation")
    score.add(2, name)
    score.add(2, return_annotation)
    score.add(2, index.exact("branch_count"))
    score.add(1, index.prefix("calls:") if len(index.prefix("calls:")) >= 2 else ())
    score.add(1, index.exact("returns_value_syntax"))
    return score.candidate(
        6,
        valid=bool(name) and bool(return_annotation),
    )


def _controller(index: _Index) -> _Candidate | None:
    score = _Score(InsightRole.CONTROLLER)
    name = index.tokens("control", "controller")
    calls = index.prefix("calls:")
    context_parameters = index.parameters("action", "state", "view")
    score.add(2, name)
    score.add(3, calls if len(calls) >= 3 else ())
    score.add(1, context_parameters)
    return score.candidate(
        6,
        valid=bool(name) and len(calls) >= 3 and bool(context_parameters),
    )


def _adapter(index: _Index) -> _Candidate | None:
    score = _Score(InsightRole.ADAPTER)
    name = index.tokens("adapt", "adapter")
    structured_input = _has_structured_parameters(index)
    structured_return = _has_structured_return(index)
    score.add(2, name)
    score.add(1, structured_input)
    score.add(2, structured_return)
    score.add(1, index.prefix("calls:"))
    score.add(1, index.exact("returns_value_syntax"))
    return score.candidate(
        6,
        valid=bool(name) and bool(structured_input) and bool(structured_return),
    )


def _orchestrator(index: _Index) -> _Candidate | None:
    score = _Score(InsightRole.ORCHESTRATOR)
    calls = index.prefix("calls:")
    name = index.tokens("execute", "main", "process", "run")
    module_caller = tuple(
        item
        for item in index.prefix("called_by:")
        if item.reference and item.reference.endswith("::<module>")
    )
    called_modules = {
        item.reference.partition("::")[0]
        for item in calls
        if item.reference and "::" in item.reference
    }
    distributed_calls = len(calls) >= 5 and len(called_modules) >= 2
    if len(calls) >= 5:
        score.add(6, calls)
    elif len(calls) == 4:
        score.add(5, calls)
    elif len(calls) == 3:
        score.add(4, calls)
    score.add(1, name)
    score.add(1, module_caller)
    score.add(1, index.exact("returns_value_syntax"))
    context = bool(name or module_caller or distributed_calls)
    return score.candidate(6, valid=len(calls) >= 3 and context)


def _model(index: _Index) -> _Candidate | None:
    score = _Score(InsightRole.MODEL)
    dataclass = index.exact("dataclass_decorator")
    variables = index.prefix("class_variable:")
    method_count = index.exact("method_count")
    async_methods = index.prefix("async_method:")
    count = None
    if method_count:
        words = method_count[0].description.split()
        count = next((int(word) for word in words if word.isdigit()), None)
    score.add(4, dataclass)
    score.add(2, variables)
    if count is None or count <= 2:
        score.add(1, method_count)
    complex_behavior = bool(async_methods) or count is not None and count > 3
    return score.candidate(
        6,
        valid=bool(dataclass) and bool(variables) and not complex_behavior,
    )


def _candidates(index: _Index) -> tuple[_Candidate, ...]:
    candidates = tuple(
        candidate
        for candidate in (
            _orchestrator(index),
            _analyzer(index),
            _parser(index),
            _renderer(index),
            _exporter(index),
            _loader_or_reader(index, InsightRole.LOADER),
            _loader_or_reader(index, InsightRole.READER),
            _writer(index),
            _validator(index),
            _transformer(index),
            _resolver(index),
            _scanner(index),
            _graph_builder(index),
            _controller(index),
            _adapter(index),
            _model(index),
            _factory(index),
        )
        if candidate is not None
    )
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                -item.score,
                _ROLE_PRIORITY[item.role],
                item.role.value,
            ),
        )
    )


def classify_evidence(evidence: Iterable[InsightEvidence]) -> RoleClassification:
    """Classify a role from Evidence, returning UNKNOWN when support is weak."""
    normalized = _normalize(evidence)
    candidates = _candidates(_Index(normalized))
    if not candidates:
        return RoleClassification(primary_role=InsightRole.UNKNOWN)

    primary = candidates[0]
    secondary = tuple(
        candidate
        for candidate in candidates[1:]
        if candidate.score >= primary.score - 2
        and frozenset((primary.role, candidate.role)) in _SECONDARY_COMPATIBILITY
    )[:2]
    return RoleClassification(
        primary_role=primary.role,
        secondary_roles=tuple(item.role for item in secondary),
        supporting_evidence=primary.evidence,
        secondary_support=tuple(
            RoleSupport(role=item.role, evidence=item.evidence) for item in secondary
        ),
    )
