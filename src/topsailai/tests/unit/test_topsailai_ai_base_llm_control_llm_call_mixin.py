"""Unit tests for provider-neutral LLM call orchestration."""

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

from topsailai.ai_base.llm_control.llm_call_mixin import LLMCallMixin


class ExampleCallModel(LLMCallMixin):
    """Exercise the mixin with an unrelated provider representation."""

    def __init__(self):
        """Initialize deterministic collaborators for call orchestration tests."""
        self.tokenStat = MagicMock()
        self.content_senders = []
        self.events = []
        self.sent = []
        self.complete_response = {"text": " complete "}
        self.stream_response = iter(
            [
                {"text": " first ", "calls": [{"key": "a", "part": "x"}]},
                {"text": "second", "calls": [{"key": "a", "part": "y"}]},
            ]
        )

    def _get_first_byte_timeout_config(self):
        """Return a deterministic timeout configuration."""
        return 2, False

    def _create_with_first_byte_timeout(self, messages, **kwargs):
        """Return the configured complete response or stream iterator."""
        if kwargs["stream"]:
            return self.stream_response, False
        return self.complete_response

    def _extract_response_content(self, response):
        """Extract content from the example provider response."""
        return response["text"]

    def _extract_stream_part(self, chunk):
        """Treat an example provider chunk as its stream part."""
        return chunk

    def _extract_stream_content(self, stream_part):
        """Extract content from an example provider stream part."""
        return stream_part["text"]

    def _merge_stream_calls(self, accumulated_calls, stream_part):
        """Accumulate example provider call fragments."""
        for call in stream_part["calls"]:
            accumulated_calls[call["key"]] = (
                accumulated_calls.get(call["key"], "") + call["part"]
            )

    def _build_stream_calls(self, accumulated_calls):
        """Build example provider completed calls."""
        return sorted(accumulated_calls.items())

    def _build_stream_response(self, content, completed_calls):
        """Build the example provider final response."""
        return {"text": content, "calls": completed_calls}

    def get_response_usage(self, response):
        """Return example usage when a response supplies it."""
        return response.get("usage") if isinstance(response, dict) else None

    def fix_response_content(self, rsp_obj, rsp_content):
        """Preserve content to expose orchestration ordering."""
        return rsp_content

    def check_response_content(self, rsp_obj, rsp_content):
        """Accept all example provider content."""

    def send_content(self, content):
        """Record content sent by the orchestration layer."""
        self.sent.append(content)

    def _record_llm_response_event(self, response, **kwargs):
        """Record response-event invocation arguments."""
        self.events.append((response, kwargs))

    def _get_stream_chunk_sample_limit(self):
        """Disable chunk sampling for the focused behavior test."""
        return 0

    def _get_llm_request_timing_ticket(self):
        """Return no active timing ticket in this isolated test."""
        return None

    def _iter_stream_for_request_timing(self, response, ticket):
        """Return the example stream unchanged."""
        return response

    def iter_stream_with_first_byte_timeout(self, response, *args, **kwargs):
        """Return the example stream unchanged after timeout adaptation."""
        return response

    def _observe_stream_usage(self, usage, diagnostics):
        """Record example usage cardinality."""
        diagnostics["seen"] = diagnostics.get("seen", 0) + 1

    def _warn_stream_usage_error(self, error):
        """Fail if usage inspection unexpectedly raises."""
        raise AssertionError(error)

    def _serialize_stream_chunk(self, chunk):
        """Return a serializable example chunk."""
        return chunk

    def _check_stream_interrupt(self):
        """Accept continued execution in this isolated test."""

    def _finish_stream_debug_output(self):
        """Avoid console output in this isolated test."""

    def _log_final_stream_usage(self, usage, diagnostics):
        """Retain final diagnostics for assertions."""
        self.final_diagnostics = diagnostics


def test_complete_call_orchestration_is_provider_neutral():
    """The mixin coordinates a complete response through generic hooks."""
    model = ExampleCallModel()

    response, content = model.call_llm_model([{"text": "question"}])

    assert response is model.complete_response
    assert content == " complete "
    assert model.sent == [" complete "]
    model.tokenStat.finalize_usage.assert_called_once()
    assert model.events == [(response, {"is_stream": False})]


def test_stream_call_orchestration_reconstructs_provider_response():
    """The mixin reconstructs streamed content and calls through generic hooks."""
    model = ExampleCallModel()
    sender = SimpleNamespace(finish=MagicMock())
    model.content_senders = [sender]

    response, content = model.call_llm_model_by_stream([{"text": "question"}])

    assert content == "first second"
    assert response == {"text": "first second", "calls": [("a", "xy")]}
    assert model.sent == [" first ", "second"]
    sender.finish.assert_called_once_with()
    model.tokenStat.finalize_usage.assert_called_once()
    assert model.events == [
        (response, {"is_stream": True, "sampled_chunks": None})
    ]


def test_mixin_source_has_no_provider_sdk_traces():
    """The reusable mixin must not encode the current provider SDK contract."""
    source = inspect.getsource(inspect.getmodule(LLMCallMixin)).lower()

    forbidden_terms = (
        "open" + "ai",
        "cho" + "ices",
        "chat" + "completion",
        "api" + "timeout" + "error",
        "chat" + "_model.create",
    )
    for forbidden in forbidden_terms:
        assert forbidden not in source
