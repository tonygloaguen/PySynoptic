from __future__ import annotations

import threading
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pysynoptic.gui.ai_explanations import (
    AIExplanationSession,
    configuration_from_fields,
    provider_label,
)
from pysynoptic.gui.insights import (
    InsightCatalog,
    InsightSelection,
    InsightsPanel,
    present_insight,
)
from pysynoptic.insights import (
    CallableInsight,
    FlowExplanation,
    FlowExplanationReliability,
    FlowStep,
    InsightAnalysis,
    InsightConfidence,
    InsightRole,
    PurposeSource,
)
from pysynoptic.insights.ai_explanation import (
    AIExplanationResult,
    AIProviderError,
    DisabledAIExplanationProvider,
    build_ai_explanation_request,
)


def callable_insight() -> CallableInsight:
    return CallableInsight(
        identity="sample::run",
        display_name="run()",
        module="sample",
        path=Path("sample.py"),
        symbol_id="sample.py::run@1:0",
        qualified_name="run",
        kind="function",
        is_async=False,
        source_line=1,
        role=InsightRole.ORCHESTRATOR,
        secondary_roles=(),
        purpose="Coordinate sample work.",
        purpose_source=PurposeSource.ROLE_TEMPLATE,
        confidence=InsightConfidence.HIGH,
    )


def static_explanation() -> FlowExplanation:
    return FlowExplanation(
        callable_identity="sample::run",
        summary="Call work, then return.",
        steps=(FlowStep(1, "call", "Call work().", ("n1",)),),
        decisions=(),
        loops=(),
        exceptions=(),
        outcomes=(),
        reliability=FlowExplanationReliability.HIGH,
        supporting_node_ids=("n1",),
    )


class FakeProvider:
    provider_id = "fake:https://provider.test"
    model = "fake-model"

    def __init__(self, text="AI explains the supplied static facts.") -> None:
        self.text = text
        self.calls = 0

    def rewrite_explanation(self, request):
        self.calls += 1
        return AIExplanationResult(self.text, "fake", self.model)


class ErrorProvider(FakeProvider):
    def rewrite_explanation(self, request):
        self.calls += 1
        raise AIProviderError("AI provider request timed out.")


class SlowProvider(FakeProvider):
    def __init__(self, text="Slow AI result.") -> None:
        super().__init__(text)
        self.started = Event()
        self.release = Event()
        self.finished = Event()

    def rewrite_explanation(self, request):
        self.calls += 1
        self.started.set()
        self.release.wait(5)
        try:
            return AIExplanationResult(self.text, "fake", self.model)
        finally:
            self.finished.set()


def session_with(provider: FakeProvider) -> AIExplanationSession:
    def factory(config):
        if not config.enabled:
            return DisabledAIExplanationProvider()
        return provider

    session = AIExplanationSession(provider_factory=factory)
    session.configure(
        configuration_from_fields(
            "OpenAI-compatible",
            "https://provider.test",
            provider.model,
            "",
        )
    )
    session.set_generation(1)
    return session


def wait_completion(session: AIExplanationSession, request_id: int):
    for _ in range(1000):
        completion = session.poll(request_id)
        if completion is not None:
            return completion
        time.sleep(0.001)
    pytest.fail("AI completion did not arrive")


def request_for_selected():
    return build_ai_explanation_request(callable_insight(), static_explanation())


def explicit_panel(session: AIExplanationSession) -> SimpleNamespace:
    insight = callable_insight()
    return SimpleNamespace(
        _ai_explanations=session,
        _on_configure_ai=None,
        _on_confirm_ai_send=None,
        _current_callable_insight=lambda: insight,
        _current_ai_request=request_for_selected,
        _ai_message="",
        _ai_result=AIExplanationResult("Previous AI text.", "fake", "model"),
        _show_ai_result=True,
        _render_ai_controls=Mock(),
        _render_presentation=Mock(),
        _pending_ai_request_id=None,
        _ai_busy=False,
        after=Mock(),
        _poll_ai_explanation=Mock(),
        selected_callable_symbol_id=insight.symbol_id,
        _presentation=SimpleNamespace(
            callable_symbol_id=insight.symbol_id,
            flow_explanation=static_explanation(),
        ),
    )


def test_ai_control_contract_is_visible_and_disabled_by_default() -> None:
    session = AIExplanationSession()

    assert not session.enabled
    assert provider_label(session.config.kind) == "Disabled"
    assert hasattr(InsightsPanel, "_improve_with_ai")


