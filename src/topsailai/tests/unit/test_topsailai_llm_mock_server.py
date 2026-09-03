"""Tests for the reusable OpenAI-compatible LLM mock server."""

import json
import threading
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import MagicMock, patch

import pytest
from openai import OpenAI

from topsailai.tests.mock.llm_mock_server import (
    MockServerConfig,
    PromptCache,
    common_prefix_tokens,
    create_server,
    parse_args,
    main,
    prompt_token_count,
)


def _message(role, content):
    """Build one chat message."""
    return {"role": role, "content": content}


@contextmanager
def running_server(**kwargs):
    """Run a mock server on an available loopback port."""
    server = create_server(MockServerConfig(port=0, **kwargs))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(base_url, path, method="GET", payload=None):
    """Send one HTTP request and decode its JSON response."""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        base_url + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=3) as response:
        return response.status, json.loads(response.read())


def _completion(base_url, messages, **extra):
    """Send a non-streaming completion request."""
    payload = {"model": "test-model", "messages": messages, "stream": False}
    payload.update(extra)
    return _request(base_url, "/v1/chat/completions", "POST", payload)[1]


@pytest.mark.parametrize(
    "kwargs,error",
    [
        ({"port": -1}, "port"),
        ({"chars_per_token": 0}, "chars_per_token"),
        ({"cache_capacity": 0}, "cache_capacity"),
        ({"request_body_capacity": 0}, "request_body_capacity"),
    ],
)
def test_config_rejects_invalid_values(kwargs, error):
    """Invalid numeric values must fail before server startup."""
    with pytest.raises(ValueError, match=error):
        MockServerConfig(**kwargs)


def test_prompt_token_count_is_deterministic_and_positive():
    """Token estimation must be deterministic and count every message."""
    messages = [_message("user", "a"), _message("assistant", "longer")]
    assert prompt_token_count(messages, 4) == prompt_token_count(messages, 4)
    assert prompt_token_count(messages, 4) >= 2


def test_common_prefix_counts_only_complete_leading_messages():
    """A mismatch must stop cache reuse at the preceding message boundary."""
    prefix = _message("system", "stable")
    current = [prefix, _message("user", "changed"), _message("user", "tail")]
    previous = [prefix, _message("user", "original"), _message("user", "tail")]
    tokens, messages = common_prefix_tokens(current, previous, 4)
    assert messages == 1
    assert tokens == prompt_token_count([prefix], 4)


def test_prompt_cache_uses_best_retained_prefix_and_evicts():
    """The cache must use the best retained prefix and stay capacity bounded."""
    cache = PromptCache(capacity=2, chars_per_token=4)
    first = [_message("system", "one"), _message("user", "a")]
    second = [_message("system", "two"), _message("user", "b")]
    third = [_message("system", "one"), _message("user", "c")]
    cache.record(first)
    cache.record(second)
    result = cache.record(third)
    state = cache.state()
    assert result["cached_messages"] == 1
    assert result["cached_tokens"] == prompt_token_count(first[:1], 4)
    assert state["cached_prompt_count"] == 2
    assert len(state["requests"]) == 2
    assert state["total_requests"] == 3


def test_prompt_cache_clear_resets_state():
    """Clearing the cache must remove prompts, records, and counters."""
    cache = PromptCache(capacity=2, chars_per_token=4)
    cache.record([_message("user", "hello")])
    cache.clear()
    assert cache.state() == {
        "capacity": 2,
        "cached_prompt_count": 0,
        "total_requests": 0,
        "requests": [],
    }


def test_health_and_unknown_endpoint():
    """Health must identify the model and unknown paths must return 404."""
    with running_server(model="cache-model") as (_, base_url):
        status, payload = _request(base_url, "/health")
        assert status == 200
        assert payload == {"status": "ok", "model": "cache-model"}
        with pytest.raises(HTTPError) as error:
            _request(base_url, "/missing")
        assert error.value.code == 404


