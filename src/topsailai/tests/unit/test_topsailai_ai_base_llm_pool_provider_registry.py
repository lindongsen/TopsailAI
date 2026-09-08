"""Unit tests for provider-neutral LLM backend registration."""

from types import SimpleNamespace

import pytest

from topsailai.ai_base.llm_pool.provider_registry import (
    LLMProviderBackend,
    LLMProviderRegistry,
)


def _make_backend(name="example"):
    """Return a minimal provider backend for registry tests."""
    return LLMProviderBackend(
        name=name,
        config_factory=dict,
        acquire=lambda config: SimpleNamespace(client=config),
        invalidate=lambda key: True,
        get_chat_model=lambda client: client,
        response_adapter=object(),
    )


def test_registry_resolves_normalized_provider_name():
    """Provider lookup is case-insensitive and trims surrounding whitespace."""
    registry = LLMProviderRegistry()
    backend = _make_backend("Example")

    registry.register(backend)

    assert registry.resolve(" example ") is backend
    assert registry.resolve("EXAMPLE") is backend


def test_registry_rejects_duplicate_provider_name():
    """Duplicate normalized names cannot silently replace a backend."""
    registry = LLMProviderRegistry()
    registry.register(_make_backend("example"))

    with pytest.raises(ValueError, match="already registered: example"):
        registry.register(_make_backend("EXAMPLE"))


def test_registry_rejects_unknown_or_empty_provider_before_dispatch():
    """Unknown and empty provider values fail without invoking provider code."""
    registry = LLMProviderRegistry()

    with pytest.raises(ValueError, match="unsupported LLM provider: missing"):
        registry.resolve("missing")
    with pytest.raises(ValueError, match="non-empty string"):
        registry.resolve("  ")
