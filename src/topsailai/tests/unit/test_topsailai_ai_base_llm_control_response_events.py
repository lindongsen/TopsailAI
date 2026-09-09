"""Tests for provider-neutral LLM response event behavior."""

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from topsailai.ai_base.llm_base import LLMModel
from topsailai.ai_base.llm_control.response_events import LLMResponseEventMixin


class ResponseEventHost(LLMResponseEventMixin):
    """Provide the host contract for response-event mixin tests."""

    model_name = "test-model"

    def get_response_message(self, response):
        """Return the test response message."""
        return response.message


def test_response_event_mixin_builds_provider_neutral_payload():
    """The mixin serializes content, tool calls, raw data, and samples."""
    tool_call = SimpleNamespace(
        id="call-1",
        type="function",
        function=SimpleNamespace(name="lookup", arguments='{"id":1}'),
    )
    response = SimpleNamespace(
        message=SimpleNamespace(content="result", tool_calls=[tool_call]),
        to_dict=lambda: {"id": "response-1"},
    )

    with patch(
        "topsailai.ai_base.llm_control.response_events.env_tool"
    ) as env_tool, patch("topsailai.events.record_event") as record_event:
        env_tool.EnvReaderInstance.check_bool.side_effect = [True, True]
        env_tool.EnvReaderInstance.get.return_value = 100000
        ResponseEventHost()._record_llm_response_event(
            response,
            is_stream=True,
            sampled_chunks=[{"chunk": 1}],
        )

    record_event.assert_called_once_with(
        "llm.response.raw",
        payload={
            "model": "test-model",
            "is_stream": True,
            "content": "result",
            "tool_calls": [{
                "id": "call-1",
                "type": "function",
                "function": {"name": "lookup", "arguments": '{"id":1}'},
            }],
            "raw_response": {"id": "response-1"},
            "sampled_chunks": [{"chunk": 1}],
        },
        source="ai_base.llm_base",
    )


def test_response_event_mixin_is_safe_and_honors_disabled_mode():
    """Disabled recording and adapter failures never call or escape."""
    host = ResponseEventHost()
    response = SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))

    with patch(
        "topsailai.ai_base.llm_control.response_events.env_tool"
    ) as env_tool, patch("topsailai.events.record_event") as record_event:
        env_tool.EnvReaderInstance.check_bool.return_value = False
        host._record_llm_response_event(response)
        record_event.assert_not_called()

        env_tool.EnvReaderInstance.check_bool.side_effect = [True, True]
        env_tool.EnvReaderInstance.get.return_value = 100000
        host.get_response_message = MagicMock(
            side_effect=RuntimeError("provider failure")
        )
        host._record_llm_response_event(response)
        record_event.assert_not_called()


def test_llm_model_inherits_response_event_methods_and_signature():
    """LLMModel inherits the complete response-event implementation."""
    method_names = {
        "_record_llm_response_event",
        "_truncate_event_payload",
        "_get_llm_response_event_message",
        "_get_llm_response_event_model_name",
        "_serialize_llm_response_event_tool_calls",
        "_serialize_llm_response_event_raw",
    }
    assert method_names.isdisjoint(LLMModel.__dict__)
    assert method_names <= LLMResponseEventMixin.__dict__.keys()
    assert str(inspect.signature(LLMModel._record_llm_response_event)) == (
        "(self, response, is_stream=False, sampled_chunks=None)"
    )


def test_llm_model_mixin_reads_configuration_and_dispatches():
    """The response-event module configuration controls mixin dispatch."""
    model = object.__new__(LLMModel)
    model.model_name = "patched-model"
    response = SimpleNamespace(
        message=SimpleNamespace(content="patched", tool_calls=None),
        to_dict=lambda: {"id": "patched-response"},
    )
    model.get_response_message = MagicMock(return_value=response.message)

    with patch(
        "topsailai.ai_base.llm_control.response_events.env_tool"
    ) as env_tool, patch("topsailai.events.record_event") as record_event:
        env_tool.EnvReaderInstance.check_bool.side_effect = [True, False]
        env_tool.EnvReaderInstance.get.return_value = 1234
        model._record_llm_response_event(response)

    env_tool.EnvReaderInstance.check_bool.assert_any_call(
        "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED", default=True
    )
    env_tool.EnvReaderInstance.check_bool.assert_any_call(
        "TOPSAILAI_LLM_RESPONSE_EVENTS_INCLUDE_RAW", default=True
    )
    record_event.assert_called_once_with(
        "llm.response.raw",
        payload={
            "model": "patched-model",
            "is_stream": False,
            "content": "patched",
            "tool_calls": None,
        },
        source="ai_base.llm_base",
    )


def test_call_path_remains_interceptable_on_llm_model():
    """The non-streaming call uses the inherited patchable event method."""
    model = object.__new__(LLMModel)
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))]
    )
    model.tokenStat = MagicMock()
    model._get_first_byte_timeout_config = MagicMock(return_value=(0, False))
    model._create_with_first_byte_timeout = MagicMock(return_value=response)
    model.get_response_usage = MagicMock(return_value=None)
    model.fix_response_content = MagicMock(return_value="answer")
    model.check_response_content = MagicMock()
    model.send_content = MagicMock()

    with patch.object(LLMModel, "_record_llm_response_event") as record_event:
        result = LLMModel.call_llm_model.__wrapped__.__wrapped__(model, [])

    assert result == (response, "answer")
    record_event.assert_called_once_with(response, is_stream=False)
