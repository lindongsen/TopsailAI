"""Unit tests for the `/agent.tokens` plugin instruction."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from topsailai.workspace.context.base import ContextWatermarkResult
from topsailai.workspace.context.instruction import ContextRuntimeInstructions
from topsailai.workspace.plugin_instruction.agent import INSTRUCTIONS, get_tokens


def _agent(messages=None):
    """Build a minimal active agent for token-report tests."""
    return SimpleNamespace(
        messages=[] if messages is None else messages,
        llm_model=SimpleNamespace(model_name="test-model", max_tokens=1000),
    )


def _watermark(current_tokens=2500):
    """Build a representative existing watermark result."""
    return ContextWatermarkResult(
        level="NORMAL",
        current_tokens=current_tokens,
        safe_tokens=current_tokens,
        model_max_context=10000,
        max_tokens=1000,
        summary_safe_limit=8000,
        send_limit=9000,
        low_limit=5840,
        high_limit=7440,
    )


def test_agent_tokens_is_registered_exactly_once():
    """Register `/agent.tokens` only through the context-bound instruction map."""
    runtime_instructions = ContextRuntimeInstructions(MagicMock()).instructions

    registrations = int("tokens" in INSTRUCTIONS) + int(
        "agent.tokens" in runtime_instructions
    )

    assert registrations == 1
    assert "tokens" not in INSTRUCTIONS
    assert runtime_instructions["agent.tokens"].__self__.__class__ is ContextRuntimeInstructions


@patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent", return_value=None)
def test_get_tokens_without_active_agent(mock_get_ai_agent):
    """Return a clear diagnostic when no active agent exists."""
    assert get_tokens() == "No active agent"


def test_get_tokens_reports_both_snapshots_and_context_capacity():
    """Count both canonical layers and reuse the existing watermark result."""
    agent_messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "runtime"},
    ]
    session_messages = [{"role": "user", "content": "persisted"}]
    runtime = SimpleNamespace(
        ai_agent=_agent(agent_messages),
        messages=session_messages,
        session_id="session-1",
        _get_current_tokens=MagicMock(side_effect=[2500, 500]),
        _classify_context_watermark=MagicMock(return_value=_watermark()),
    )

    report = get_tokens(runtime)

    token_calls = runtime._get_current_tokens.call_args_list
    assert token_calls[0].args[0] == agent_messages
    assert token_calls[0].args[0] is not agent_messages
    assert token_calls[1].args[0] == session_messages
    assert token_calls[1].args[0] is not session_messages
    runtime._classify_context_watermark.assert_called_once_with(
        current_tokens=2500,
        model_name="test-model",
        max_tokens=1000,
    )
    assert "Model: test-model" in report
    assert "Agent2LLM:\n  Messages: 2\n  Estimated tokens: 2,500" in report
    assert "User2Agent:\n  Messages: 1\n  Estimated tokens: 500" in report
    assert "Model maximum: 10,000" in report
    assert "Completion reserve: 1,000" in report
    assert "Input send limit: 9,000" in report
    assert "Agent2LLM usage: 27.8%" in report
    assert "Watermark: NORMAL" in report


def test_get_tokens_labels_ephemeral_empty_session():
    """Label an unsaved session while still counting both empty collections."""
    runtime = SimpleNamespace(
        ai_agent=_agent([]),
        messages=[],
        session_id="",
        _get_current_tokens=MagicMock(side_effect=[0, 0]),
        _classify_context_watermark=MagicMock(return_value=None),
    )

    report = get_tokens(runtime)

    assert "Agent2LLM:\n  Messages: 0\n  Estimated tokens: 0" in report
    assert "User2Agent: (ephemeral/unsaved session)" in report
    assert "User2Agent: (ephemeral/unsaved session)\n  Messages: 0" in report
    assert "Model maximum: unavailable" in report
    assert "Agent2LLM usage:" not in report
    assert "Watermark:" not in report


def test_get_tokens_reports_unavailable_on_counting_failure():
    """Never disguise token-count failures as zero."""
    runtime = SimpleNamespace(
        ai_agent=_agent([{"role": "user", "content": "runtime"}]),
        messages=[{"role": "user", "content": "session"}],
        session_id="session-1",
        _get_current_tokens=MagicMock(side_effect=[None, None]),
        _classify_context_watermark=MagicMock(),
    )

    report = get_tokens(runtime)

    assert report.count("Estimated tokens: unavailable") == 2
    assert "Model maximum: unavailable" in report
    runtime._classify_context_watermark.assert_not_called()


def test_get_tokens_omits_ratio_when_model_limit_is_unknown():
    """Keep token counts visible when no model context limit is configured."""
    runtime = SimpleNamespace(
        ai_agent=_agent([{"role": "user", "content": "runtime"}]),
        messages=[{"role": "user", "content": "session"}],
        session_id="session-1",
        _get_current_tokens=MagicMock(side_effect=[100, 50]),
        _classify_context_watermark=MagicMock(return_value=None),
    )

    report = get_tokens(runtime)

    assert "Estimated tokens: 100" in report
    assert "Estimated tokens: 50" in report
    assert "Model maximum: unavailable" in report
    assert "Agent2LLM usage:" not in report
    assert "Watermark:" not in report


def test_context_runtime_instructions_binds_canonical_runtime_data():
    """Override the plugin fallback with a handler bound to runtime data."""
    runtime = MagicMock()
    instructions = ContextRuntimeInstructions(runtime)

    with patch(
        "topsailai.workspace.context.instruction.get_tokens",
        return_value="token report",
    ) as mock_get_tokens:
        result = instructions.instructions["agent.tokens"]()

    assert result == "token report"
    mock_get_tokens.assert_called_once_with(runtime)
