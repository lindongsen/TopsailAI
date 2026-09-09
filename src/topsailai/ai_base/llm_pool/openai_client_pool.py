"""Process-local pool for reusable synchronous OpenAI SDK clients."""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

import httpcore
import httpx
import openai

from topsailai.ai_base.llm_control.exception import (
    LLMProviderBadRequestError,
    LLMProviderConnectionError,
    LLMProviderInternalServerError,
    LLMProviderPermissionDeniedError,
    LLMProviderRateLimitError,
    LLMProviderReadError,
    LLMProviderTimeoutError,
)
from topsailai.ai_base.llm_pool.base_client_pool import (
    BaseClientPool,
    ClientPoolHandle,
)
from topsailai.ai_base.llm_pool.provider_registry import (
    LLMProviderBackend,
    default_provider_registry,
)

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_CLIENT_POOL_CAPACITY = 32
_CLIENT_KIND_SYNC = "sync"


def normalize_base_url(base_url: str | None) -> str:
    """Return the effective base URL with conservative trailing-slash cleanup."""
    normalized = (base_url or DEFAULT_OPENAI_BASE_URL).strip()
    while normalized.endswith("/") and not normalized.endswith("://"):
        normalized = normalized[:-1]
    return normalized or DEFAULT_OPENAI_BASE_URL


