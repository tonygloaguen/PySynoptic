from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from urllib import error

import pytest

from pysynoptic.gui.controller import ApplicationController
from pysynoptic.gui.flow_explanations import FlowExplanationCache
from pysynoptic.insights import (
    CallableInsight,
    FlowDecision,
    FlowException,
    FlowExplanation,
    FlowExplanationReliability,
    FlowLoop,
    FlowOutcome,
    FlowStep,
    InsightAnalysis,
    InsightConfidence,
    InsightRole,
    PurposeSource,
)
from pysynoptic.insights.ai_explanation import (
    MAX_AI_REQUEST_CHARS,
    MAX_HTTP_RESPONSE_BYTES,
    AIExplanationDecision,
    AIExplanationDisabledError,
    AIExplanationException,
    AIExplanationLoop,
    AIExplanationOutcome,
    AIExplanationRequest,
    AIExplanationResult,
    AIExplanationService,
    AIExplanationStep,
    AIProviderConfig,
    AIProviderError,
    AIProviderKind,
    AIResolvedCallee,
    AIResponseError,
    DisabledAIExplanationProvider,
    OllamaCompatibleProvider,
    OpenAICompatibleProvider,
    UrllibJSONTransport,
    build_ai_explanation_request,
    build_ai_prompt,
    is_local_endpoint,
    normalize_ai_explanation_request,
    provider_from_config,
    request_hash,
    request_payload,
    validate_ai_text,
)


def callable_insight(**changes) -> CallableInsight:
    values = {
        "identity": "sample::render_report",
        "display_name": "render_report()",
        "module": "sample",
        "path": Path("sample.py"),
        "symbol_id": "sample.py::render_report@1:0",
        "qualified_name": "render_report",
        "kind": "function",
        "is_async": False,
        "source_line": 1,
        "role": InsightRole.RENDERER,
        "secondary_roles": (),
        "purpose": "Render report output.",
        "purpose_source": PurposeSource.ROLE_TEMPLATE,
        "confidence": InsightConfidence.HIGH,
        "responsibilities": (),
        "inputs": (),
        "outputs": ("str",),
        "side_effects": (),
        "callers": (),
        "callees": ("sample::write_report", "sample::prepare"),
        "evidence": (),
        "supporting_evidence": (),
    }
    values.update(changes)
    return CallableInsight(**values)


def flow_explanation(**changes) -> FlowExplanation:
    nested = FlowStep(1, "call", "Call prepare().", ("n2",))
    values = {
        "callable_identity": "sample::render_report",
        "summary": "Build a report, then return it.",
        "steps": (
            FlowStep(1, "statement", "Build the report.", ("n1",), (nested,)),
            FlowStep(2, "return", "Return the report.", ("n3",)),
        ),
        "decisions": (
            FlowDecision(
                "output is empty",
                (FlowStep(1, "return", "Return an empty report.", ("n4",)),),
                (FlowStep(1, "statement", "Keep the report.", ("n5",)),),
                ("n4", "n5"),
            ),
        ),
        "loops": (
            FlowLoop(
                "For each item",
                "Append the rendered item.",
                (FlowStep(1, "call", "Call render_item().", ("n6",)),),
                ("n6",),
            ),
        ),
        "exceptions": (
            FlowException(
                "Write the report.",
                ("Handle OSError.",),
                "Close the output.",
                ("n7",),
            ),
        ),
        "outcomes": (FlowOutcome("return", "Return the report.", ("n3",)),),
        "reliability": FlowExplanationReliability.HIGH,
        "supporting_node_ids": ("n1", "n2", "n3"),
    }
    values.update(changes)
    return FlowExplanation(**values)


