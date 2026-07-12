"""
Unit tests for topsailai.events.decorators.
"""

import time

from topsailai.events.decorators import (
    record_approval_events,
    record_llm_chat_events,
    record_tool_call_events,
)


class FakeCollector:
    def __init__(self):
        self.events = []
        self.enabled = True

    def record(self, event_type, payload=None, session_id=None, **kwargs):
        self.events.append(
            {"event_type": event_type, "payload": payload, "session_id": session_id}
        )

    def flush(self):
        pass

    def close(self):
        pass


def test_record_tool_call_events_success():
    collector = FakeCollector()

    @record_tool_call_events(collector=collector, tool_name="demo")
    def demo_tool(x):
        return x * 2

    result = demo_tool(3)
    assert result == 6
    assert collector.events[0]["event_type"] == "tool_call.start"
    assert collector.events[1]["event_type"] == "tool_call.end"
    assert collector.events[1]["payload"]["success"] is True


def test_record_tool_call_events_error():
    collector = FakeCollector()

    @record_tool_call_events(collector=collector, tool_name="fail")
    def fail_tool():
        raise ValueError("boom")

    try:
        fail_tool()
    except ValueError:
        pass

    assert collector.events[0]["event_type"] == "tool_call.start"
    assert collector.events[1]["event_type"] == "tool_call.end"
    assert collector.events[1]["payload"]["success"] is False
    assert "boom" in collector.events[1]["payload"]["error"]


def test_record_tool_call_events_payload_has_duration_ms():
    collector = FakeCollector()

    @record_tool_call_events(collector=collector, tool_name="slow")
    def slow_tool():
        time.sleep(0.01)
        return "ok"

    slow_tool()
    end_payload = collector.events[1]["payload"]
    assert "duration_ms" in end_payload
    assert end_payload["duration_ms"] >= 10


def test_record_tool_call_events_payload_args_is_original_dict():
    collector = FakeCollector()
    original_args = {"a": 1, "b": 2}

    @record_tool_call_events(collector=collector, tool_name="with_args")
    def with_args_tool(tool_func, args, tool_name=""):
        return args

    with_args_tool(None, original_args, tool_name="with_args")
    end_payload = collector.events[1]["payload"]
    assert end_payload["args"] is original_args
    assert end_payload["args"] == {"a": 1, "b": 2}


def test_record_tool_call_events_payload_truncates_large_result():
    collector = FakeCollector()

    @record_tool_call_events(collector=collector, tool_name="big")
    def big_tool():
        return "x" * 20000

    big_tool()
    end_payload = collector.events[1]["payload"]
    assert end_payload["success"] is True
    assert len(end_payload["result"]) < 20000
    assert "truncated" in end_payload["result"]

def test_record_tool_call_events_payload_error_type():
    collector = FakeCollector()

    @record_tool_call_events(collector=collector, tool_name="err")
    def err_tool():
        raise RuntimeError("crash")

    try:
        err_tool()
    except RuntimeError:
        pass

    end_payload = collector.events[1]["payload"]
    assert end_payload["success"] is False
    assert end_payload["error_type"] == "RuntimeError"


def test_record_approval_events():
    collector = FakeCollector()

    @record_approval_events(collector=collector)
    def approve():
        return {"action": "allow", "rule_name": "r1"}

    result = approve()
    assert result["action"] == "allow"
    assert collector.events[0]["event_type"] == "tool_approval.decision"
    assert collector.events[0]["payload"]["decision"]["action"] == "allow"


def test_record_llm_chat_events_success():
    collector = FakeCollector()

    @record_llm_chat_events(collector=collector)
    def chat():
        return "hello"

    result = chat()
    assert result == "hello"
    assert collector.events[0]["event_type"] == "llm.request.start"
    assert collector.events[1]["event_type"] == "llm.response.success"


def test_record_llm_chat_events_error():
    collector = FakeCollector()

    @record_llm_chat_events(collector=collector)
    def chat():
        raise RuntimeError("llm failed")

    try:
        chat()
    except RuntimeError:
        pass

    assert collector.events[0]["event_type"] == "llm.request.start"
    assert collector.events[1]["event_type"] == "llm.response.error"
    assert "llm failed" in collector.events[1]["payload"]["error"]


def test_decorators_use_default_collector(monkeypatch, tmp_path):
    from topsailai.events import reset_event_collector

    path = str(tmp_path / "decorator.events")
    monkeypatch.setenv("TOPSAILAI_EVENTS_FILE_PATH", path)
    reset_event_collector()

    @record_tool_call_events(tool_name="x")
    def fn():
        return 1

    fn()
    reset_event_collector()

    with open(path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 2


def test_decorator_disabled_collector():
    collector = FakeCollector()
    collector.enabled = False

    @record_tool_call_events(collector=collector, tool_name="x")
    def fn():
        return 1

    fn()
    assert len(collector.events) == 0
