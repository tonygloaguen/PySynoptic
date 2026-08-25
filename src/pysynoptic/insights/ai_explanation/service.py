"""Generation-scoped in-memory cache for explicit AI rewrites."""

from __future__ import annotations

from dataclasses import dataclass

from pysynoptic.insights.ai_explanation.models import (
    AIExplanationRequest,
    AIExplanationResult,
)
from pysynoptic.insights.ai_explanation.providers import AIExplanationProvider
from pysynoptic.insights.ai_explanation.request import (
    normalize_ai_explanation_request,
    request_hash,
)


class StaleAIExplanationError(RuntimeError):
    """Raised when an in-flight result belongs to an older analysis."""


@dataclass(frozen=True, slots=True)
class CachedAIExplanation:
    """One validated result and whether it came from memory."""

    result: AIExplanationResult
    cache_hit: bool


@dataclass(frozen=True, slots=True)
class _CacheKey:
    generation: int
    symbol_id: str
    provider: str
    model: str
    request_hash: str


class AIExplanationService:
    """Call providers only on demand and retain results for one generation."""

    def __init__(self) -> None:
        self._generation = 0
        self._items: dict[_CacheKey, AIExplanationResult] = {}

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def size(self) -> int:
        return len(self._items)

    def set_generation(self, generation: int) -> None:
        """Invalidate all AI prose when the static analysis changes."""
        if generation == self._generation:
            return
        self._generation = generation
        self._items.clear()

    def _key(
        self,
        symbol_id: str,
        request: AIExplanationRequest,
        provider: AIExplanationProvider,
    ) -> _CacheKey:
        return _CacheKey(
            self._generation,
            symbol_id,
            provider.provider_id,
            provider.model,
            request_hash(request),
        )

    def peek(
        self,
        symbol_id: str,
        request: AIExplanationRequest,
        provider: AIExplanationProvider,
    ) -> AIExplanationResult | None:
        """Return cached prose without making a provider call."""
        normalized = normalize_ai_explanation_request(request)
        return self._items.get(self._key(symbol_id, normalized, provider))

    def rewrite(
        self,
        symbol_id: str,
        request: AIExplanationRequest,
        provider: AIExplanationProvider,
    ) -> CachedAIExplanation:
        """Return cached prose or perform one explicit provider request."""
        normalized = normalize_ai_explanation_request(request)
        key = self._key(symbol_id, normalized, provider)
        cached = self._items.get(key)
        if cached is not None:
            return CachedAIExplanation(cached, True)
        generation = self._generation
        result = provider.rewrite_explanation(normalized)
        if generation != self._generation:
            raise StaleAIExplanationError(
                "AI explanation belongs to a previous analysis."
            )
        self._items[key] = result
        return CachedAIExplanation(result, False)


__all__ = [
    "AIExplanationService",
    "CachedAIExplanation",
    "StaleAIExplanationError",
]