def test_identical_request_reports_full_cache_hit():
    """An identical second prompt must report full prompt reuse."""
    messages = [_message("system", "stable"), _message("user", "hello")]
    with running_server() as (_, base_url):
        first = _completion(base_url, messages)
        second = _completion(base_url, messages)
    assert first["usage"]["prompt_tokens_details"]["cached_tokens"] == 0
    assert second["usage"]["prompt_tokens_details"]["cached_tokens"] == second["usage"]["prompt_tokens"]


def test_cache_usage_details_can_be_omitted_without_hiding_known_usage():
    """An opt-out Provider response must retain prompt and completion usage."""
    messages = [_message("user", "usage without cache details")]
    with running_server(report_cache_usage=False) as (_, base_url):
        response = _completion(base_url, messages)
    usage = response["usage"]
    assert "prompt_tokens_details" not in usage
    assert usage["prompt_tokens"] > 0
    assert usage["completion_tokens"] > 0
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]


def test_provider_usage_can_be_omitted_without_hiding_response_content():
    """An opt-out response must omit usage while preserving completion content."""
    messages = [_message("user", "usage omitted")]
    with running_server(report_usage=False, reply="content remains") as (_, base_url):
        response = _completion(base_url, messages)
    assert response["choices"][0]["message"]["content"] == "content remains"
    assert "usage" not in response


def test_appended_suffix_reports_partial_prefix_hit():
    """An appended suffix must reuse all previously sent leading messages."""
    prefix = [_message("system", "stable"), _message("user", "hello")]
    with running_server(chars_per_token=2) as (_, base_url):
        _completion(base_url, prefix)
        response = _completion(base_url, prefix + [_message("assistant", "new")])
    cached = response["usage"]["prompt_tokens_details"]["cached_tokens"]
    assert cached == prompt_token_count(prefix, 2)
    assert cached < response["usage"]["prompt_tokens"]


def test_different_prefix_reports_no_cache_hit():
    """A changed first message must report zero cached tokens."""
    with running_server() as (_, base_url):
        _completion(base_url, [_message("system", "first"), _message("user", "same")])
        response = _completion(base_url, [_message("system", "second"), _message("user", "same")])
    assert response["usage"]["prompt_tokens_details"]["cached_tokens"] == 0


def test_middle_insertion_reduces_cache_hit_like_summarization():
    """A middle insertion must stop reuse before the unchanged tail."""
    system = _message("system", "stable")
    task = _message("user", "task")
    body = _message("assistant", "long body")
    tail = _message("user", "continue")
    with running_server() as (_, base_url):
        original = _completion(base_url, [system, task, body, tail])
        rebuilt = _completion(
            base_url,
            [system, task, _message("assistant", "summary"), tail],
        )
    cached = rebuilt["usage"]["prompt_tokens_details"]["cached_tokens"]
    assert original["usage"]["prompt_tokens_details"]["cached_tokens"] == 0
    assert cached == prompt_token_count([system, task], 4)
    assert cached < rebuilt["usage"]["prompt_tokens"]


def test_debug_state_and_delete_are_observable():
    """Debug endpoints must expose request results and support deterministic reset."""
    with running_server(cache_capacity=3) as (_, base_url):
        _completion(base_url, [_message("user", "hello")])
        _, state = _request(base_url, "/debug/state")
        assert state["total_requests"] == 1
        assert state["requests"][0]["cached_tokens"] == 0
        status, result = _request(base_url, "/debug/state", "DELETE")
        assert status == 200
        assert result == {"status": "cleared"}
        assert _request(base_url, "/debug/state")[1]["total_requests"] == 0


def test_debug_state_captures_request_bodies_and_reset_clears_them():
    """Debug state must expose parsed request bodies and reset their counters."""
    messages = [_message("user", "captured")]
    with running_server() as (_, base_url):
        _completion(base_url, messages, temperature=0.25)
        state = _request(base_url, "/debug/state")[1]
        assert state["request_body_capacity"] == 32
        assert state["dropped_request_body_count"] == 0
        assert state["request_bodies"][0]["parsed"] is True
        assert state["request_bodies"][0]["body"]["messages"] == messages
        assert state["request_bodies"][0]["body"]["temperature"] == 0.25
        _request(base_url, "/debug/state", "DELETE")
        reset = _request(base_url, "/debug/state")[1]
    assert reset["request_bodies"] == []
    assert reset["dropped_request_body_count"] == 0


