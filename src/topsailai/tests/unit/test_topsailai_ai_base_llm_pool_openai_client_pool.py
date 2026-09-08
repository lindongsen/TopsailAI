"""Unit tests for the reusable OpenAI SDK client pool."""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

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

from topsailai.ai_base.llm_pool.openai_client_pool import (
    OpenAIClientConfig,
    OpenAIClientPool,
    OpenAIResponseAdapter,
    normalize_base_url,
)


class FakeClient:
    """Track deterministic lifecycle events for a fake root SDK client."""

    def __init__(self, identifier, kwargs):
        """Initialize one fake client from captured constructor arguments."""
        self.identifier = identifier
        self.kwargs = kwargs
        self.close_count = 0
        self.chat = type("Chat", (), {"completions": object()})()

    def close(self):
        """Record a root-client close call."""
        self.close_count += 1


class ClientFactory:
    """Create and retain fake root clients for assertions."""

    def __init__(self):
        """Initialize an empty synchronized client collection."""
        self.clients = []
        self.lock = threading.Lock()

    def __call__(self, **kwargs):
        """Create one fake client and retain it in creation order."""
        with self.lock:
            client = FakeClient(len(self.clients), kwargs)
            self.clients.append(client)
            return client


def make_config(
    api_key="secret-key",
    base_url="https://provider.example/v1",
    model=None,
    organization=None,
    project=None,
    client_options=(),
):
    """Build one immutable client configuration for a test."""
    return OpenAIClientConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
        organization=organization,
        project=project,
        client_options=client_options,
    )


def test_same_connection_identity_reuses_client_across_models():
    """Model names remain request-scoped and do not split the client cache."""
    factory = ClientFactory()
    pool = OpenAIClientPool(client_factory=factory)

    first = pool.acquire(make_config(model="model-a"))
    second = pool.acquire(make_config(model="model-b"))

    assert first.client is second.client
    assert first.key == second.key
    assert len(factory.clients) == 1
    assert first.client.chat.completions is not None

    first.release()
    second.release()
    pool.close_all()


def test_different_api_keys_create_distinct_clients():
    """Credential identity prevents clients from crossing API-key boundaries."""
    factory = ClientFactory()
    pool = OpenAIClientPool(client_factory=factory)

    first = pool.acquire(make_config(api_key="tenant-one", model="shared-model"))
    second = pool.acquire(make_config(api_key="tenant-two", model="shared-model"))

    assert first.client is not second.client
    assert first.key.api_key_fingerprint != second.key.api_key_fingerprint
    assert len(factory.clients) == 2

    pool.close_all()


def test_all_client_constructor_dimensions_participate_in_key():
    """Every supported client-construction dimension separates cache entries."""
    factory = ClientFactory()
    pool = OpenAIClientPool(client_factory=factory)
    configs = [
        make_config(),
        make_config(base_url="https://other.example/v1"),
        make_config(organization="org-a"),
        make_config(project="project-a"),
        make_config(client_options=(("max_retries", 4),)),
    ]

    handles = [pool.acquire(config) for config in configs]

    assert len({id(handle.client) for handle in handles}) == len(configs)
    assert len(factory.clients) == len(configs)
    pool.close_all()


def test_base_url_normalization_reuses_equivalent_urls():
    """Whitespace and redundant trailing slashes do not split cache identity."""
    factory = ClientFactory()
    pool = OpenAIClientPool(client_factory=factory)

    first = pool.acquire(make_config(base_url=" https://provider.example/v1/// "))
    second = pool.acquire(make_config(base_url="https://provider.example/v1"))

    assert normalize_base_url(" https://provider.example/v1/// ") == (
        "https://provider.example/v1"
    )
    assert first.client is second.client
    pool.close_all()