def test_callable_selection_performs_no_provider_call() -> None:
    provider = FakeProvider()
    session = session_with(provider)
    insight = callable_insight()
    analysis = InsightAnalysis((), (), (insight,))
    panel = SimpleNamespace(
        _catalog=InsightCatalog(analysis),
        _selection=None,
        _presentation=None,
        _analysis=analysis,
        _flow_explanations=SimpleNamespace(
            get=Mock(return_value=SimpleNamespace(explanation=static_explanation()))
        ),
        _ai_explanations=session,
        _selected_step_node_ids=None,
        _show_ai_result=False,
        _ai_result=None,
        _ai_busy=False,
        _ai_message="",
        _render_presentation=Mock(),
        selected_callable_symbol_id=None,
    )

    assert InsightsPanel.select(panel, "callable", insight.identity)
    assert provider.calls == 0
    panel._render_presentation.assert_called_once()


def test_explicit_improve_click_triggers_provider() -> None:
    provider = FakeProvider()
    session = session_with(provider)
    session.confirm_current_endpoint()
    insight = callable_insight()
    panel = SimpleNamespace(
        _ai_explanations=session,
        _on_configure_ai=None,
        _on_confirm_ai_send=None,
        _current_callable_insight=lambda: insight,
        _current_ai_request=request_for_selected,
        _ai_message="",
        _render_ai_controls=Mock(),
        _pending_ai_request_id=None,
        _ai_busy=False,
        after=Mock(),
        _poll_ai_explanation=Mock(),
    )

    InsightsPanel._improve_with_ai(panel)
    wait_completion(session, panel._pending_ai_request_id)

    assert provider.calls == 1
    panel.after.assert_called_once()


def test_slow_provider_does_not_block_tk_callback() -> None:
    provider = SlowProvider()
    session = session_with(provider)
    session.confirm_current_endpoint()
    panel = explicit_panel(session)

    started = time.perf_counter()
    InsightsPanel._improve_with_ai(panel)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.05
    assert provider.started.wait(1)
    assert panel._ai_busy
    provider.release.set()
    assert provider.finished.wait(1)


def test_static_remains_visible_while_slow_request_is_active() -> None:
    provider = SlowProvider()
    session = session_with(provider)
    session.confirm_current_endpoint()
    panel = explicit_panel(session)
    static = panel._presentation.flow_explanation

    InsightsPanel._improve_with_ai(panel)

    assert provider.started.wait(1)
    assert not panel._show_ai_result
    assert panel._presentation.flow_explanation is static
    assert panel._ai_message == "Generating…"
    provider.release.set()
    assert provider.finished.wait(1)


def test_second_click_during_request_does_not_launch_duplicate() -> None:
    provider = SlowProvider()
    session = session_with(provider)
    session.confirm_current_endpoint()
    panel = explicit_panel(session)

    InsightsPanel._improve_with_ai(panel)
    assert provider.started.wait(1)
    first_request_id = panel._pending_ai_request_id
    InsightsPanel._improve_with_ai(panel)

    assert panel._pending_ai_request_id == first_request_id
    assert provider.calls == 1
    provider.release.set()
    assert provider.finished.wait(1)


def test_async_success_is_displayed_after_polling() -> None:
    provider = SlowProvider()
    session = session_with(provider)
    session.confirm_current_endpoint()
    panel = explicit_panel(session)

    InsightsPanel._improve_with_ai(panel)
    assert provider.started.wait(1)
    provider.release.set()
    assert provider.finished.wait(1)
    InsightsPanel._poll_ai_explanation(panel)

    assert panel._ai_result.text == "Slow AI result."
    assert panel._show_ai_result
    assert not panel._ai_busy


def test_async_result_for_callable_a_never_overwrites_callable_b() -> None:
    provider = SlowProvider()
    session = session_with(provider)
    session.confirm_current_endpoint()
    panel = explicit_panel(session)

    InsightsPanel._improve_with_ai(panel)
    assert provider.started.wait(1)
    panel.selected_callable_symbol_id = "sample.py::other@2:0"
    panel._ai_result = None
    provider.release.set()
    assert provider.finished.wait(1)
    InsightsPanel._poll_ai_explanation(panel)

    assert panel._ai_result is None
    assert panel._ai_message == ""
    assert (
        session.peek(callable_insight().symbol_id, request_for_selected()) is not None
    )


def test_previous_analysis_generation_result_is_rejected() -> None:
    provider = SlowProvider()
    session = session_with(provider)
    request_id = session.submit(callable_insight().symbol_id, request_for_selected())
    assert provider.started.wait(1)

    session.set_generation(2)
    provider.release.set()
    assert provider.finished.wait(1)

    assert session.poll(request_id) is None
    assert session.cache_size == 0


