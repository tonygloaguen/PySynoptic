"""Optional AI providers using one injectable standard-library HTTP transport."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Protocol
from urllib import error, request
from urllib.parse import urlparse, urlunparse

from pysynoptic.insights.ai_explanation.models import (
    AIExplanationRequest,
    AIExplanationResult,
    AIProviderConfig,
    AIProviderKind,
)
from pysynoptic.insights.ai_explanation.request import (
    SYSTEM_INSTRUCTION,
    build_ai_prompt,
)

MAX_AI_EXPLANATION_LENGTH = 2000
MAX_HTTP_RESPONSE_BYTES = 1_000_000


class AIExplanationError(RuntimeError):
    """Base error safe to surface without provider response bodies or secrets."""


class AIExplanationDisabledError(AIExplanationError):
    """Raised when an explicit rewrite is requested while AI is disabled."""


class AIConfigurationError(AIExplanationError):
    """Raised for incomplete or invalid session configuration."""


class AIProviderError(AIExplanationError):
    """Raised for timeout, HTTP, or transport failures."""


class AIResponseError(AIExplanationError):
    """Raised when provider output is not usable prose."""


class JSONTransport(Protocol):
    """Small shared HTTP boundary replaced by fakes in every standard test."""

    def post_json(
        self,
        url: str,
        payload: Mapping[str, object],
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> object:
        """POST JSON and return the decoded response value."""


class UrllibJSONTransport:
    """Production JSON transport with deliberately sanitized errors."""

    def post_json(
        self,
        url: str,
        payload: Mapping[str, object],
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> object:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        outgoing_headers = {"Content-Type": "application/json", **headers}
        outgoing = request.Request(
            url,
            data=body,
            headers=outgoing_headers,
            method="POST",
        )
        try:
            with request.urlopen(outgoing, timeout=timeout) as response:
                raw = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
        except error.HTTPError as exc:
            raise AIProviderError(f"AI provider returned HTTP {exc.code}.") from None
        except (TimeoutError, error.URLError) as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, TimeoutError):
                raise AIProviderError("AI provider request timed out.") from None
            raise AIProviderError("AI provider could not be reached.") from None
        if len(raw) > MAX_HTTP_RESPONSE_BYTES:
            raise AIResponseError("AI provider response body is too large.")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AIResponseError("AI provider returned invalid JSON.") from None


class AIExplanationProvider(Protocol):
    """Provider abstraction used only after an explicit user action."""

    @property
    def provider_id(self) -> str:
        """Return a stable provider identity including the endpoint."""

    @property
    def model(self) -> str:
        """Return the configured model name."""

    def rewrite_explanation(
        self,
        request: AIExplanationRequest,
    ) -> AIExplanationResult:
        """Rewrite the structured static explanation."""


def _endpoint_url(endpoint: str, suffix: str) -> str:
    parsed = urlparse(endpoint.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AIConfigurationError("AI endpoint must be an HTTP(S) URL.")
    path = parsed.path.rstrip("/")
    suffix = suffix.strip("/")
    if path.endswith(f"/{suffix}"):
        return urlunparse(parsed)
    first_segment, _, remainder = suffix.partition("/")
    if remainder and path.endswith(f"/{first_segment}"):
        suffix = remainder
    path = f"{path}/{suffix}"
    return urlunparse(parsed._replace(path=path))


def is_local_endpoint(endpoint: str) -> bool:
    """Recognize only literal loopback hosts as local endpoints."""
    host = (urlparse(endpoint).hostname or "").casefold()
    return host in {"localhost", "127.0.0.1", "::1"}


def validate_ai_text(value: object) -> str:
    """Accept bounded prose and reject empty, structured, or oversized output."""
    if not isinstance(value, str):
        raise AIResponseError("AI provider did not return text.")
    text = value.strip()
    if not text:
        raise AIResponseError("AI provider returned an empty explanation.")
    if len(text) > MAX_AI_EXPLANATION_LENGTH:
        raise AIResponseError(
            f"AI explanation exceeds {MAX_AI_EXPLANATION_LENGTH} characters."
        )
    if text[:1] in {"{", "["}:
        try:
            structured = json.loads(text)
        except json.JSONDecodeError:
            structured = None
        if isinstance(structured, (dict, list)):
            raise AIResponseError("AI provider returned structured data, not prose.")
    return text


def _require_enabled_config(config: AIProviderConfig) -> None:
    if not config.enabled:
        raise AIExplanationDisabledError("AI explanations are disabled.")
    if not config.endpoint.strip():
        raise AIConfigurationError("An AI endpoint is required.")
    if not config.model.strip():
        raise AIConfigurationError("An AI model is required.")
    if config.timeout_seconds <= 0:
        raise AIConfigurationError("AI timeout must be greater than zero.")


class DisabledAIExplanationProvider:
    """Explicit no-provider implementation that cannot touch the network."""

    provider_id = AIProviderKind.DISABLED.value
    model = ""

    def rewrite_explanation(
        self,
        request: AIExplanationRequest,
    ) -> AIExplanationResult:
        del request
        raise AIExplanationDisabledError("AI explanations are disabled.")


class OpenAICompatibleProvider:
    """Chat-completions-compatible provider over the shared JSON transport."""

    def __init__(
        self,
        config: AIProviderConfig,
        *,
        transport: JSONTransport | None = None,
    ) -> None:
        _require_enabled_config(config)
        self._config = config
        self._transport = transport or UrllibJSONTransport()
        self._url = _endpoint_url(config.endpoint, "v1/chat/completions")

    @property
    def provider_id(self) -> str:
        return f"{AIProviderKind.OPENAI_COMPATIBLE.value}:{self._url}"

    @property
    def model(self) -> str:
        return self._config.model

    def rewrite_explanation(
        self,
        request: AIExplanationRequest,
    ) -> AIExplanationResult:
        headers = {}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        response = self._transport.post_json(
            self._url,
            {
                "model": self.model,
                "messages": [
                    {"role": "developer", "content": SYSTEM_INSTRUCTION},
                    {"role": "user", "content": build_ai_prompt(request)},
                ],
                "stream": False,
            },
            headers=headers,
            timeout=self._config.timeout_seconds,
        )
        try:
            content = response["choices"][0]["message"]["content"]  # type: ignore[index]
        except (KeyError, IndexError, TypeError):
            raise AIResponseError(
                "AI provider response has an invalid shape."
            ) from None
        return AIExplanationResult(
            text=validate_ai_text(content),
            provider=AIProviderKind.OPENAI_COMPATIBLE.value,
            model=self.model,
        )


class OllamaCompatibleProvider:
    """Ollama chat provider sharing the same transport and prompt contract."""

    def __init__(
        self,
        config: AIProviderConfig,
        *,
        transport: JSONTransport | None = None,
    ) -> None:
        _require_enabled_config(config)
        self._config = config
        self._transport = transport or UrllibJSONTransport()
        self._url = _endpoint_url(config.endpoint, "api/chat")

    @property
    def provider_id(self) -> str:
        return f"{AIProviderKind.OLLAMA_COMPATIBLE.value}:{self._url}"

    @property
    def model(self) -> str:
        return self._config.model

    def rewrite_explanation(
        self,
        request: AIExplanationRequest,
    ) -> AIExplanationResult:
        response = self._transport.post_json(
            self._url,
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_INSTRUCTION},
                    {"role": "user", "content": build_ai_prompt(request)},
                ],
                "stream": False,
            },
            headers={},
            timeout=self._config.timeout_seconds,
        )
        try:
            content = response["message"]["content"]  # type: ignore[index]
        except (KeyError, TypeError):
            raise AIResponseError(
                "AI provider response has an invalid shape."
            ) from None
        return AIExplanationResult(
            text=validate_ai_text(content),
            provider=AIProviderKind.OLLAMA_COMPATIBLE.value,
            model=self.model,
        )


def provider_from_config(
    config: AIProviderConfig,
    *,
    transport: JSONTransport | None = None,
    environment: Mapping[str, str] | None = None,
) -> AIExplanationProvider:
    """Build one provider, reading an optional API key only into session memory."""
    if config.kind is AIProviderKind.DISABLED:
        return DisabledAIExplanationProvider()
    values = os.environ if environment is None else environment
    if not config.api_key:
        api_key = values.get("PYSYNOPTIC_AI_API_KEY", "")
        if config.kind is AIProviderKind.OPENAI_COMPATIBLE:
            api_key = api_key or values.get("OPENAI_API_KEY", "")
        if api_key:
            config = AIProviderConfig(
                kind=config.kind,
                endpoint=config.endpoint,
                model=config.model,
                api_key=api_key,
                timeout_seconds=config.timeout_seconds,
            )
    if config.kind is AIProviderKind.OPENAI_COMPATIBLE:
        return OpenAICompatibleProvider(config, transport=transport)
    if config.kind is AIProviderKind.OLLAMA_COMPATIBLE:
        return OllamaCompatibleProvider(config, transport=transport)
    raise AIConfigurationError("Unsupported AI provider configuration.")


__all__ = [
    "AIConfigurationError",
    "AIExplanationDisabledError",
    "AIExplanationError",
    "AIExplanationProvider",
    "AIProviderError",
    "AIResponseError",
    "DisabledAIExplanationProvider",
    "JSONTransport",
    "MAX_AI_EXPLANATION_LENGTH",
    "MAX_HTTP_RESPONSE_BYTES",
    "OllamaCompatibleProvider",
    "OpenAICompatibleProvider",
    "UrllibJSONTransport",
    "is_local_endpoint",
    "provider_from_config",
    "validate_ai_text",
]