def test_concurrent_acquire_constructs_one_client():
    """Synchronized acquire calls create exactly one client for one key."""
    factory = ClientFactory()
    pool = OpenAIClientPool(client_factory=factory)
    worker_count = 12
    start = threading.Barrier(worker_count)
    handles = []
    handles_lock = threading.Lock()

    def acquire_client():
        """Wait until all workers are ready, then acquire one handle."""
        start.wait()
        handle = pool.acquire(make_config())
        with handles_lock:
            handles.append(handle)

    threads = [threading.Thread(target=acquire_client) for _ in range(worker_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(factory.clients) == 1
    assert len({id(handle.client) for handle in handles}) == 1
    for handle in handles:
        handle.release()
    pool.close_all()


def test_factory_failure_leaves_no_dirty_entry():
    """A failed constructor is retried normally without a partial cache entry."""
    calls = []

    def failing_once_factory(**kwargs):
        """Fail the first construction and succeed on the second."""
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("constructor failed")
        return FakeClient(len(calls), kwargs)

    pool = OpenAIClientPool(client_factory=failing_once_factory)

    with pytest.raises(RuntimeError, match="constructor failed"):
        pool.acquire(make_config())
    handle = pool.acquire(make_config())

    assert len(calls) == 2
    assert handle.client.identifier == 2
    pool.close_all()


def test_invalidate_creates_new_generation_and_defers_active_close():
    """Invalidation retires an active generation until its final release."""
    factory = ClientFactory()
    pool = OpenAIClientPool(client_factory=factory)
    config = make_config()
    old_handle = pool.acquire(config)

    assert pool.invalidate(config) is True
    new_handle = pool.get_or_create(config)

    assert old_handle.client is not new_handle.client
    assert new_handle.generation == old_handle.generation + 1
    assert old_handle.client.close_count == 0

    old_handle.release()
    assert old_handle.client.close_count == 1
    assert new_handle.client.close_count == 0
    new_handle.release()
    pool.close_all()


def test_lru_evicts_idle_client_but_never_in_use_client():
    """Capacity pressure closes the least-recent idle entry only."""
    factory = ClientFactory()
    clock_values = iter(range(100))
    pool = OpenAIClientPool(
        capacity=2,
        client_factory=factory,
        clock=lambda: next(clock_values),
    )
    idle = pool.acquire(make_config(api_key="idle"))
    active = pool.acquire(make_config(api_key="active"))
    idle.release()

    newest = pool.acquire(make_config(api_key="newest"))

    assert idle.client.close_count == 1
    assert active.client.close_count == 0
    assert newest.client.close_count == 0

    active.release()
    newest.release()
    pool.close_all()


def test_capacity_may_be_exceeded_when_every_client_is_in_use():
    """Capacity enforcement never closes clients with live leases."""
    factory = ClientFactory()
    pool = OpenAIClientPool(capacity=1, client_factory=factory)

    first = pool.acquire(make_config(api_key="first"))
    second = pool.acquire(make_config(api_key="second"))

    assert first.client.close_count == 0
    assert second.client.close_count == 0

    first.release()
    assert first.client.close_count == 1
    assert second.client.close_count == 0
    second.release()
    pool.close_all()


def test_release_and_close_all_are_idempotent():
    """Repeated cleanup cannot underflow references or close a client twice."""
    factory = ClientFactory()
    pool = OpenAIClientPool(client_factory=factory)
    first = pool.acquire(make_config())
    second = pool.acquire(make_config())

    first.release()
    first.release()
    pool.release(second)
    pool.release(second)
    assert first.client.close_count == 0

    assert pool.close_all() == 1
    assert pool.close_all() == 0
    assert first.client.close_count == 1


def test_close_idle_closes_only_clients_past_idle_threshold():
    """Idle cleanup respects both lease state and the requested age threshold."""
    factory = ClientFactory()
    now = [0.0]
    pool = OpenAIClientPool(client_factory=factory, clock=lambda: now[0])
    idle = pool.acquire(make_config(api_key="idle"))
    active = pool.acquire(make_config(api_key="active"))
    idle.release()
    now[0] = 10.0

    assert pool.close_idle(idle_seconds=5.0) == 1
    assert idle.client.close_count == 1
    assert active.client.close_count == 0

    active.release()
    pool.close_all()


def test_pid_change_abandons_inherited_clients_without_closing_them():
    """A child process starts fresh and never closes a parent-owned transport."""
    factory = ClientFactory()
    pid = [100]
    pool = OpenAIClientPool(client_factory=factory, pid_getter=lambda: pid[0])
    inherited = pool.acquire(make_config())

    pid[0] = 200
    child = pool.acquire(make_config())

    assert inherited.client is not child.client
    assert inherited.client.close_count == 0
    inherited.release()
    assert inherited.client.close_count == 0

    child.release()
    pool.close_all()
    assert child.client.close_count == 1


def test_api_key_is_absent_from_representations_and_logs():
    """Cache diagnostics and dataclass representations never expose credentials."""
    secret = "plaintext-api-key-sentinel"
    factory = ClientFactory()
    pool = OpenAIClientPool(client_factory=factory)
    config = make_config(api_key=secret)

    with patch(
        "topsailai.ai_base.llm_pool.base_client_pool.logger.debug"
    ) as debug_log:
        first = pool.acquire(config)
        second = pool.acquire(config)
        pool.invalidate(config)
        first.release()
        second.release()

    rendered_logs = " ".join(str(call) for call in debug_log.call_args_list)
    captured = rendered_logs + repr(config) + repr(first.key) + repr(first)
    assert secret not in captured
    assert first.key.api_key_fingerprint[:8] in rendered_logs


def test_response_adapter_extracts_chat_content_and_stream_delta():
    """The adapter owns OpenAI response and stream field traversal."""
    message = MagicMock(content="answer")
    response = MagicMock(choices=[MagicMock(message=message)])
    delta = MagicMock(content="chunk")
    chunk = MagicMock(choices=[MagicMock(delta=delta)])

    assert OpenAIResponseAdapter.get_response_content(response) == "answer"
    assert OpenAIResponseAdapter.get_stream_delta(chunk) is delta
    assert OpenAIResponseAdapter.get_stream_delta(MagicMock(choices=[])) is None
    assert OpenAIResponseAdapter.get_delta_content(delta) == "chunk"


def test_response_adapter_merges_and_builds_stream_tool_calls():
    """The adapter accumulates fragmented OpenAI tool calls in index order."""
    first = SimpleNamespace(
        index=1,
        id="call-b",
        function=SimpleNamespace(name="second", arguments='{"b":'),
    )
    second = SimpleNamespace(
        index=0,
        id="call-a",
        function=SimpleNamespace(name="first", arguments='{"a":1}'),
    )
    continuation = SimpleNamespace(
        index=1,
        id=None,
        function=SimpleNamespace(name=None, arguments="2}"),
    )
    accumulated = {}

    OpenAIResponseAdapter.merge_delta_tool_calls(
        accumulated,
        MagicMock(tool_calls=[first, second]),
    )
    OpenAIResponseAdapter.merge_delta_tool_calls(
        accumulated,
        MagicMock(tool_calls=[continuation]),
    )
    tool_calls = OpenAIResponseAdapter.build_tool_calls(accumulated)

    assert [tool_call.id for tool_call in tool_calls] == ["call-a", "call-b"]
    assert tool_calls[1].function.name == "second"
    assert tool_calls[1].function.arguments == '{"b":2}'


def test_response_adapter_builds_message_timeout_and_request():
    """The adapter owns OpenAI message, timeout, and request construction."""
    message = OpenAIResponseAdapter.build_assistant_message("answer", [])
    error = OpenAIResponseAdapter.make_first_byte_timeout_error(7)
    chat_model = MagicMock()
    expected_response = object()
    chat_model.create.return_value = expected_response

    response = OpenAIResponseAdapter.create_response(
        chat_model,
        {"model": "provider-model", "stream": False},
    )

    assert message.role == "assistant"
    assert message.content == "answer"
    assert message.tool_calls == []
    assert error.args == ("First byte timeout after 7s",)
    assert response is expected_response
    chat_model.create.assert_called_once_with(
        timeout=(5, 300),
        model="provider-model",
        stream=False,
    )


def _make_openai_status_error(error_type, message):
    """Build an OpenAI status error with diagnostic response metadata."""
    response = httpx.Response(
        status_code=400,
        request=httpx.Request("POST", "https://provider.example/v1/chat/completions"),
    )
    return error_type(message, response=response, body={"detail": message})


@pytest.mark.parametrize(
    ("source_error", "target_type"),
    [
        (
            _make_openai_status_error(openai.RateLimitError, "rate limited"),
            LLMProviderRateLimitError,
        ),
        (
            _make_openai_status_error(
                openai.InternalServerError, "internal failure"
            ),
            LLMProviderInternalServerError,
        ),
        (
            openai.APITimeoutError(
                request=httpx.Request("POST", "https://provider.example/v1")
            ),
            LLMProviderTimeoutError,
        ),
        (
            openai.APIConnectionError(
                request=httpx.Request("POST", "https://provider.example/v1")
            ),
            LLMProviderConnectionError,
        ),
        (
            _make_openai_status_error(
                openai.PermissionDeniedError, "permission denied"
            ),
            LLMProviderPermissionDeniedError,
        ),
        (
            _make_openai_status_error(openai.BadRequestError, "bad request"),
            LLMProviderBadRequestError,
        ),
        (httpx.ReadError("read failed"), LLMProviderReadError),
        (httpcore.ReadError("core read failed"), LLMProviderReadError),
        (httpx.RemoteProtocolError("protocol failed"), LLMProviderReadError),
        (httpx.ReadTimeout("read timed out"), LLMProviderReadError),
        (httpcore.ReadTimeout("core read timed out"), LLMProviderReadError),
    ],
)
def test_response_adapter_translates_provider_errors(source_error, target_type):
    """Every consumed OpenAI transport category maps to a project error."""
    translated = OpenAIResponseAdapter.translate_error(source_error)

    assert isinstance(translated, target_type)
    assert str(source_error) == str(translated)
    assert translated.response is getattr(source_error, "response", None)
    assert translated.body is getattr(source_error, "body", None)


def test_response_adapter_preserves_unrecognized_errors():
    """Unknown failures retain their original type and identity."""
    source_error = RuntimeError("unknown failure")

    assert OpenAIResponseAdapter.translate_error(source_error) is source_error


def test_response_adapter_translates_create_error():
    """Synchronous SDK request failures cross the boundary as project errors."""
    chat_model = MagicMock()
    source_error = _make_openai_status_error(
        openai.BadRequestError, "invalid request"
    )
    chat_model.create.side_effect = source_error

    with pytest.raises(LLMProviderBadRequestError) as captured:
        OpenAIResponseAdapter.create_response(chat_model, {"stream": False})

    assert captured.value.__cause__ is source_error
    assert captured.value.response is source_error.response
    assert captured.value.body is source_error.body


def test_response_adapter_translates_deferred_stream_error():
    """Failures raised after stream creation are translated during iteration."""
    source_error = openai.APIConnectionError(
        request=httpx.Request("POST", "https://provider.example/v1")
    )

    def failing_stream():
        """Yield one item before the provider stream fails."""
        yield "first"
        raise source_error

    chat_model = MagicMock()
    chat_model.create.return_value = failing_stream()
    response = OpenAIResponseAdapter.create_response(
        chat_model, {"stream": True}
    )
    iterator = iter(response)

    assert next(iterator) == "first"
    with pytest.raises(LLMProviderConnectionError) as captured:
        next(iterator)

    assert captured.value.__cause__ is source_error
