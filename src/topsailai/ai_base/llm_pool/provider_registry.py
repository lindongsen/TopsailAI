"""Provider-neutral registry for LLM client pools and response adapters."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Callable


DEFAULT_LLM_PROVIDER = "openai"

# Map a normalized provider name to the module that registers its backend.
# The module is imported lazily on first resolve so that importing the
# provider-neutral core never pulls in a provider SDK (e.g. openai).
_PROVIDER_MODULE_MAP = {
    "openai": "topsailai.ai_base.llm_pool.openai_client_pool",
}


@dataclass(frozen=True)
class LLMProviderBackend:
    """Describe one provider's pool, resource, and response adaptation hooks."""

    name: str
    config_factory: Callable[..., Any]
    acquire: Callable[[Any], Any]
    invalidate: Callable[[Any], bool]
    get_chat_model: Callable[[Any], Any]
    response_adapter: Any
    model_name_resolver: Callable[[str], str] = lambda default: default
    api_base_resolver: Callable[[str | None], str | None] = lambda default: default
    api_key_resolver: Callable[[str], str] = lambda default: default


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
        """Return one backend, lazily importing its provider module on first use."""
        name = self._normalize_name(provider)
        backend = self._backends.get(name)
        if backend is None:
            module_path = _PROVIDER_MODULE_MAP.get(name)
            if module_path:
                importlib.import_module(module_path)
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
