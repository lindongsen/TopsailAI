"""Tests for the public JEV tool contract."""

from types import SimpleNamespace

import pytest

from topsailai.tools import jev_tool


def test_registration_and_docstring_contract():
    """The registered function exposes its string-first LLM contract."""
    assert jev_tool.TOOLS == {"evaluate": jev_tool.evaluate}
    doc = jev_tool.evaluate.__doc__ or ""
    for marker in ("JSON-object string", "noul", "choice", "score", "System messages", "invalid_request"):
        assert marker in doc

@pytest.mark.parametrize("value,reason", [
    ("bad", "invalid_questions_json"),
    ("[]", "questions_must_contain_1_to_32_entries"),
    ('{"": {"type":"noul","instructions":"x"}}', "invalid_question_id"),
    ('{"q": {"type":"bad","instructions":"x"}}', "invalid_question_type"),
    ('{"q": {"type":"choice","instructions":"x"}}', "missing_question_criteria"),
    ('{"q": {"type":"noul","instructions":"x","criteria":{}}}', "noul_criteria_not_supported"),
    ('{"q": {"type":"noul","instructions":"x","extra":1}}', "unknown_question_field"),
])
def test_invalid_questions_fail_before_configuration(value, reason):
    """Invalid caller input returns machine-readable validation errors."""
    result = jev_tool.evaluate(value)
    assert result["status"] == "invalid_request"
    assert result["reason"] == reason


def test_orchestration_uses_runtime_agent(monkeypatch):
    """Public evaluate loads trusted config and current Agent2LLM context."""
    expected = {"status": "ok", "model": "m", "answers": {}, "usage": {}}
    config = SimpleNamespace(api_key="key", max_context_messages=2, max_context_chars=100)
    agent = SimpleNamespace(messages=[{"role": "user", "content": "hello"}])
    monkeypatch.setattr(jev_tool, "load_config", lambda: config)
    monkeypatch.setattr(jev_tool, "get_agent_object", lambda: agent)
    monkeypatch.setattr(jev_tool, "build_state", lambda *args: {"agent2llm_messages": []})
    monkeypatch.setattr(jev_tool, "evaluate_remote", lambda *args: expected)
    result = jev_tool.evaluate('{"q":{"type":"noul","instructions":"yes?"}}')
    assert result is expected


@pytest.mark.parametrize("value,reason", [
    (None, "questions_must_be_json_string"),
    ('{"q":"bad"}', "question_must_be_object"),
    ('{"q":{"type":"noul","instructions":" "}}', "invalid_question_instructions"),
])
def test_additional_question_validation(value, reason):
    """Non-string, non-object, and empty-instruction inputs fail predictably."""
    result = jev_tool.evaluate(value)
    assert result["status"] == "invalid_request"
    assert result["reason"] == reason


def test_configuration_failure_is_safe(monkeypatch):
    """Configuration errors become bounded invalid-request results."""
    monkeypatch.setattr(
        jev_tool,
        "load_config",
        lambda: (_ for _ in ()).throw(jev_tool.JevConfigError("missing_config")),
    )
    result = jev_tool.evaluate('{"q":{"type":"noul","instructions":"yes?"}}')
    assert result == {
        "status": "invalid_request",
        "reason": "missing_config",
        "message": "Invalid JEV configuration",
        "retryable": False,
    }


def test_context_failure_is_safe(monkeypatch):
    """Unavailable runtime context becomes a machine-readable result."""
    config = SimpleNamespace(api_key="key", max_context_messages=2, max_context_chars=100)
    monkeypatch.setattr(jev_tool, "load_config", lambda: config)
    monkeypatch.setattr(jev_tool, "get_agent_object", lambda: None)
    monkeypatch.setattr(
        jev_tool,
        "build_state",
        lambda *args: (_ for _ in ()).throw(jev_tool.JevContextError("no_runtime_context")),
    )
    result = jev_tool.evaluate('{"q":{"type":"noul","instructions":"yes?"}}')
    assert result["status"] == "unavailable"
    assert result["reason"] == "no_runtime_context"