def test_previous_provider_configuration_result_is_rejected() -> None:
    first = SlowProvider()
    second = FakeProvider()

    def factory(config):
        if not config.enabled:
            return DisabledAIExplanationProvider()
        return first if config.model == "first-model" else second

    session = AIExplanationSession(provider_factory=factory)
    first.model = "first-model"
    session.configure(
        configuration_from_fields(
            "OpenAI-compatible",
            "https://first.test",
            "first-model",
            "",
        )
    )
    session.set_generation(1)
    request_id = session.submit(callable_insight().symbol_id, request_for_selected())
    assert first.started.wait(1)

    session.configure(
        configuration_from_fields(
            "OpenAI-compatible",
            "https://second.test",
            second.model,
            "",
        )
    )
    first.release.set()
    assert first.finished.wait(1)

    assert session.poll(request_id) is None
    assert second.calls == 0


def test_async_non_timeout_error_keeps_static_available() -> None:
    class FailureProvider(FakeProvider):
        def rewrite_explanation(self, request):
            self.calls += 1
            raise AIProviderError("AI provider could not be reached.")

    session = session_with(FailureProvider())
    session.confirm_current_endpoint()
    panel = explicit_panel(session)
    static = panel._presentation.flow_explanation

    InsightsPanel._improve_with_ai(panel)
    for _ in range(1000):
        completion = session.poll(panel._pending_ai_request_id)
        if completion is not None:
            panel._ai_explanations = SimpleNamespace(
                closed=False,
                poll=Mock(return_value=completion),
            )
            break
        time.sleep(0.001)
    InsightsPanel._poll_ai_explanation(panel)

    assert panel._presentation.flow_explanation is static
    assert not panel._show_ai_result
    assert panel._ai_message.startswith("AI explanation unavailable:")
    assert not panel._ai_busy


def test_closing_with_active_request_does_not_wait_for_network_worker() -> None:
    provider = SlowProvider()
    session = session_with(provider)
    request_id = session.submit(callable_insight().symbol_id, request_for_selected())
    assert provider.started.wait(1)

    started = time.perf_counter()
    session.shutdown()
    elapsed = time.perf_counter() - started

    assert elapsed < 0.05
    assert session.closed
    provider.release.set()
    assert provider.finished.wait(1)
    assert session.poll(request_id) is None
    for _ in range(1000):
        if not any(
            thread.name.startswith("pysynoptic-ai-") for thread in threading.enumerate()
        ):
            break
        time.sleep(0.001)
    assert not any(
        thread.name.startswith("pysynoptic-ai-") for thread in threading.enumerate()
    )


def test_cache_hit_creates_no_worker_and_makes_no_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider()
    session = session_with(provider)
    request = request_for_selected()
    first = session.submit(callable_insight().symbol_id, request)
    wait_completion(session, first)

    def forbidden_thread(*_args, **_kwargs):
        raise AssertionError("cache hit created a worker")

    monkeypatch.setattr(
        "pysynoptic.gui.ai_explanations.threading.Thread",
        forbidden_thread,
    )
    second = session.submit(callable_insight().symbol_id, request)
    completion = wait_completion(session, second)

    assert completion.cache_hit
    assert provider.calls == 1


def test_static_explanation_object_is_unchanged_after_ai_result() -> None:
    insight = callable_insight()
    static = static_explanation()
    presentation = present_insight(
        InsightSelection("callable", insight.identity), insight, static
    )
    panel = SimpleNamespace(
        _presentation=presentation,
        _ai_result=AIExplanationResult("AI text.", "fake", "model"),
    )

    assert InsightsPanel.flow_explanation.fget(panel) is static
    assert InsightsPanel.flow_explanation.fget(panel).summary == (
        "Call work, then return."
    )


def test_ai_text_is_available_separately_from_static_text() -> None:
    panel = SimpleNamespace(_ai_result=AIExplanationResult("AI text.", "fake", "model"))

    assert InsightsPanel.ai_explanation_text.fget(panel) == "AI text."


def test_static_to_ai_switch_changes_only_display_mode() -> None:
    panel = SimpleNamespace(
        _ai_result=AIExplanationResult("AI text.", "fake", "model"),
        _show_ai_result=False,
        _render_presentation=Mock(),
    )

    InsightsPanel._show_ai_explanation(panel)

    assert panel._show_ai_result
    panel._render_presentation.assert_called_once()


