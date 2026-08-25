"""Session-only optional AI rewriting support for the Tk interface."""

from __future__ import annotations

import itertools
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import messagebox

import ttkbootstrap as ttk

from pysynoptic.insights.ai_explanation import (
    AIConfigurationError,
    AIExplanationError,
    AIExplanationProvider,
    AIExplanationRequest,
    AIExplanationResult,
    AIExplanationService,
    AIProviderConfig,
    AIProviderKind,
    StaleAIExplanationError,
    build_ai_explanation_request,
    is_local_endpoint,
    provider_from_config,
)
from pysynoptic.insights.flow_explanation.models import FlowExplanation
from pysynoptic.insights.models import CallableInsight, InsightAnalysis

ProviderFactory = Callable[[AIProviderConfig], AIExplanationProvider]

_PROVIDER_LABELS = {
    AIProviderKind.DISABLED: "Disabled",
    AIProviderKind.OLLAMA_COMPATIBLE: "Local / Ollama",
    AIProviderKind.OPENAI_COMPATIBLE: "OpenAI-compatible",
}
_KINDS_BY_LABEL = {label: kind for kind, label in _PROVIDER_LABELS.items()}
_DEFAULT_ENDPOINTS = {
    AIProviderKind.DISABLED: "",
    AIProviderKind.OLLAMA_COMPATIBLE: "http://127.0.0.1:11434",
    AIProviderKind.OPENAI_COMPATIBLE: "https://api.openai.com",
}


@dataclass(frozen=True, slots=True)
class AIExplanationCompletion:
    """One asynchronous completion associated with a static generation."""

    request_id: int
    generation: int
    symbol_id: str
    configuration_revision: int = 0
    result: AIExplanationResult | None = None
    cache_hit: bool = False
    error_message: str | None = None


class AIExplanationSession:
    """Own configuration, cache, privacy consent, and explicit daemon work."""

    def __init__(
        self,
        *,
        provider_factory: ProviderFactory = provider_from_config,
    ) -> None:
        self._provider_factory = provider_factory
        self._config = AIProviderConfig()
        self._provider: AIExplanationProvider = provider_factory(self._config)
        self._service = AIExplanationService()
        self._completed: queue.SimpleQueue[AIExplanationCompletion] = (
            queue.SimpleQueue()
        )
        self._request_ids = itertools.count(1)
        self._confirmed_endpoints: set[str] = set()
        self._configuration_revision = 0
        self._closed = False

    @property
    def config(self) -> AIProviderConfig:
        return self._config

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def generation(self) -> int:
        return self._service.generation

    @property
    def cache_size(self) -> int:
        return self._service.size

    @property
    def closed(self) -> bool:
        return self._closed

    def configure(self, config: AIProviderConfig) -> None:
        """Replace session settings without persisting or logging credentials."""
        provider = self._provider_factory(config)
        self._config = config
        self._provider = provider
        self._configuration_revision += 1

    def set_generation(self, generation: int) -> None:
        """Invalidate cached prose and reject older asynchronous completions."""
        self._service.set_generation(generation)

    def needs_privacy_confirmation(self) -> bool:
        """Return whether this configured endpoint has not been approved yet."""
        return bool(
            self.enabled and self._config.endpoint not in self._confirmed_endpoints
        )

    def confirm_current_endpoint(self) -> None:
        """Remember explicit consent for this endpoint during this session."""
        if self.enabled:
            self._confirmed_endpoints.add(self._config.endpoint)

    def current_endpoint_is_local(self) -> bool:
        return is_local_endpoint(self._config.endpoint)

    @staticmethod
    def build_request(
        insight: CallableInsight,
        explanation: FlowExplanation,
        analysis: InsightAnalysis | None,
    ) -> AIExplanationRequest:
        return build_ai_explanation_request(insight, explanation, analysis)

    def peek(
        self,
        symbol_id: str,
        request: AIExplanationRequest,
    ) -> AIExplanationResult | None:
        """Look up previously requested prose without any provider call."""
        if not self.enabled:
            return None
        return self._service.peek(symbol_id, request, self._provider)

    def submit(
        self,
        symbol_id: str,
        request: AIExplanationRequest,
    ) -> int:
        """Start one daemon request only after an explicit GUI action."""
        if self._closed:
            raise RuntimeError("AI explanation session is closed.")
        if not self.enabled:
            raise AIConfigurationError("AI explanations are disabled.")
        request_id = next(self._request_ids)
        generation = self.generation
        configuration_revision = self._configuration_revision
        cached = self._service.peek(symbol_id, request, self._provider)
        if cached is not None:
            self._completed.put(
                AIExplanationCompletion(
                    request_id,
                    generation,
                    symbol_id,
                    configuration_revision,
                    result=cached,
                    cache_hit=True,
                )
            )
            return request_id
        provider = self._provider

        def run() -> None:
            try:
                outcome = self._service.rewrite(symbol_id, request, provider)
            except StaleAIExplanationError:
                return
            except AIExplanationError as exc:
                completion = AIExplanationCompletion(
                    request_id,
                    generation,
                    symbol_id,
                    configuration_revision,
                    error_message=str(exc),
                )
            except Exception:
                completion = AIExplanationCompletion(
                    request_id,
                    generation,
                    symbol_id,
                    configuration_revision,
                    error_message="AI explanation failed.",
                )
            else:
                completion = AIExplanationCompletion(
                    request_id,
                    generation,
                    symbol_id,
                    configuration_revision,
                    result=outcome.result,
                    cache_hit=outcome.cache_hit,
                )
            if (
                not self._closed
                and generation == self.generation
                and configuration_revision == self._configuration_revision
            ):
                self._completed.put(completion)

        threading.Thread(
            target=run,
            name=f"pysynoptic-ai-{request_id}",
            daemon=True,
        ).start()
        return request_id

    def poll(self, request_id: int) -> AIExplanationCompletion | None:
        """Return the requested current completion, discarding stale work."""
        while True:
            try:
                completion = self._completed.get_nowait()
            except queue.Empty:
                return None
            if (
                completion.request_id == request_id
                and completion.generation == self.generation
                and completion.configuration_revision == self._configuration_revision
            ):
                return completion

    def shutdown(self) -> None:
        """Prevent daemon completions from being delivered after Tk shutdown."""
        self._closed = True


