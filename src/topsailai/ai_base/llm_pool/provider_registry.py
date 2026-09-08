"""Provider-neutral registry for LLM client pools and response adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


DEFAULT_LLM_PROVIDER = "openai"


@dataclass(frozen=True)
class LLMProviderBackend:
    """Describe one provider's pool, resource, and response adaptation hooks."""

    name: str
    config_factory: Callable[..., Any]
    acquire: Callable[[Any], Any]
    invalidate: Callable[[Any], bool]
    get_chat_model: Callable[[Any], Any]
    response_adapter: Any


class LLMProviderRegistry:
    """Resolve immutable provider backends by normalized provider name."""

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._backends: dict[str, LLMProviderBackend] = {}

    def register(self, backend: LLMProviderBackend) -> None:
        """Register one backend and reject ambiguous duplicate names."""
        name = self._normalize_name(backend.name)
        if name in self._backends:
            raise ValueError(f"LLM provider already registered: {name}")
        self._backends[name] = backend

    def resolve(self, provider: str = DEFAULT_LLM_PROVIDER) -> LLMProviderBackend:
        """Return one backend or fail before any provider client is acquired."""
        name = self._normalize_name(provider)
        backend = self._backends.get(name)
        if backend is None:
            raise ValueError(f"unsupported LLM provider: {name}")
        return backend

    @staticmethod
    def _normalize_name(provider: str) -> str:
        """Normalize a provider name while rejecting missing or invalid values."""
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("LLM provider must be a non-empty string")
        return provider.strip().lower()


default_provider_registry = LLMProviderRegistry()
