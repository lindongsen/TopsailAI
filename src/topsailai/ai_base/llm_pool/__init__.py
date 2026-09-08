"""Reusable LLM SDK client pools and provider routing."""

from topsailai.ai_base.llm_pool.base_client_pool import (
    DEFAULT_CLIENT_POOL_CAPACITY,
    BaseClientPool,
    ClientPoolEntry,
    ClientPoolHandle,
)
from topsailai.ai_base.llm_pool.provider_registry import (
    DEFAULT_LLM_PROVIDER,
    LLMProviderBackend,
    LLMProviderRegistry,
    default_provider_registry,
)
from topsailai.ai_base.llm_pool.openai_client_pool import (
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_OPENAI_CLIENT_POOL_CAPACITY,
    OPENAI_PROVIDER_BACKEND,
    OpenAIClientConfig,
    OpenAIClientHandle,
    OpenAIClientKey,
    OpenAIClientPool,
    acquire,
    close_all,
    close_idle,
    default_openai_client_pool,
    get_or_create,
    invalidate,
    normalize_base_url,
    release,
)

__all__ = [
    "DEFAULT_CLIENT_POOL_CAPACITY",
    "DEFAULT_LLM_PROVIDER",
    "DEFAULT_OPENAI_BASE_URL",
    "DEFAULT_OPENAI_CLIENT_POOL_CAPACITY",
    "BaseClientPool",
    "ClientPoolEntry",
    "ClientPoolHandle",
    "LLMProviderBackend",
    "LLMProviderRegistry",
    "OPENAI_PROVIDER_BACKEND",
    "OpenAIClientConfig",
    "OpenAIClientHandle",
    "OpenAIClientKey",
    "OpenAIClientPool",
    "acquire",
    "close_all",
    "close_idle",
    "default_openai_client_pool",
    "default_provider_registry",
    "get_or_create",
    "invalidate",
    "normalize_base_url",
    "release",
]
