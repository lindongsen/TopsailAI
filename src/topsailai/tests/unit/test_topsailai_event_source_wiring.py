'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-11-13
  Purpose: Unit tests for wiring real event sources into approval and LLM flows.
'''

import threading

import pytest

from topsailai.ai_base.llm_control import request_events
from topsailai.ai_base.tool_approval import decorator as approval_decorator
from topsailai.ai_base.tool_approval.decorator import with_tool_approval
from topsailai.ai_base.tool_approval.exceptions import ToolApprovalDeniedError
from topsailai.ai_base.tool_approval.instance import (
    ApprovalDecision,
    set_default_approval_transport,
)
from topsailai.ai_base.tool_approval.transport import ApprovalTransport


class RecordingTransport(ApprovalTransport):
    """Transport that records requests and resolves them on demand."""

    def __init__(self, resolve_status=None):
        self.instances = []
        self._events = {}
        self._lock = threading.Lock()
        self._resolve_status = resolve_status

    def send_request(self, instance):
        self.instances.append(instance)
        with self._lock:
            self._events[instance.id] = threading.Event()
        if self._resolve_status is not None:
            self.resolve(instance.id, self._resolve_status)

    def wait_response(self, instance, timeout=None):
        with self._lock:
            event = self._events.get(instance.id)
        if event is None:
            return instance.status
        effective = timeout if timeout is not None else instance.timeout
        if event.wait(timeout=effective):
            return instance.status
        return instance.STATUS_TIMEOUT

    def on_resolved(self, instance):
        with self._lock:
            event = self._events.pop(instance.id, None)
        if event is not None:
            event.set()

    def supports_external_resolution(self):
        return True

    def resolve(self, instance_id, status):
        instance = next((i for i in self.instances if i.id == instance_id), None)
        if instance is None:
            return
        if status == "approve":
            instance.approve()
        elif status == "deny":
            instance.deny()


@pytest.fixture
def recorded_events(monkeypatch):
    """Capture every event recorded by both wired event sources."""
    captured = []

    def fake_record(event_type, payload):
        captured.append((event_type, payload))

    monkeypatch.setattr(approval_decorator, "record_event", fake_record)
    monkeypatch.setattr(request_events, "record_event", fake_record)
    return captured


def _make_ask_rule(monkeypatch, timeout=5, policy="deny"):
    """Force the approval decision to ASK with a deterministic rule."""
    decision = ApprovalDecision(
        action=ApprovalDecision.ASK,
        rule={"name": "test-rule"},
        timeout=timeout,
        policy=policy,
    )
    monkeypatch.setattr(
        approval_decorator.ToolApprovalInstance,
        "decide",
        lambda self: decision,
    )
    return decision


def _build_wrapped(transport):
    set_default_approval_transport(transport)

    @with_tool_approval
    def exec_tool_func(tool_func, args, tool_name=None, **kwargs):
        return tool_func(**args)

    return exec_tool_func


def _tool(**kwargs):
    return "tool-result"


class TestApprovalEventWiring:
    """Approval events must be emitted at the ASK branch only."""

    def test_ask_branch_records_request_and_decision(
        self, monkeypatch, recorded_events
    ):
        _make_ask_rule(monkeypatch)
        transport = RecordingTransport(resolve_status="approve")
        wrapped = _build_wrapped(transport)

        assert wrapped(_tool, {}, tool_name="demo_tool") == "tool-result"

        types = [event_type for event_type, _ in recorded_events]
        assert types == ["tool_approval.request", "tool_approval.decision"]

        request_payload = recorded_events[0][1]
        assert request_payload["tool_name"] == "demo_tool"
        assert request_payload["rule_name"] == "test-rule"
        assert request_payload["timeout"] == 5
        assert request_payload["policy"] == "deny"

        decision_payload = recorded_events[1][1]
        assert decision_payload["tool_name"] == "demo_tool"
        assert decision_payload["rule_name"] == "test-rule"
        assert decision_payload["status"] == "approved"

    def test_denied_decision_still_records_before_raising(
        self, monkeypatch, recorded_events
    ):
        _make_ask_rule(monkeypatch)
        transport = RecordingTransport(resolve_status="deny")
        wrapped = _build_wrapped(transport)

        with pytest.raises(ToolApprovalDeniedError):
            wrapped(_tool, {}, tool_name="demo_tool")

        types = [event_type for event_type, _ in recorded_events]
        assert types == ["tool_approval.request", "tool_approval.decision"]
        assert recorded_events[1][1]["status"] == "denied"

    def test_no_approval_path_records_nothing(self, monkeypatch, recorded_events):
        decision = ApprovalDecision(action=ApprovalDecision.NO_APPROVAL)
        monkeypatch.setattr(
            approval_decorator.ToolApprovalInstance,
            "decide",
            lambda self: decision,
        )
        transport = RecordingTransport()
        wrapped = _build_wrapped(transport)

        assert wrapped(_tool, {}, tool_name="demo_tool") == "tool-result"
        assert recorded_events == []

    def test_allow_path_records_nothing(self, monkeypatch, recorded_events):
        decision = ApprovalDecision(action=ApprovalDecision.ALLOW)
        monkeypatch.setattr(
            approval_decorator.ToolApprovalInstance,
            "decide",
            lambda self: decision,
        )
        transport = RecordingTransport()
        wrapped = _build_wrapped(transport)

        assert wrapped(_tool, {}, tool_name="demo_tool") == "tool-result"
        assert recorded_events == []

    def test_payload_never_contains_tool_arguments(
        self, monkeypatch, recorded_events
    ):
        _make_ask_rule(monkeypatch)
        transport = RecordingTransport(resolve_status="approve")
        wrapped = _build_wrapped(transport)

        secret_args = {"password": "super-secret-value", "path": "/etc/shadow"}
        wrapped(_tool, secret_args, tool_name="demo_tool")

        serialized = repr(recorded_events)
        assert "super-secret-value" not in serialized
        assert "/etc/shadow" not in serialized

    def test_recording_failure_does_not_change_approval_outcome(
        self, monkeypatch
    ):
        _make_ask_rule(monkeypatch)

        def exploding_record(event_type, payload):
            raise RuntimeError("event backend exploded")

        monkeypatch.setattr(approval_decorator, "record_event", exploding_record)
        transport = RecordingTransport(resolve_status="approve")
        wrapped = _build_wrapped(transport)

        assert wrapped(_tool, {}, tool_name="demo_tool") == "tool-result"

    def test_recording_failure_does_not_mask_denial(self, monkeypatch):
        _make_ask_rule(monkeypatch)

        def exploding_record(event_type, payload):
            raise RuntimeError("event backend exploded")

        monkeypatch.setattr(approval_decorator, "record_event", exploding_record)
        transport = RecordingTransport(resolve_status="deny")
        wrapped = _build_wrapped(transport)

        with pytest.raises(ToolApprovalDeniedError):
            wrapped(_tool, {}, tool_name="demo_tool")


class TestLlmRequestEventPayloads:
    """LLM request payloads must stay bounded and content-free."""

    def test_start_payload_records_only_metadata(self):
        payload = request_events.build_llm_request_start_payload(
            operation_id="op-1",
            model_name="test-model",
            messages=[{"role": "user", "content": "secret prompt text"}],
            stream=True,
            return_mode="parsed",
        )

        assert payload == {
            "operation_id": "op-1",
            "model_name": "test-model",
            "message_count": 1,
            "stream": True,
            "return_mode": "parsed",
        }
        assert "secret prompt text" not in repr(payload)

    def test_start_payload_handles_none_messages(self):
        payload = request_events.build_llm_request_start_payload(
            operation_id="op-1",
            model_name=None,
            messages=None,
            stream=False,
            return_mode="raw",
        )

        assert payload["message_count"] == 0
        assert payload["model_name"] == ""

    def test_start_payload_handles_unmeasurable_messages(self):
        payload = request_events.build_llm_request_start_payload(
            operation_id="op-1",
            model_name="m",
            messages=42,
            stream=False,
            return_mode="raw",
        )

        assert payload["message_count"] == 0

    def test_end_payload_omits_error_category_on_success(self):
        payload = request_events.build_llm_request_end_payload(
            operation_id="op-1",
            model_name="test-model",
            outcome="success",
            attempt_count=1,
            duration_sec=1.23456,
        )

        assert payload["outcome"] == "success"
        assert payload["attempt_count"] == 1
        assert payload["duration_sec"] == 1.235
        assert "error_category" not in payload

    def test_end_payload_includes_error_category_on_failure(self):
        payload = request_events.build_llm_request_end_payload(
            operation_id="op-1",
            model_name="test-model",
            outcome="exhausted",
            attempt_count=18,
            duration_sec=2.0,
            error_category="LLMProviderTimeoutError",
        )

        assert payload["outcome"] == "exhausted"
        assert payload["error_category"] == "LLMProviderTimeoutError"

    def test_end_payload_truncates_long_error_category(self):
        payload = request_events.build_llm_request_end_payload(
            operation_id="op-1",
            model_name="m",
            outcome="exhausted",
            attempt_count=1,
            duration_sec=0.0,
            error_category="X" * 500,
        )

        assert len(payload["error_category"]) == 128

    def test_record_llm_request_event_swallows_malformed_payload(self):
        """A malformed payload must not raise into the business path."""
        request_events.record_llm_request_event("llm.request.end", None)

    def test_record_llm_request_event_swallows_failures(self, monkeypatch):
        def exploding_record(event_type, payload):
            raise RuntimeError("backend exploded")

        monkeypatch.setattr(request_events, "record_event", exploding_record)

        # Must not raise.
        request_events.record_llm_request_event("llm.request.start", {"a": 1})


class TestLlmRequestLifecyclePairing:
    """Every logical LLM request must emit one start and one terminal end."""

    @staticmethod
    def _build_model(monkeypatch, recorded_events):
        """Build a minimal LLMModel whose chat() reaches the retry loop."""
        from topsailai.ai_base import llm_base

        model = object.__new__(llm_base.LLMModel)
        model.model_name = "test-model"
        return model, llm_base

    def test_start_event_precedes_retry_loop(self, monkeypatch, recorded_events):
        """The start event is emitted once, before any attempt runs."""
        payload = request_events.build_llm_request_start_payload(
            operation_id="op-1",
            model_name="test-model",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
            return_mode="parsed",
        )
        request_events.record_llm_request_event("llm.request.start", payload)

        starts = [e for e in recorded_events if e[0] == "llm.request.start"]
        assert len(starts) == 1
        assert starts[0][1]["message_count"] == 1
        assert starts[0][1]["stream"] is True

    def test_terminal_outcomes_are_distinct_categories(self):
        """Each terminal exit uses a category that names its own cause."""
        outcomes = {}
        for outcome, category in (
            ("success", None),
            ("exhausted", "LLMRetryExhaustedError"),
            ("abandoned", "LLMBackToChatError"),
            ("failed", "LLMProviderBadRequestError"),
        ):
            payload = request_events.build_llm_request_end_payload(
                operation_id="op-1",
                model_name="test-model",
                outcome=outcome,
                attempt_count=1,
                duration_sec=0.5,
                error_category=category,
            )
            outcomes[outcome] = payload

        assert outcomes["success"]["outcome"] == "success"
        assert "error_category" not in outcomes["success"]
        assert outcomes["exhausted"]["error_category"] == "LLMRetryExhaustedError"
        assert outcomes["abandoned"]["error_category"] == "LLMBackToChatError"
        assert outcomes["failed"]["error_category"] == "LLMProviderBadRequestError"

    def test_hard_interrupt_records_terminal_event_and_preserves_exception(
        self, monkeypatch, recorded_events
    ):
        """A hard interrupt is observable without changing control flow."""
        from topsailai.ai_base import llm_base
        from topsailai.ai_base.exception import HardInterruptError

        interrupt = HardInterruptError("stop now")

        class InterruptingAgent:
            """Raise the exact host interruption from the production check seam."""

            def _check_hard_interrupt(self):
                raise interrupt

        model, _ = self._build_model(monkeypatch, recorded_events)
        monkeypatch.setattr(llm_base, "get_agent_object", lambda: InterruptingAgent())

        with pytest.raises(HardInterruptError) as captured:
            model.chat([{"role": "user", "content": "private prompt"}])

        assert captured.value is interrupt
        assert [event_type for event_type, _ in recorded_events] == [
            "llm.request.start",
            "llm.request.end",
        ]
        start_payload = recorded_events[0][1]
        end_payload = recorded_events[1][1]
        assert end_payload["operation_id"] == start_payload["operation_id"]
        assert end_payload["outcome"] == "interrupted"
        assert end_payload["error_category"] == "HardInterruptError"
        assert "private prompt" not in repr(recorded_events)

    def test_keyboard_interrupt_records_terminal_event_and_stays_host_interrupt(
        self, monkeypatch, recorded_events
    ):
        """KeyboardInterrupt remains a BaseException while gaining an end event."""
        from topsailai.ai_base import llm_base

        interrupt = KeyboardInterrupt("operator interrupt")

        class InterruptingAgent:
            """Raise the exact host interruption from the production check seam."""

            def _check_hard_interrupt(self):
                raise interrupt

        model, _ = self._build_model(monkeypatch, recorded_events)
        monkeypatch.setattr(llm_base, "get_agent_object", lambda: InterruptingAgent())

        with pytest.raises(KeyboardInterrupt) as captured:
            model.chat([{"role": "user", "content": "private prompt"}])

        assert captured.value is interrupt
        assert [event_type for event_type, _ in recorded_events] == [
            "llm.request.start",
            "llm.request.end",
        ]
        assert recorded_events[1][1]["outcome"] == "interrupted"
        assert recorded_events[1][1]["error_category"] == "KeyboardInterrupt"

    @pytest.mark.parametrize(
        ("outcome", "error_category"),
        (
            ("abandoned", "LLMBackToChatError"),
            ("exhausted", "LLMRetryExhaustedError"),
            ("failed", "LLMProviderBadRequestError"),
        ),
    )
    def test_existing_exception_terminal_event_is_not_duplicated(
        self, recorded_events, outcome, error_category
    ):
        """An existing exceptional end remains the sole terminal event."""
        original = RuntimeError("original control flow")

        @request_events.track_llm_request_events
        def request(_model):
            request_events.record_llm_request_event(
                "llm.request.start",
                request_events.build_llm_request_start_payload(
                    operation_id="op-existing-end",
                    model_name="test-model",
                    messages=[],
                    stream=False,
                    return_mode="parsed",
                ),
            )
            request_events.record_llm_request_event(
                "llm.request.end",
                request_events.build_llm_request_end_payload(
                    operation_id="op-existing-end",
                    model_name="test-model",
                    outcome=outcome,
                    attempt_count=2,
                    duration_sec=0.1,
                    error_category=error_category,
                ),
            )
            raise original

        with pytest.raises(RuntimeError) as captured:
            request(object())

        assert captured.value is original
        assert [event_type for event_type, _ in recorded_events] == [
            "llm.request.start",
            "llm.request.end",
        ]
        assert recorded_events[1][1]["outcome"] == outcome
        assert recorded_events[1][1]["error_category"] == error_category

    def test_existing_terminal_event_is_not_duplicated(
        self, monkeypatch, recorded_events
    ):
        """The lifecycle owner does not duplicate an end emitted by chat()."""
        from topsailai.ai_base import llm_base

        model, _ = self._build_model(monkeypatch, recorded_events)
        monkeypatch.setattr(llm_base, "get_agent_object", lambda: None)
        model.call_llm_model = lambda *args, **kwargs: (object(), "answer")
        model._split_native_tool_call_response = (
            lambda response, content: (response, content, 1, 1)
        )
        model._return_chat_response = lambda *args, **kwargs: ["success"]
        model.tokenStat = type(
            "TokenStat", (), {"current_tokens": 0, "current_cached_tokens": 0}
        )()

        assert model.chat([{"role": "user", "content": "private prompt"}]) == [
            "success"
        ]
        assert [event_type for event_type, _ in recorded_events] == [
            "llm.request.start",
            "llm.request.end",
        ]
        assert recorded_events[1][1]["outcome"] == "success"