def insight_analysis() -> InsightAnalysis:
    target = callable_insight()
    prepare = callable_insight(
        identity="sample::prepare",
        display_name="prepare()",
        symbol_id="sample.py::prepare@20:0",
        qualified_name="prepare",
        purpose="Prepare report data.",
        callees=(),
    )
    writer = callable_insight(
        identity="sample::write_report",
        display_name="write_report()",
        symbol_id="sample.py::write_report@30:0",
        qualified_name="write_report",
        purpose="Write report output.",
        callees=(),
    )
    return InsightAnalysis((), (), (target, writer, prepare))


def ai_request(**changes) -> AIExplanationRequest:
    base = build_ai_explanation_request(
        callable_insight(),
        flow_explanation(),
        insight_analysis(),
    )
    return replace(base, **changes)


class FakeTransport:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[tuple[str, object, object, float]] = []

    def post_json(self, url, payload, *, headers, timeout):
        self.calls.append((url, payload, headers, timeout))
        return self.response


class FakeProvider:
    def __init__(self, text: str = "Clear rewritten explanation.", model="fake"):
        self.provider_id = "fake:memory"
        self.model = model
        self.text = text
        self.calls = 0

    def rewrite_explanation(self, request):
        self.calls += 1
        return AIExplanationResult(self.text, "fake", self.model)


def test_ai_disabled_is_default_and_never_rewrites() -> None:
    config = AIProviderConfig()
    provider = provider_from_config(config)

    assert not config.enabled
    assert isinstance(provider, DisabledAIExplanationProvider)
    with pytest.raises(AIExplanationDisabledError):
        provider.rewrite_explanation(ai_request())


def test_request_contains_only_expected_structured_sections() -> None:
    payload = request_payload(ai_request())

    assert tuple(payload) == (
        "callable",
        "role",
        "purpose",
        "static_summary",
        "key_steps",
        "decisions",
        "loops",
        "exceptions",
        "outcomes",
        "resolved_callees",
        "reliability",
    )
    assert "source" not in payload
    assert "path" not in payload


def test_request_does_not_include_raw_source_text() -> None:
    source = "RAW_SENTINEL = 'never transmit this complete source line'"
    encoded = json.dumps(request_payload(ai_request()), ensure_ascii=False)
    prompt = build_ai_prompt(ai_request())

    assert source not in encoded
    assert source not in prompt


def test_request_ordering_and_hash_are_deterministic() -> None:
    first = build_ai_explanation_request(
        callable_insight(callees=("sample::write_report", "sample::prepare")),
        flow_explanation(),
        insight_analysis(),
    )
    second = build_ai_explanation_request(
        callable_insight(callees=("sample::prepare", "sample::write_report")),
        flow_explanation(),
        insight_analysis(),
    )

    assert first == second
    assert request_hash(first) == request_hash(second)
    assert tuple(item.identity for item in first.resolved_callees) == (
        "sample::prepare",
        "sample::write_report",
    )


@pytest.mark.parametrize(
    ("attribute", "expected"),
    [
        ("role", "RENDERER"),
        ("purpose", "Render report output."),
        ("static_summary", "Build a report, then return it."),
        ("steps", "Build the report."),
        ("decisions", "output is empty"),
        ("loops", "For each item"),
        ("exceptions", "Handle OSError."),
        ("outcomes", "Return the report."),
        ("reliability", FlowExplanationReliability.HIGH),
    ],
)
def test_request_includes_each_approved_fact_group(attribute, expected) -> None:
    value = getattr(ai_request(), attribute)

    if isinstance(value, tuple):
        assert expected in repr(value)
    else:
        assert value == expected


def test_unknown_role_and_reliability_are_supported() -> None:
    request = build_ai_explanation_request(
        callable_insight(
            role=InsightRole.UNKNOWN,
            purpose=None,
            confidence=InsightConfidence.UNKNOWN,
        ),
        flow_explanation(reliability=FlowExplanationReliability.UNKNOWN),
    )

    assert request.role == "UNKNOWN"
    assert request.purpose is None
    assert request.reliability is FlowExplanationReliability.UNKNOWN