def _fingerprint(value: str) -> str:
    """Return a stable SHA-256 fingerprint without retaining the input in a key."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _options_fingerprint(options: tuple[tuple[str, Any], ...]) -> str:
    """Return a deterministic fingerprint for client-construction options."""
    encoded = json.dumps(
        options,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda value: {
            "type": f"{type(value).__module__}.{type(value).__qualname__}",
            "repr": repr(value),
        },
    )
    return _fingerprint(encoded)


def _normalize_options(
    options: Mapping[str, Any] | tuple[tuple[str, Any], ...] | None,
) -> tuple[tuple[str, Any], ...]:
    """Convert supported option collections into an immutable ordered tuple."""
    if options is None:
        return ()
    items = options.items() if isinstance(options, Mapping) else options
    return tuple(sorted(items, key=lambda item: item[0]))


@dataclass(frozen=True)
class OpenAIClientKey:
    """Secret-free identity of one reusable OpenAI SDK client generation."""

    client_type: str
    normalized_base_url: str
    api_key_fingerprint: str
    organization: str | None
    project: str | None
    client_options_fingerprint: str


@dataclass(frozen=True)
class OpenAIClientConfig:
    """Immutable effective configuration used to construct an OpenAI client."""

    api_key: str = field(default="", repr=False)
    base_url: str = DEFAULT_OPENAI_BASE_URL
    organization: str | None = None
    project: str | None = None
    client_type: str = _CLIENT_KIND_SYNC
    client_options: tuple[tuple[str, Any], ...] = ()
    model: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        """Normalize immutable configuration fields at construction time."""
        object.__setattr__(self, "base_url", normalize_base_url(self.base_url))
        object.__setattr__(self, "client_options", _normalize_options(self.client_options))
        if self.client_type != _CLIENT_KIND_SYNC:
            raise ValueError(f"unsupported OpenAI client type: {self.client_type}")

    def to_key(self) -> OpenAIClientKey:
        """Build the secret-free cache key; model is intentionally excluded."""
        return OpenAIClientKey(
            client_type=self.client_type,
            normalized_base_url=self.base_url,
            api_key_fingerprint=_fingerprint(self.api_key),
            organization=self.organization,
            project=self.project,
            client_options_fingerprint=_options_fingerprint(self.client_options),
        )

    def constructor_kwargs(self) -> dict[str, Any]:
        """Return keyword arguments for constructing the root SDK client."""
        kwargs = dict(self.client_options)
        kwargs["api_key"] = self.api_key
        kwargs["base_url"] = self.base_url
        if self.organization is not None:
            kwargs["organization"] = self.organization
        if self.project is not None:
            kwargs["project"] = self.project
        return kwargs


class OpenAIResponseAdapter:
    """Contain OpenAI response parsing, construction, and error translation."""

    _ERROR_MAP = (
        (openai.RateLimitError, LLMProviderRateLimitError),
        (openai.InternalServerError, LLMProviderInternalServerError),
        (openai.APITimeoutError, LLMProviderTimeoutError),
        (openai.APIConnectionError, LLMProviderConnectionError),
        (openai.PermissionDeniedError, LLMProviderPermissionDeniedError),
        (openai.BadRequestError, LLMProviderBadRequestError),
        (
            (
                httpx.ReadError,
                httpcore.ReadError,
                httpx.RemoteProtocolError,
                httpx.ReadTimeout,
                httpcore.ReadTimeout,
            ),
            LLMProviderReadError,
        ),
    )

    @staticmethod
    def get_response_content(response):
        """Return content from the first OpenAI chat-completion message."""
        return response.choices[0].message.content

    @staticmethod
    def get_stream_delta(chunk):
        """Return the first OpenAI stream delta when present."""
        if not chunk.choices:
            return None
        return chunk.choices[0].delta

    @staticmethod
    def get_delta_content(delta):
        """Return text content from an OpenAI stream delta."""
        return delta.content

    @staticmethod
    def merge_delta_tool_calls(full_tool_calls, delta):
        """Merge OpenAI tool-call deltas into accumulated plain data."""
        for tool_call in delta.tool_calls or []:
            current = full_tool_calls.setdefault(
                tool_call.index,
                {"id": "", "function": {"name": "", "arguments": ""}},
            )
            if tool_call.id:
                current["id"] = tool_call.id
            if not tool_call.function:
                continue
            if tool_call.function.name:
                current["function"]["name"] = tool_call.function.name
            if tool_call.function.arguments:
                current["function"]["arguments"] += tool_call.function.arguments

    @staticmethod
    def build_tool_calls(full_tool_calls):
        """Build final OpenAI tool-call objects from accumulated deltas."""
        from openai.types.chat import ChatCompletionMessageToolCall

        result = []
        for index in sorted(full_tool_calls):
            tool_call = full_tool_calls[index]
            tool_call["type"] = "function"
            result.append(ChatCompletionMessageToolCall(**tool_call))
        return result

    @staticmethod
    def build_assistant_message(content, tool_calls):
        """Build the final OpenAI assistant response message."""
        from openai.types.chat import ChatCompletionMessage

        return ChatCompletionMessage(
            role="assistant",
            content=content,
            tool_calls=tool_calls,
        )

    @staticmethod
    def make_first_byte_timeout_error(first_byte_timeout):
        """Construct a project-owned timeout for a first-byte timeout."""
        return LLMProviderTimeoutError(
            f"First byte timeout after {first_byte_timeout}s"
        )

    @classmethod
    def translate_error(cls, error):
        """Translate one recognized OpenAI or transport error."""
        for source_type, target_type in cls._ERROR_MAP:
            if isinstance(error, source_type):
                return target_type(
                    str(error),
                    response=getattr(error, "response", None),
                    body=getattr(error, "body", None),
                )
        return error

    @classmethod
    def iter_response(cls, response):
        """Yield stream items while translating deferred transport errors."""
        try:
            yield from response
        except Exception as error:
            translated = cls.translate_error(error)
            if translated is error:
                raise
            raise translated from error

    @classmethod
    def create_response(cls, chat_model, params):
        """Create a response and translate errors at the OpenAI boundary."""
        try:
            response = chat_model.create(timeout=(5, 300), **params)
        except Exception as error:
            translated = cls.translate_error(error)
            if translated is error:
                raise
            raise translated from error
        if params.get("stream"):
            return cls.iter_response(response)
        return response


@dataclass(frozen=True)
class OpenAIClientHandle(ClientPoolHandle):
    """Immutable caller lease for a pooled root OpenAI client."""


class OpenAIClientPool(BaseClientPool):
    """Thread-safe, process-local pool of reusable root OpenAI clients."""

    handle_class = OpenAIClientHandle
    pool_name = "OpenAI client"

    def __init__(
        self,
        capacity: int = DEFAULT_OPENAI_CLIENT_POOL_CAPACITY,
        client_factory: Callable[..., Any] = openai.OpenAI,
        clock: Callable[[], float] = time.monotonic,
        pid_getter: Callable[[], int] = os.getpid,
    ) -> None:
        """Initialize an isolated OpenAI pool using the common lifecycle."""
        super().__init__(
            capacity=capacity,
            client_factory=client_factory,
            clock=clock,
            pid_getter=pid_getter,
        )

    @staticmethod
    def _log_identity(key: OpenAIClientKey) -> str:
        """Return safe, concise OpenAI cache identity text for diagnostics."""
        return (
            f"type={key.client_type} base_url={key.normalized_base_url} "
            f"api_key_sha256={key.api_key_fingerprint[:8]}"
        )


default_openai_client_pool = OpenAIClientPool()


def get_or_create(config: OpenAIClientConfig) -> OpenAIClientHandle:
    """Acquire a handle from the process-wide default pool."""
    return default_openai_client_pool.get_or_create(config)


def acquire(config: OpenAIClientConfig) -> OpenAIClientHandle:
    """Acquire a handle from the process-wide default pool."""
    return default_openai_client_pool.acquire(config)


def release(handle: OpenAIClientHandle) -> None:
    """Release a handle obtained from the process-wide default pool."""
    default_openai_client_pool.release(handle)


def invalidate(config_or_key: OpenAIClientConfig | OpenAIClientKey) -> bool:
    """Invalidate a current generation in the process-wide default pool."""
    return default_openai_client_pool.invalidate(config_or_key)


def close_idle(idle_seconds: float = 0.0) -> int:
    """Close idle clients in the process-wide default pool."""
    return default_openai_client_pool.close_idle(idle_seconds)


def close_all() -> int:
    """Close all clients in the process-wide default pool."""
    return default_openai_client_pool.close_all()


def get_chat_model(client):
    """Return the OpenAI chat-completions resource from one root client."""
    return client.chat.completions


def _resolve_openai_model_name(default: str) -> str:
    """Resolve the default OpenAI model name from its environment variable."""
    return os.getenv("OPENAI_MODEL", default)


def _make_openai_config(
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    **kwargs: Any,
) -> OpenAIClientConfig:
    """Build an OpenAI client config, resolving environment defaults."""
    effective_api_key = api_key or os.getenv("OPENAI_API_KEY", "")
    effective_api_base = base_url or os.getenv(
        "OPENAI_API_BASE", DEFAULT_OPENAI_BASE_URL
    )
    return OpenAIClientConfig(
        api_key=effective_api_key,
        base_url=effective_api_base,
        model=model,
        **kwargs,
    )


OPENAI_PROVIDER_BACKEND = LLMProviderBackend(
    name="openai",
    config_factory=_make_openai_config,
    acquire=acquire,
    invalidate=invalidate,
    get_chat_model=get_chat_model,
    response_adapter=OpenAIResponseAdapter,
    model_name_resolver=_resolve_openai_model_name,
)
default_provider_registry.register(OPENAI_PROVIDER_BACKEND)


atexit.register(close_all)