def test_request_body_capture_is_bounded_and_reports_drops():
    """Body capture must retain only its newest configured number of requests."""
    with running_server(request_body_capacity=2) as (_, base_url):
        for number in range(3):
            _completion(base_url, [_message("user", f"request-{number}")])
        state = _request(base_url, "/debug/state")[1]
    assert state["request_body_capacity"] == 2
    assert state["dropped_request_body_count"] == 1
    assert [record["request_number"] for record in state["request_bodies"]] == [2, 3]
    assert state["request_bodies"][-1]["body"]["messages"][0]["content"] == "request-2"


def test_malformed_request_body_is_captured_without_crashing_handler():
    """Malformed JSON must remain inspectable after the server returns HTTP 400."""
    with running_server() as (_, base_url):
        request = Request(
            base_url + "/v1/chat/completions",
            data=b"{invalid",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(HTTPError) as error:
            urlopen(request, timeout=3)
        state = _request(base_url, "/debug/state")[1]
    assert error.value.code == 400
    assert state["total_requests"] == 0
    assert state["request_bodies"] == [{
        "request_number": 1,
        "parsed": False,
        "body": None,
        "raw_body": "{invalid",
        "parse_error": "JSONDecodeError",
    }]


def test_native_tool_calls_response_is_openai_compatible_and_scripted():
    """Opt-in scripted tool calls must parse through the official OpenAI client."""
    tool_calls = (({
        "id": "call_mock_1",
        "type": "function",
        "function": {"name": "safe_tool", "arguments": "{\"value\":1}"},
    },),)
    with running_server(tool_call_responses=tool_calls, reply="finished") as (_, base_url):
        client = OpenAI(api_key="mock", base_url=base_url + "/v1")
        first = client.chat.completions.create(
            model="topsailai-mock",
            messages=[_message("user", "use tool")],
        )
        second = client.chat.completions.create(
            model="topsailai-mock",
            messages=[_message("user", "finish")],
        )
    call = first.choices[0].message.tool_calls[0]
    assert first.choices[0].finish_reason == "tool_calls"
    assert first.choices[0].message.content is None
    assert (call.id, call.type, call.function.name) == ("call_mock_1", "function", "safe_tool")
    assert json.loads(call.function.arguments) == {"value": 1}
    assert second.choices[0].message.content == "finished"
    assert second.choices[0].message.tool_calls is None
    assert second.choices[0].finish_reason == "stop"


def test_native_multi_tool_calls_response_preserves_parallel_shape():
    """One scripted response must preserve multiple independent tool calls."""
    calls = tuple({
        "id": f"call_mock_{number}",
        "type": "function",
        "function": {"name": f"tool_{number}", "arguments": "{}"},
    } for number in (1, 2))
    with running_server(tool_call_responses=(calls,)) as (_, base_url):
        response = _completion(base_url, [_message("user", "use both")])
    message = response["choices"][0]["message"]
    assert response["choices"][0]["finish_reason"] == "tool_calls"
    assert message["content"] is None
    assert [call["id"] for call in message["tool_calls"]] == ["call_mock_1", "call_mock_2"]


def test_default_non_streaming_response_shape_is_unchanged():
    """Unset tool-call scripting must preserve the legacy plain-content response."""
    with running_server(reply="unchanged") as (_, base_url):
        response = _completion(base_url, [_message("user", "hello")])
    assert response["choices"] == [{
        "index": 0,
        "message": {"role": "assistant", "content": "unchanged"},
        "finish_reason": "stop",
    }]


def test_openai_client_can_use_mock_endpoint():
    """The official client must parse cache usage from the mock response."""
    with running_server(reply="compatible") as (_, base_url):
        client = OpenAI(api_key="mock", base_url=base_url + "/v1")
        messages = [_message("user", "hello")]
        client.chat.completions.create(model="topsailai-mock", messages=messages)
        response = client.chat.completions.create(model="topsailai-mock", messages=messages)
    assert response.choices[0].message.content == "compatible"
    assert response.usage.prompt_tokens_details.cached_tokens == response.usage.prompt_tokens


def test_openai_client_can_consume_opt_in_sse_stream():
    """The official client must parse configured SSE chunks over real HTTP."""
    with running_server(stream_chunks=("first", " second")) as (server, base_url):
        client = OpenAI(api_key="mock", base_url=base_url + "/v1")
        stream = client.chat.completions.create(
            model="topsailai-mock",
            messages=[_message("user", "hello")],
            stream=True,
            stream_options={"include_usage": True},
        )
        chunks = list(stream)
    content = "".join(
        chunk.choices[0].delta.content or ""
        for chunk in chunks
        if chunk.choices
    )
    assert content == "first second"
    assert chunks[-1].usage.prompt_tokens > 0
    assert server.prompt_cache.state()["total_requests"] == 1


@pytest.mark.parametrize(
    "payload,error_text",
    [
        ({"messages": "invalid"}, "messages must be"),
        ({"messages": [], "stream": True}, "streaming is not supported"),
    ],
)
def test_invalid_completion_requests_return_openai_errors(payload, error_text):
    """Invalid request shapes must return clear OpenAI-compatible errors."""
    with running_server() as (_, base_url):
        with pytest.raises(HTTPError) as error:
            _request(base_url, "/v1/chat/completions", "POST", payload)
        body = json.loads(error.value.read())
    assert error.value.code == 400
    assert error_text in body["error"]["message"]


def test_invalid_json_and_unknown_delete_return_errors():
    """Malformed JSON and unsupported DELETE paths must be rejected."""
    with running_server() as (_, base_url):
        request = Request(
            base_url + "/v1/chat/completions",
            data=b"{",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(HTTPError) as invalid_json:
            urlopen(request, timeout=3)
        with pytest.raises(HTTPError) as unknown_delete:
            _request(base_url, "/missing", "DELETE")
    assert invalid_json.value.code == 400
    assert unknown_delete.value.code == 404


def test_parse_args_supports_explicit_configuration():
    """Command-line arguments must map to reusable server configuration fields."""
    args = parse_args([
        "--host", "0.0.0.0",
        "--port", "9000",
        "--model", "m",
        "--reply", "r",
        "--chars-per-token", "2",
        "--cache-capacity", "7",
    ])
    assert vars(args) == {
        "host": "0.0.0.0",
        "port": 9000,
        "model": "m",
        "reply": "r",
        "chars_per_token": 2,
        "cache_capacity": 7,
        "request_body_capacity": 32,
    }


def test_unknown_completion_path_returns_error():
    """Unsupported POST paths must return 404."""
    with running_server() as (_, base_url):
        with pytest.raises(HTTPError) as error:
            _request(base_url, "/missing", "POST", {"messages": []})
    assert error.value.code == 404


def test_non_object_json_body_returns_error():
    """A valid JSON body must still be an object."""
    with running_server() as (_, base_url):
        with pytest.raises(HTTPError) as error:
            _request(base_url, "/v1/chat/completions", "POST", [])
        body = json.loads(error.value.read())
    assert error.value.code == 400
    assert "JSON object" in body["error"]["message"]


def test_main_builds_config_serves_and_closes():
    """The launcher must serve with parsed settings and always close the server."""
    server = MagicMock()
    server.server_address = ("127.0.0.1", 8123)
    server.serve_forever.side_effect = KeyboardInterrupt
    with patch("topsailai.tests.mock.llm_mock_server.create_server", return_value=server) as create:
        main([
            "--host", "127.0.0.1",
            "--port", "8123",
            "--model", "model",
            "--reply", "reply",
            "--chars-per-token", "3",
            "--cache-capacity", "5",
            "--request-body-capacity", "6",
        ])
    config = create.call_args.args[0]
    assert config == MockServerConfig(
        host="127.0.0.1",
        port=8123,
        model="model",
        reply="reply",
        chars_per_token=3,
        cache_capacity=5,
        request_body_capacity=6,
    )
    server.serve_forever.assert_called_once_with()
    server.server_close.assert_called_once_with()