def provider_label(kind: AIProviderKind) -> str:
    return _PROVIDER_LABELS[kind]


def configuration_from_fields(
    provider: str,
    endpoint: str,
    model: str,
    api_key: str,
) -> AIProviderConfig:
    """Build redacted, session-only configuration from dialog values."""
    try:
        kind = _KINDS_BY_LABEL[provider]
    except KeyError:
        raise AIConfigurationError("Choose a supported AI provider.") from None
    if kind is AIProviderKind.DISABLED:
        return AIProviderConfig()
    config = AIProviderConfig(
        kind=kind,
        endpoint=endpoint.strip(),
        model=model.strip(),
        api_key=api_key,
    )
    provider_from_config(config, environment={})
    return config


def prompt_ai_configuration(
    parent: tk.Misc,
    current: AIProviderConfig,
) -> AIProviderConfig | None:
    """Prompt for non-persistent AI settings and return them on Save."""
    dialog = tk.Toplevel(parent)
    dialog.title("Configure AI explanations")
    dialog.resizable(False, False)
    dialog.transient(parent)
    dialog.grab_set()

    frame = ttk.Frame(dialog, padding=16)
    frame.pack(fill="both", expand=True)
    provider_var = tk.StringVar(value=provider_label(current.kind))
    endpoint_var = tk.StringVar(value=current.endpoint)
    model_var = tk.StringVar(value=current.model)
    api_key_var = tk.StringVar(value=current.api_key)
    result: list[AIProviderConfig] = []

    ttk.Label(frame, text="AI Provider").grid(row=0, column=0, sticky="w")
    provider_box = ttk.Combobox(
        frame,
        textvariable=provider_var,
        values=tuple(_KINDS_BY_LABEL),
        state="readonly",
        width=28,
    )
    provider_box.grid(row=0, column=1, sticky="ew", padx=(12, 0), pady=4)
    ttk.Label(frame, text="Endpoint").grid(row=1, column=0, sticky="w")
    ttk.Entry(frame, textvariable=endpoint_var, width=42).grid(
        row=1, column=1, sticky="ew", padx=(12, 0), pady=4
    )
    ttk.Label(frame, text="Model").grid(row=2, column=0, sticky="w")
    ttk.Entry(frame, textvariable=model_var, width=42).grid(
        row=2, column=1, sticky="ew", padx=(12, 0), pady=4
    )
    ttk.Label(frame, text="API key (session only)").grid(row=3, column=0, sticky="w")
    ttk.Entry(frame, textvariable=api_key_var, show="•", width=42).grid(
        row=3, column=1, sticky="ew", padx=(12, 0), pady=4
    )
    ttk.Label(
        frame,
        text=(
            "The key is never saved. OPENAI_API_KEY or "
            "PYSYNOPTIC_AI_API_KEY may also be used."
        ),
        wraplength=390,
        bootstyle="secondary",
    ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 12))

    def provider_changed(_event: object = None) -> None:
        kind = _KINDS_BY_LABEL[provider_var.get()]
        if not endpoint_var.get().strip():
            endpoint_var.set(_DEFAULT_ENDPOINTS[kind])

    provider_box.bind("<<ComboboxSelected>>", provider_changed)

    def save() -> None:
        try:
            config = configuration_from_fields(
                provider_var.get(),
                endpoint_var.get(),
                model_var.get(),
                api_key_var.get(),
            )
        except AIConfigurationError as exc:
            messagebox.showerror("PySynoptic", str(exc), parent=dialog)
            return
        result.append(config)
        api_key_var.set("")
        dialog.destroy()

    buttons = ttk.Frame(frame)
    buttons.grid(row=5, column=0, columnspan=2, sticky="e")
    ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(
        side="left", padx=(0, 8)
    )
    ttk.Button(buttons, text="Save", command=save, bootstyle="primary").pack(
        side="left"
    )
    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
    dialog.wait_window()
    api_key_var.set("")
    return result[0] if result else None


__all__ = [
    "AIExplanationCompletion",
    "AIExplanationSession",
    "configuration_from_fields",
    "prompt_ai_configuration",
    "provider_label",
]