def test_empty_static_summary_is_supported() -> None:
    request = build_ai_explanation_request(
        callable_insight(),
        flow_explanation(summary=None),
    )

    assert request.static_summary == ""
    assert "Static summary: None available" in build_ai_prompt(request)


def _payload_size(request: AIExplanationRequest) -> int:
    return len(
        json.dumps(
            request_payload(request),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def test_small_request_is_unchanged_by_normalization() -> None:
    request = ai_request()

    assert normalize_ai_explanation_request(request) is request


def _large_collection(field: str, count: int = 300):
    text = "x" * 580
    if field == "steps":
        return tuple(
            AIExplanationStep((index,), "call", f"Step {index} {text}")
            for index in range(count)
        )
    if field == "decisions":
        return tuple(
            AIExplanationDecision(
                f"Decision {index} {text}",
                (f"True {index} {text}",),
                (f"False {index} {text}",),
            )
            for index in range(count)
        )
    if field == "loops":
        return tuple(
            AIExplanationLoop(
                f"Loop {index} {text}",
                f"Body {index} {text}",
                (f"Step {index} {text}",),
            )
            for index in range(count)
        )
    if field == "exceptions":
        return tuple(
            AIExplanationException(
                f"Protected {index} {text}",
                (f"Handler {index} {text}",),
                f"Finally {index} {text}",
            )
            for index in range(count)
        )
    if field == "outcomes":
        return tuple(
            AIExplanationOutcome("return", f"Outcome {index} {text}")
            for index in range(count)
        )
    if field == "resolved_callees":
        return tuple(
            AIResolvedCallee(
                f"sample::callee_{index}",
                f"Purpose {index} {text}",
            )
            for index in range(count)
        )
    raise AssertionError(field)


@pytest.mark.parametrize(
    "field",
    [
        "steps",
        "decisions",
        "loops",
        "exceptions",
        "outcomes",
        "resolved_callees",
    ],
)
def test_large_collection_is_reduced_with_exact_omitted_count(field: str) -> None:
    empty = {
        "steps": (),
        "decisions": (),
        "loops": (),
        "exceptions": (),
        "outcomes": (),
        "resolved_callees": (),
    }
    values = _large_collection(field)
    request = replace(ai_request(), **{**empty, field: values})

    normalized = normalize_ai_explanation_request(request)

    retained = getattr(normalized, field)
    assert retained == values[: len(retained)]
    assert getattr(normalized.omissions, field) == len(values) - len(retained)
    assert getattr(normalized.omissions, field) > 0
    assert len(build_ai_prompt(request)) <= MAX_AI_REQUEST_CHARS
    assert _payload_size(request) <= MAX_AI_REQUEST_CHARS


def test_request_reduction_preserves_every_priority_field() -> None:
    request = replace(
        ai_request(),
        steps=_large_collection("steps"),
        decisions=_large_collection("decisions"),
        loops=_large_collection("loops"),
        exceptions=_large_collection("exceptions"),
        outcomes=_large_collection("outcomes"),
        resolved_callees=_large_collection("resolved_callees"),
    )

    normalized = normalize_ai_explanation_request(request)

    assert normalized.callable_name == request.callable_name
    assert normalized.callable_identity == request.callable_identity
    assert normalized.role == request.role
    assert normalized.purpose == request.purpose
    assert normalized.static_summary == request.static_summary
    assert normalized.reliability is request.reliability
    assert normalized.steps
    assert normalized.omissions.resolved_callees == len(request.resolved_callees)


def test_step_reduction_prioritizes_root_steps_over_nested_detail() -> None:
    text = "x" * 580
    steps = (
        AIExplanationStep((1,), "statement", "First root"),
        *(
            AIExplanationStep((1, index), "call", f"Nested {index} {text}")
            for index in range(1, 300)
        ),
        AIExplanationStep((2,), "return", "Second root"),
    )
    request = replace(
        ai_request(),
        steps=steps,
        decisions=(),
        loops=(),
        exceptions=(),
        outcomes=(),
        resolved_callees=(),
    )

    normalized = normalize_ai_explanation_request(request)

    assert normalized.steps[:2] == (steps[0], steps[-1])
    assert normalized.omissions.steps > 0


def test_omissions_are_provider_visible_structured_counts() -> None:
    request = replace(
        ai_request(), resolved_callees=_large_collection("resolved_callees")
    )
    normalized = normalize_ai_explanation_request(request)
    payload = request_payload(request)

    assert payload["omissions"]["additional_callees_omitted"] == (
        normalized.omissions.resolved_callees
    )
    assert "Additional callees omitted" in build_ai_prompt(request)


def test_normalization_is_exactly_deterministic() -> None:
    request = replace(ai_request(), steps=_large_collection("steps"))

    first = normalize_ai_explanation_request(request)
    second = normalize_ai_explanation_request(request)

    assert first == second
    assert request_payload(first) == request_payload(second)
    assert request_hash(first) == request_hash(second)


def test_same_effective_payload_has_same_request_hash() -> None:
    common = list(_large_collection("steps", 300))
    first = replace(ai_request(), steps=tuple(common))
    changed_tail = [
        replace(item, text=f"Different omitted tail {index}")
        for index, item in enumerate(common)
    ]
    second = replace(
        ai_request(),
        steps=tuple(common[:50] + changed_tail[50:]),
    )

    assert request_payload(first) == request_payload(second)
    assert request_hash(first) == request_hash(second)


def test_normalization_never_reintroduces_redacted_literals() -> None:
    secret = "NEVER_SEND_LITERAL_7f62"
    request = replace(
        ai_request(),
        static_summary=f'Return "{secret}".',
        steps=(AIExplanationStep((1,), "return", f"Return '{secret}'."),),
    )
    normalized = normalize_ai_explanation_request(request)
    serialized = json.dumps(request_payload(normalized), ensure_ascii=False)

    assert secret not in serialized
    assert "<redacted literal>" in serialized


def test_provider_receives_normalized_request_used_by_cache_hash() -> None:
    class CapturingProvider(FakeProvider):
        def rewrite_explanation(self, request):
            self.received = request
            return super().rewrite_explanation(request)

    request = replace(ai_request(), steps=_large_collection("steps"))
    provider = CapturingProvider()
    service = AIExplanationService()

    service.rewrite("symbol", request, provider)

    assert provider.received == normalize_ai_explanation_request(request)
    assert request_hash(provider.received) == request_hash(request)


def test_openai_compatible_fake_success_and_prompt_contract() -> None:
    transport = FakeTransport(
        {"choices": [{"message": {"content": "  Rewritten safely.  "}}]}
    )
    provider = OpenAICompatibleProvider(
        AIProviderConfig(
            AIProviderKind.OPENAI_COMPATIBLE,
            "https://example.test",
            "model-a",
            api_key="secret",
        ),
        transport=transport,
    )

    result = provider.rewrite_explanation(ai_request())

    assert result.text == "Rewritten safely."
    assert result.source == "AI"
    url, payload, headers, _timeout = transport.calls[0]
    assert url == "https://example.test/v1/chat/completions"
    assert headers == {"Authorization": "Bearer secret"}
    assert payload["messages"][0]["role"] == "developer"
    assert "Do not invent business intent" in payload["messages"][0]["content"]


def test_ollama_provider_reuses_transport_with_native_shape() -> None:
    transport = FakeTransport({"message": {"content": "Local rewrite."}})
    provider = OllamaCompatibleProvider(
        AIProviderConfig(
            AIProviderKind.OLLAMA_COMPATIBLE,
            "http://127.0.0.1:11434",
            "local-model",
        ),
        transport=transport,
    )

    result = provider.rewrite_explanation(ai_request())

    assert result.text == "Local rewrite."
    assert transport.calls[0][0] == "http://127.0.0.1:11434/api/chat"
    assert transport.calls[0][2] == {}


def test_provider_endpoint_joining_avoids_duplicate_api_segments() -> None:
    openai_transport = FakeTransport(
        {"choices": [{"message": {"content": "OpenAI-compatible prose."}}]}
    )
    ollama_transport = FakeTransport({"message": {"content": "Local prose."}})
    OpenAICompatibleProvider(
        AIProviderConfig(
            AIProviderKind.OPENAI_COMPATIBLE,
            "https://example.test/v1",
            "model",
        ),
        transport=openai_transport,
    ).rewrite_explanation(ai_request())
    OllamaCompatibleProvider(
        AIProviderConfig(
            AIProviderKind.OLLAMA_COMPATIBLE,
            "http://127.0.0.1:11434/api",
            "model",
        ),
        transport=ollama_transport,
    ).rewrite_explanation(ai_request())

    assert openai_transport.calls[0][0] == ("https://example.test/v1/chat/completions")
    assert ollama_transport.calls[0][0] == "http://127.0.0.1:11434/api/chat"


def test_api_key_never_enters_provider_request_or_cache_key() -> None:
    secret = "never-cache-this-key"
    transport = FakeTransport({"choices": [{"message": {"content": "Safe response."}}]})
    provider = OpenAICompatibleProvider(
        AIProviderConfig(
            AIProviderKind.OPENAI_COMPATIBLE,
            "https://example.test",
            "model",
            api_key=secret,
        ),
        transport=transport,
    )
    service = AIExplanationService()

    service.rewrite("symbol", ai_request(), provider)

    assert secret not in json.dumps(request_payload(ai_request()))
    assert secret not in repr(service._items)
    assert transport.calls[0][2] == {"Authorization": f"Bearer {secret}"}


def test_transport_timeout_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pysynoptic.insights.ai_explanation.providers.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError()),
    )

    with pytest.raises(AIProviderError, match="timed out"):
        UrllibJSONTransport().post_json(
            "https://example.test",
            {},
            headers={"Authorization": "Bearer secret"},
            timeout=0.1,
        )


