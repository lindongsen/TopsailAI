"""Reusable LLM SDK client pools."""

from topsailai.ai_base.llm_pool.base_client_pool import (
    DEFAULT_CLIENT_POOL_CAPACITY,
    BaseClientPool,
    ClientPoolEntry,
    ClientPoolHandle,
)
from topsailai.ai_base.llm_pool.openai_client_pool import (
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_OPENAI_CLIENT_POOL_CAPACITY,
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
    "DEFAULT_OPENAI_BASE_URL",
    "DEFAULT_OPENAI_CLIENT_POOL_CAPACITY",
    "BaseClientPool",
    "ClientPoolEntry",
    "ClientPoolHandle",
    "OpenAIClientConfig",
    "OpenAIClientHandle",
    "OpenAIClientKey",
    "OpenAIClientPool",
    "acquire",
    "close_all",
    "close_idle",
    "default_openai_client_pool",
    "get_or_create",
    "invalidate",
    "normalize_base_url",
    "release",
]
