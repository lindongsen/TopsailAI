"""Tests for dynamic context-window enforcement at the pre-chat checkpoint."""

from unittest.mock import Mock, patch

import pytest

from topsailai.workspace.context.base import (
    CONTEXT_WATERMARK_HARD,
    CONTEXT_WATERMARK_HIGH,
    CONTEXT_WATERMARK_LOW,
    CONTEXT_WATERMARK_NORMAL,
    ContextWatermarkResult,
)


def _watermark(level, current_tokens, send_limit=900):
    """Build one classified context snapshot for hook tests."""
    return ContextWatermarkResult(
        level=level,
        current_tokens=current_tokens,
        safe_tokens=current_tokens,
        model_max_context=1000,
        max_tokens=100,
        summary_safe_limit=800,
        send_limit=send_limit,
        low_limit=584,
        high_limit=744,
    )


def _build_agent_chat(classifications, processing_answer="summary"):
    """Build an AgentChatBase whose pre-chat hook can be called directly."""
    from topsailai.workspace.agent.agent_chat_base import AgentChatBase

    ai_agent = Mock()
    ai_agent.messages = [{"role": "user", "content": "task"}]
    ai_agent.hooks_after_init_prompt = []
    ai_agent.hooks_after_new_session = []
    ai_agent.hooks_pre_chat = []

    ctx_runtime_data = Mock()
    ctx_runtime_data.messages = [{"role": "user", "content": "task"}]
    ctx_runtime_data._classify_context_watermark.side_effect = classifications
    ctx_runtime_data.is_need_summarize_for_processed.return_value = False
    ctx_runtime_data.is_need_summarize_for_processing.return_value = False
    ctx_runtime_data.summarize_messages_for_processed.return_value = "session-summary"
    ctx_runtime_data.summarize_messages_for_processing.return_value = processing_answer

    ctx_rt_aiagent = Mock()
    ctx_rt_aiagent.ai_agent = ai_agent
    ctx_rt_aiagent.ctx_runtime_data = ctx_runtime_data

    with (
        patch(
            "topsailai.workspace.agent.hooks.base.init.get_hooks",
            return_value=[],
        ),
        patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent"),
        patch("topsailai.workspace.agent.agent_chat_base.env_tool") as env_tool,
    ):
        env_tool.EnvReaderInstance.get.return_value = None
        env_tool.EnvReaderInstance.check_bool.return_value = False
        agent_chat = AgentChatBase(
            hook_instruction=Mock(),
            ctx_rt_aiagent=ctx_rt_aiagent,
            ctx_rt_instruction=Mock(),
        )
        agent_chat.heavy_task.threshold_continuous_summary_times = 5

    return agent_chat, ctx_runtime_data, ai_agent


def test_low_runs_ordinary_summarization_at_current_checkpoint():
    """LOW immediately summarizes both layers without forced mode."""
    agent_chat, runtime, ai_agent = _build_agent_chat(
        [_watermark(CONTEXT_WATERMARK_LOW, 600), _watermark(CONTEXT_WATERMARK_NORMAL, 300)]
    )

    ai_agent.hooks_pre_chat[0](ai_agent)

    runtime.summarize_messages_for_processed.assert_called_once_with(force=False)
    runtime.summarize_messages_for_processing.assert_called_once_with(force=False)
    assert runtime._classify_context_watermark.call_count == 2


def test_high_runs_forced_summarization_and_bypasses_disabled_legacy_thresholds():
    """HIGH forces summarization even when both legacy triggers are disabled."""
    agent_chat, runtime, ai_agent = _build_agent_chat(
        [_watermark(CONTEXT_WATERMARK_HIGH, 760), _watermark(CONTEXT_WATERMARK_LOW, 600)]
    )

    ai_agent.hooks_pre_chat[0](ai_agent)

    runtime.is_need_summarize_for_processed.assert_called_once_with()
    runtime.is_need_summarize_for_processing.assert_called_once_with()
    runtime.summarize_messages_for_processed.assert_called_once_with(force=True)
    runtime.summarize_messages_for_processing.assert_called_once_with(force=True)


def test_hard_forces_compression_and_allows_request_after_recovery():
    """HARD permits continuation only after reclassification leaves HARD."""
    agent_chat, runtime, ai_agent = _build_agent_chat(
        [_watermark(CONTEXT_WATERMARK_HARD, 920), _watermark(CONTEXT_WATERMARK_HIGH, 750)]
    )

    ai_agent.hooks_pre_chat[0](ai_agent)

    runtime.summarize_messages_for_processed.assert_called_once_with(force=True)
    runtime.summarize_messages_for_processing.assert_called_once_with(force=True)


def test_hard_raises_when_forced_compression_cannot_recover():
    """An ordinary LLM request is blocked while the context remains HARD."""
    from topsailai.ai_base.exception import ContextWindowLimitError

    agent_chat, runtime, ai_agent = _build_agent_chat(
        [_watermark(CONTEXT_WATERMARK_HARD, 920), _watermark(CONTEXT_WATERMARK_HARD, 910)]
    )

    with pytest.raises(ContextWindowLimitError, match="send_limit=900"):
        ai_agent.hooks_pre_chat[0](ai_agent)


def test_hard_priority_is_not_short_circuited_by_lower_watermarks():
    """The single classification result drives HARD rather than LOW/HIGH branches."""
    from topsailai.ai_base.exception import ContextWindowLimitError

    agent_chat, runtime, ai_agent = _build_agent_chat(
        [_watermark(CONTEXT_WATERMARK_HARD, 950), _watermark(CONTEXT_WATERMARK_HARD, 940)]
    )

    with pytest.raises(ContextWindowLimitError):
        ai_agent.hooks_pre_chat[0](ai_agent)

    runtime.summarize_messages_for_processing.assert_called_once_with(force=True)


def test_single_large_message_can_jump_directly_to_high():
    """HIGH does not require a prior LOW checkpoint."""
    agent_chat, runtime, ai_agent = _build_agent_chat(
        [_watermark(CONTEXT_WATERMARK_HIGH, 780), _watermark(CONTEXT_WATERMARK_NORMAL, 400)]
    )

    ai_agent.hooks_pre_chat[0](ai_agent)

    runtime.summarize_messages_for_processing.assert_called_once_with(force=True)


def test_runtime_model_switch_and_max_tokens_changes_are_reclassified_each_checkpoint():
    """Each hook invocation asks the runtime to resolve the active model boundaries again."""
    agent_chat, runtime, ai_agent = _build_agent_chat(
        [
            _watermark(CONTEXT_WATERMARK_NORMAL, 400),
            _watermark(CONTEXT_WATERMARK_HIGH, 780),
            _watermark(CONTEXT_WATERMARK_NORMAL, 400),
        ]
    )
    hook = ai_agent.hooks_pre_chat[0]

    hook(ai_agent)
    runtime.summarize_messages_for_processing.assert_not_called()

    hook(ai_agent)
    runtime.summarize_messages_for_processing.assert_called_once_with(force=True)
    assert runtime._classify_context_watermark.call_count == 3


def test_missing_dynamic_configuration_preserves_fixed_threshold_behavior():
    """An inactive dynamic guard leaves the legacy trigger path unchanged."""
    agent_chat, runtime, ai_agent = _build_agent_chat([None])
    runtime.is_need_summarize_for_processing.return_value = True

    ai_agent.hooks_pre_chat[0](ai_agent)

    runtime.summarize_messages_for_processed.assert_not_called()
    runtime.summarize_messages_for_processing.assert_called_once_with()
    assert runtime._classify_context_watermark.call_count == 1