def test_transport_http_error_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    failure = error.HTTPError("https://example.test", 503, "secret", {}, None)
    monkeypatch.setattr(
        "pysynoptic.insights.ai_explanation.providers.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )

    with pytest.raises(AIProviderError, match="HTTP 503") as captured:
        UrllibJSONTransport().post_json(
            "https://example.test",
            {},
            headers={"Authorization": "Bearer never-show"},
            timeout=1,
        )
    assert "never-show" not in str(captured.value)


def test_transport_rejects_oversized_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OversizedResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, limit):
            assert limit == MAX_HTTP_RESPONSE_BYTES + 1
            return b"x" * limit

    monkeypatch.setattr(
        "pysynoptic.insights.ai_explanation.providers.request.urlopen",
        lambda *_args, **_kwargs: OversizedResponse(),
    )

    with pytest.raises(AIResponseError, match="too large"):
        UrllibJSONTransport().post_json(
            "https://example.test",
            {},
            headers={},
            timeout=1,
        )


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {"content": 42}}]},
        {"choices": [{"message": {"content": ""}}]},
        {"choices": [{"message": {"content": '{"text": "not prose"}'}}]},
    ],
)
def test_invalid_provider_response_is_rejected(response: object) -> None:
    provider = OpenAICompatibleProvider(
        AIProviderConfig(
            AIProviderKind.OPENAI_COMPATIBLE,
            "https://example.test",
            "model-a",
        ),
        transport=FakeTransport(response),
    )

    with pytest.raises(AIResponseError):
        provider.rewrite_explanation(ai_request())


