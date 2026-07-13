"""
Unit tests for HeavyTask behavior in workspace/agent/agent_chat_base.py.

This module reproduces the msg_count infinite growth bug and verifies the fix:
block_heavy_task() must raise HeavyTaskError instead of asserting, and the
error must propagate so the agent loop terminates gracefully.
"""

import pytest
from unittest.mock import Mock, patch


class TestHeavyTaskBase:
    """Test cases for HeavyTaskBase class."""

    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    def test_block_heavy_task_raises_recoverable_error(self, mock_env_tool):
        """Before fix: block_heavy_task used assert, which could be disabled.
        After fix: it raises HeavyTaskError with the critical alert prompt."""
        from topsailai.workspace.agent.agent_chat_base import HeavyTaskBase, HeavyTaskError

        mock_env_tool.EnvReaderInstance.get.return_value = None

        ht = HeavyTaskBase()
        ht.threshold_continuous_summary_times = 5
        ht.continuous_summary_times = 12  # >= 5 + 7
        with pytest.raises(HeavyTaskError, match="CRITICAL SYSTEM ALERT"):
            ht.block_heavy_task()

    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    def test_block_heavy_task_does_not_raise_below_threshold(self, mock_env_tool):
        """block_heavy_task should be a no-op when below the threshold."""
        from topsailai.workspace.agent.agent_chat_base import HeavyTaskBase, HeavyTaskError

        mock_env_tool.EnvReaderInstance.get.return_value = None

        ht = HeavyTaskBase()
        ht.threshold_continuous_summary_times = 5
        ht.continuous_summary_times = 10  # < 5 + 7
        # Should not raise
        ht.block_heavy_task()


class TestHookSummarizeMessagesHeavyTask:
    """Test cases for hook_summarize_messages heavy task behavior."""

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    def test_hook_summarize_messages_raises_heavy_task_error_and_skips_summarize(
        self, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Before fix: AssertionError was swallowed, summarize never ran.
        After fix: HeavyTaskError is raised and propagates."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase, HeavyTaskError

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None
        mock_env_tool.EnvReaderInstance.check_bool.return_value = False

        hook_instruction = Mock()
        ctx_rt_instruction = Mock()

        ai_agent = Mock()
        ai_agent.messages = [{"role": "user", "content": f"msg-{i}"} for i in range(75)]
        ai_agent.hooks_after_init_prompt = []
        ai_agent.hooks_after_new_session = []
        ai_agent.hooks_pre_chat = []

        ctx_runtime_data = Mock()
        ctx_runtime_data.messages = []
        ctx_runtime_data.is_need_summarize_for_processed.return_value = False
        ctx_runtime_data.is_need_summarize_for_processing.return_value = True
        ctx_runtime_data.summarize_messages_for_processing.return_value = "summary"

        ctx_rt_aiagent = Mock()
        ctx_rt_aiagent.ai_agent = ai_agent
        ctx_rt_aiagent.ctx_runtime_data = ctx_runtime_data

        agent_chat = AgentChatBase(
            hook_instruction=hook_instruction,
            ctx_rt_aiagent=ctx_rt_aiagent,
            ctx_rt_instruction=ctx_rt_instruction,
        )
        agent_chat.heavy_task.threshold_continuous_summary_times = 5
        agent_chat.heavy_task.continuous_summary_times = 12

        hook_summarize_messages = agent_chat.ai_agent.hooks_pre_chat[0]

        with pytest.raises(HeavyTaskError, match="CRITICAL SYSTEM ALERT"):
            hook_summarize_messages(ai_agent)

        # Summarize should NOT have been called because block_heavy_task raised first
        ctx_runtime_data.summarize_messages_for_processing.assert_not_called()

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    def test_hook_summarize_messages_runs_summarize_when_not_heavy(
        self, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """When below the heavy task threshold, summarization should run normally."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None
        mock_env_tool.EnvReaderInstance.check_bool.return_value = False

        hook_instruction = Mock()
        ctx_rt_instruction = Mock()

        ai_agent = Mock()
        ai_agent.messages = [{"role": "user", "content": f"msg-{i}"} for i in range(75)]
        ai_agent.hooks_after_init_prompt = []
        ai_agent.hooks_after_new_session = []
        ai_agent.hooks_pre_chat = []

        ctx_runtime_data = Mock()
        ctx_runtime_data.messages = []
        ctx_runtime_data.is_need_summarize_for_processed.return_value = False
        ctx_runtime_data.is_need_summarize_for_processing.return_value = True
        ctx_runtime_data.summarize_messages_for_processing.return_value = "summary"

        ctx_rt_aiagent = Mock()
        ctx_rt_aiagent.ai_agent = ai_agent
        ctx_rt_aiagent.ctx_runtime_data = ctx_runtime_data

        agent_chat = AgentChatBase(
            hook_instruction=hook_instruction,
            ctx_rt_aiagent=ctx_rt_aiagent,
            ctx_rt_instruction=ctx_rt_instruction,
        )
        agent_chat.heavy_task.threshold_continuous_summary_times = 5
        agent_chat.heavy_task.continuous_summary_times = 0

        hook_summarize_messages = agent_chat.ai_agent.hooks_pre_chat[0]

        hook_summarize_messages(ai_agent)

        ctx_runtime_data.summarize_messages_for_processing.assert_called_once()