def test_ai_to_static_switch_changes_only_display_mode() -> None:
    panel = SimpleNamespace(_show_ai_result=True, _render_presentation=Mock())

    InsightsPanel._show_static_explanation(panel)

    assert not panel._show_ai_result
    panel._render_presentation.assert_called_once()


def test_provider_error_keeps_static_explanation_available() -> None:
    provider = ErrorProvider()
    session = session_with(provider)
    request_id = session.submit(callable_insight().symbol_id, request_for_selected())
    completion = wait_completion(session, request_id)
    static = static_explanation()
    panel = SimpleNamespace(
        _pending_ai_request_id=request_id,
        _ai_explanations=SimpleNamespace(
            closed=False,
            poll=Mock(return_value=completion),
        ),
        _ai_busy=True,
        _ai_message="",
        _show_ai_result=True,
        _presentation=SimpleNamespace(
            callable_symbol_id=callable_insight().symbol_id,
            flow_explanation=static,
        ),
        _render_presentation=Mock(),
        selected_callable_symbol_id=callable_insight().symbol_id,
    )

    InsightsPanel._poll_ai_explanation(panel)

    assert not panel._show_ai_result
    assert "timed out" in panel._ai_message
    assert panel._presentation.flow_explanation is static


def test_completion_for_previous_callable_does_not_change_current_message() -> None:
    completion = SimpleNamespace(
        symbol_id="old-symbol",
        error_message="old failure",
        result=None,
        cache_hit=False,
    )
    panel = SimpleNamespace(
        _pending_ai_request_id=7,
        _ai_explanations=SimpleNamespace(
            closed=False,
            poll=Mock(return_value=completion),
        ),
        _ai_busy=True,
        _ai_message="Generating…",
        _show_ai_result=False,
        _render_presentation=Mock(),
        selected_callable_symbol_id="new-symbol",
    )

    InsightsPanel._poll_ai_explanation(panel)

    assert panel._ai_message == ""
    panel._render_presentation.assert_called_once()


def test_second_explicit_request_uses_memory_cache() -> None:
    provider = FakeProvider()
    session = session_with(provider)
    request = request_for_selected()

    first = session.submit(callable_insight().symbol_id, request)
    assert not wait_completion(session, first).cache_hit
    second = session.submit(callable_insight().symbol_id, request)
    assert wait_completion(session, second).cache_hit

    assert provider.calls == 1


def test_new_analysis_generation_invalidates_gui_cache() -> None:
    provider = FakeProvider()
    session = session_with(provider)
    request = request_for_selected()
    request_id = session.submit(callable_insight().symbol_id, request)
    wait_completion(session, request_id)

    session.set_generation(2)

    assert session.cache_size == 0
    assert session.peek(callable_insight().symbol_id, request) is None


def test_module_and_class_selection_cannot_build_ai_request() -> None:
    panel = SimpleNamespace(
        _selection=InsightSelection("module", "sample"),
        _catalog=SimpleNamespace(find=Mock(return_value=object())),
    )

    assert InsightsPanel._current_callable_insight(panel) is None


def test_existing_calls_flow_and_key_step_callbacks_are_unchanged() -> None:
    calls = Mock()
    flow = Mock()
    step = Mock()
    panel = SimpleNamespace(
        selected_callable_symbol_id="symbol",
        _on_show_calls=calls,
        _on_open_flow=flow,
        _on_open_flow_step=step,
        _flow_step_links={"step": ("n1", "n2")},
        _selected_step_node_ids=None,
    )

    InsightsPanel._show_calls(panel)
    InsightsPanel._open_flow(panel)
    InsightsPanel._open_flow_step(panel, "step")

    calls.assert_called_once_with("symbol")
    flow.assert_called_once_with("symbol")
    step.assert_called_once_with("symbol", ("n1", "n2"))


def test_privacy_confirmation_is_required_once_per_endpoint() -> None:
    session = session_with(FakeProvider())

    assert session.needs_privacy_confirmation()
    session.confirm_current_endpoint()
    assert not session.needs_privacy_confirmation()

    session.configure(
        configuration_from_fields(
            "OpenAI-compatible",
            "https://different-provider.test",
            "fake-model",
            "",
        )
    )
    assert session.needs_privacy_confirmation()


def test_clean_shutdown_rejects_new_ai_work() -> None:
    session = session_with(FakeProvider())

    session.shutdown()

    assert session.closed
    with pytest.raises(RuntimeError, match="closed"):
        session.submit(callable_insight().symbol_id, request_for_selected())