def test_oversized_response_is_rejected() -> None:
    with pytest.raises(AIResponseError, match="2000"):
        validate_ai_text("x" * 2001)


def test_cache_hit_does_not_call_provider_twice() -> None:
    service = AIExplanationService()
    service.set_generation(7)
    provider = FakeProvider()

    first = service.rewrite("symbol", ai_request(), provider)
    second = service.rewrite("symbol", ai_request(), provider)

    assert not first.cache_hit
    assert second.cache_hit
    assert provider.calls == 1


def test_new_generation_invalidates_cache() -> None:
    service = AIExplanationService()
    provider = FakeProvider()
    service.set_generation(1)
    service.rewrite("symbol", ai_request(), provider)

    service.set_generation(2)
    service.rewrite("symbol", ai_request(), provider)

    assert provider.calls == 2
    assert service.size == 1


def test_provider_and_model_separate_cache_entries() -> None:
    service = AIExplanationService()
    first = FakeProvider(model="first")
    second = FakeProvider(model="second")

    service.rewrite("symbol", ai_request(), first)
    service.rewrite("symbol", ai_request(), second)

    assert first.calls == 1
    assert second.calls == 1
    assert service.size == 2


def test_api_key_is_never_exposed_by_configuration_or_errors() -> None:
    secret = "top-secret-api-key"
    config = AIProviderConfig(
        AIProviderKind.OPENAI_COMPATIBLE,
        "https://example.test",
        "model",
        api_key=secret,
    )

    assert secret not in repr(config)
    assert secret not in str(config)


