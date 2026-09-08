"""Unit tests for provider-neutral native tool-call response handling."""

import inspect
from unittest.mock import MagicMock, patch

from topsailai.ai_base.llm_control.native_tool_calls import (
    NativeToolCallResponseMixin,
)


class NativeToolCallModel(NativeToolCallResponseMixin):
    """Minimal provider adapter for exercising the reusable mixin."""

    def __init__(self):
        """Initialize adapter observations without creating pending state."""
        self.built_responses = []
        self.cleared_counts = []
        self.split_counts = []

    def get_response_message(self, response):
        """Return the test response directly as its provider message."""
        return response

    def fix_response_content(self, rsp_obj, rsp_content):
        """Return provider content unchanged for deterministic assertions."""
        return rsp_content

    def _build_single_native_tool_call_response(self, *, content, tool_call):
        """Build one provider-neutral test response dictionary."""
        response = MagicMock(content=content, tool_calls=[tool_call])
        self.built_responses.append(response)
        return response

    def _on_native_tool_call_responses_cleared(self, pending_count):
        """Record cleanup observations."""
        self.cleared_counts.append(pending_count)

    def _on_native_tool_call_response_split(self, total_tool_calls):
        """Record split observations."""
        self.split_counts.append(total_tool_calls)


def test_pending_queue_is_lazy_and_clear_preserves_identity():
    """Pending response state is optional, stable, and idempotently cleared."""
    model = NativeToolCallModel()

    assert not hasattr(model, "_pending_native_tool_call_responses")
    queue = model._get_pending_native_tool_call_responses()
    queue.append((object(), "content", 1, 1))

    model.clear_pending_native_tool_call_responses()
    model.clear_pending_native_tool_call_responses()

    assert model._get_pending_native_tool_call_responses() is queue
    assert list(queue) == []
    assert model.cleared_counts == [1]


def test_single_native_tool_call_preserves_original_response_identity():
    """A response with one tool call remains untouched and unqueued."""
    model = NativeToolCallModel()
    response = MagicMock(tool_calls=[object()])

    result = model._split_native_tool_call_response(response, "content")

    assert result == (response, "content", 1, 1)
    assert result[0] is response
    assert not hasattr(model, "_pending_native_tool_call_responses")
    assert model.built_responses == []
    assert model.split_counts == []


def test_multiple_native_tool_calls_preserve_fifo_and_first_content_only():
    """Multiple tool calls become ordered responses with one raw-content copy."""
    model = NativeToolCallModel()
    tool_calls = [object(), object(), object()]
    response = MagicMock(tool_calls=tool_calls)

    first = model._split_native_tool_call_response(response, "provider content")
    queue = model._get_pending_native_tool_call_responses()

    assert first == (model.built_responses[0], "provider content", 1, 3)
    assert list(queue) == [
        (model.built_responses[1], "", 2, 3),
        (model.built_responses[2], "", 3, 3),
    ]
    assert [item.tool_calls[0] for item in model.built_responses] == tool_calls
    assert [item.content for item in model.built_responses] == [
        "provider content",
        "",
        "",
    ]
    assert model.split_counts == [3]


def test_llm_model_retains_native_tool_call_class_level_compatibility_seams():
    """Existing LLMModel patch, signature, and introspection seams remain."""
    from topsailai.ai_base.llm_base import LLMModel

    expected_methods = {
        "_get_pending_native_tool_call_responses",
        "clear_pending_native_tool_call_responses",
        "_split_native_tool_call_response",
    }

    assert expected_methods.issubset(LLMModel.__dict__)
    assert inspect.signature(
        LLMModel._split_native_tool_call_response
    ) == inspect.signature(
        NativeToolCallResponseMixin._split_native_tool_call_response
    )


@patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
def test_llm_model_adapter_builds_openai_synthetic_message(mock_base_init):
    """The OpenAI adapter constructs one provider message per split unit."""
    from openai.types.chat import ChatCompletionMessageToolCall
    from topsailai.ai_base.llm_base import LLMModel

    tool_call = ChatCompletionMessageToolCall(
        id="call-1",
        type="function",
        function={"name": "tool_one", "arguments": "{}"},
    )
    model = LLMModel()

    response = model._build_single_native_tool_call_response(
        content="provider content",
        tool_call=tool_call,
    )

    assert response.role == "assistant"
    assert response.content == "provider content"
    assert response.tool_calls == [tool_call]


@patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
def test_llm_model_split_wrapper_remains_patchable_from_chat(mock_base_init):
    """Class-level patches continue to intercept chat's established split seam."""
    from topsailai.ai_base.llm_base import LLMModel

    model = LLMModel()
    model.tokenStat = MagicMock(current_tokens=1, current_cached_tokens=0)
    provider_response = object()
    model.call_llm_model = MagicMock(
        return_value=(provider_response, "provider content")
    )
    expected_response = object()
    expected_split = (expected_response, "content", 1, 1)
    expected_result = object()
    model._return_chat_response = MagicMock(return_value=expected_result)

    with patch.object(
        LLMModel,
        "_split_native_tool_call_response",
        return_value=expected_split,
    ) as split:
        result = model.chat([{"role": "user", "content": "hello"}])

    assert result is expected_result
    split.assert_called_once_with(provider_response, "provider content")
    model._return_chat_response.assert_called_once_with(
        expected_response,
        "content",
        [{"role": "user", "content": "hello"}],
        for_response=False,
    )