def test_dangerous_source_is_not_executed_or_forwarded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "executed"
    marker.write_text("safe", encoding="utf-8")
    source = tmp_path / "dangerous.py"
    sentinel = "RAW_DELETE_SENTINEL_4d84"
    long_literal = f"{sentinel}-" + ("S" * 5000)
    source_text = (
        "import os\nimport socket\nimport subprocess\n"
        f"os.system('printf bad > {marker}')\n"
        f"subprocess.run(['touch', {str(marker)!r}])\n"
        "socket.create_connection(('malicious.invalid', 443))\n"
        f"os.remove({str(marker)!r})\n"
        "def side_effect():\n"
        f"    open({str(marker)!r}, 'w').write('bad')\n"
        "    return 1\n"
        "@side_effect()\n"
        "def decorated(api_key_suspicious=side_effect()):\n"
        f"    return {long_literal!r}\n"
    )
    source.write_text(source_text, encoding="utf-8")
    controller = ApplicationController()
    state = controller.analyze(controller.select_path(source))
    cache = FlowExplanationCache()
    cache.set_analysis(state.project_analysis, state.insight_analysis)
    insight = next(
        item
        for item in state.insight_analysis.callables
        if item.qualified_name == "decorated"
    )
    static = cache.get(insight.symbol_id)
    provider = FakeProvider()

    def forbidden_read(*_args, **_kwargs):
        raise AssertionError("AI layer reread analyzed source")

    monkeypatch.setattr(Path, "read_text", forbidden_read)

    request = build_ai_explanation_request(
        insight,
        static.explanation,
        state.insight_analysis,
    )
    AIExplanationService().rewrite(insight.symbol_id, request, provider)

    assert marker.read_bytes() == b"safe"
    assert sentinel not in build_ai_prompt(request)
    assert source_text not in build_ai_prompt(request)
    assert provider.calls == 1


def test_provider_construction_and_request_build_make_no_network_call() -> None:
    transport = FakeTransport({"unused": True})
    provider = OpenAICompatibleProvider(
        AIProviderConfig(
            AIProviderKind.OPENAI_COMPATIBLE,
            "https://example.test",
            "model",
        ),
        transport=transport,
    )

    build_ai_explanation_request(callable_insight(), flow_explanation())

    assert provider.model == "model"
    assert transport.calls == []


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("http://localhost:11434", True),
        ("http://127.0.0.1:11434", True),
        ("http://[::1]:11434", True),
        ("https://local-provider.example", False),
        ("https://api.openai.com", False),
    ],
)
def test_only_literal_loopback_endpoints_are_local(
    endpoint: str, expected: bool
) -> None:
    assert is_local_endpoint(endpoint) is expected
