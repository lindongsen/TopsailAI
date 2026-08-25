"""
Unit tests for workspace/agent/agent_shell_base.py module.

This module contains unit tests for the AgentChat class which
handles the main conversation loop between human and AI agent.
"""

import os
import unittest
from unittest.mock import MagicMock, patch, PropertyMock


class TestAgentChatRun(unittest.TestCase):
    """Test cases for AgentChat.run method."""

    def setUp(self):
        """Set up test fixtures."""
        self.hook_instruction = MagicMock()
        self.ctx_rt_aiagent = MagicMock()
        self.ctx_rt_instruction = MagicMock()
        self.mock_ai_agent = MagicMock()
        self.ctx_rt_aiagent.ai_agent = self.mock_ai_agent
        self.ctx_rt_aiagent.ctx_runtime_data = MagicMock()

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.lock_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.task_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.get_agent_step_call")
    def test_run_with_initial_message(
        self, mock_get_agent_step_call, mock_task_tool, mock_lock_tool,
        mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test AgentChat.run with an initial message provided."""
        from topsailai.workspace.agent.agent_shell_base import AgentChat

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = lambda key, default: {
            "TOPSAILAI_INTERACTIVE_MODE": False,
            "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER": False,
            "TOPSAILAI_ENABLE_SESSION_LOCK": False,
        }.get(key, default)
        mock_env_tool.is_interactive_mode.return_value = False
        mock_env_tool.is_debug_mode.return_value = False

        mock_lock_tool.ctxm_void.return_value.__enter__ = MagicMock(return_value={})
        mock_lock_tool.ctxm_void.return_value.__exit__ = MagicMock(return_value=False)

        self.mock_ai_agent.run.return_value = "Test response"

        agent_chat = AgentChat(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        result = agent_chat.run(message="Hello", times=1)

        self.assertEqual(result, "Test response")
        self.mock_ai_agent.run.assert_called_once()

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.tool_stat")
    @patch("topsailai.workspace.agent.agent_shell_base.lock_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.task_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.get_agent_step_call")
    def test_run_preassigns_executor_before_manifest(self,
            mock_get_agent_step_call, mock_task_tool, mock_lock_tool,
            mock_tool_stat, mock_env_tool, mock_set_ai_agent, mock_get_hooks):
        """Verify executor is assigned before run() so pre-run manifests carry it."""
        from topsailai.workspace.agent.agent_shell_base import AgentChat

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = lambda key, default: {
            "TOPSAILAI_INTERACTIVE_MODE": False,
            "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER": False,
            "TOPSAILAI_ENABLE_SESSION_LOCK": False,
        }.get(key, default)
        mock_env_tool.is_interactive_mode.return_value = False
        mock_env_tool.is_debug_mode.return_value = False
        mock_lock_tool.ctxm_void.return_value.__enter__ = MagicMock(return_value={})
        mock_lock_tool.ctxm_void.return_value.__exit__ = MagicMock(return_value=False)

        mock_task = mock_task_tool.TaskUtil.return_value
        mock_task.manifest = "---\nstatus: initializing\nexecutor: \n---\n"
        mock_task_tool.ctxm_process_task.return_value.__enter__ = MagicMock(return_value=None)
        mock_task_tool.ctxm_process_task.return_value.__exit__ = MagicMock(return_value=False)
        self.mock_ai_agent.agent_name = "pre-agent"

        captured = {}
        def _fake_run(_step, msg):
            # At this moment run() has NOT executed yet -> executor must already be set
            captured["executor_at_run_time"] = mock_task.executor
            captured["msg_prefix"] = msg[:40]
            return "response"
        self.mock_ai_agent.run.side_effect = _fake_run

        agent_chat = AgentChat(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )
        agent_chat.run(message="Hi", times=1, task_id="t1")

        self.assertEqual(captured["executor_at_run_time"], "pre-agent")
        self.assertTrue(captured["msg_prefix"].startswith("---"))
        self.assertEqual(mock_task.executor, "pre-agent")

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.tool_stat")
    @patch("topsailai.workspace.agent.agent_shell_base.lock_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.task_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.get_agent_step_call")
    def test_run_sets_task_tool_call_count(
        self, mock_get_agent_step_call, mock_task_tool, mock_lock_tool,
        mock_tool_stat, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test task completion records the agent tool call count."""
        from topsailai.workspace.agent.agent_shell_base import AgentChat

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = lambda key, default: {
            "TOPSAILAI_INTERACTIVE_MODE": False,
            "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER": False,
            "TOPSAILAI_ENABLE_SESSION_LOCK": False,
            "TOPSAILAI_ENABLE_TOOL_STAT": True,
        }.get(key, default)
        mock_env_tool.is_interactive_mode.return_value = False
        mock_env_tool.is_debug_mode.return_value = False
        mock_lock_tool.ctxm_void.return_value.__enter__ = MagicMock(return_value={})
        mock_lock_tool.ctxm_void.return_value.__exit__ = MagicMock(return_value=False)
        mock_task = mock_task_tool.TaskUtil.return_value
        mock_task.manifest = "---\nstatus: done\n---\n"
        mock_task_tool.ctxm_process_task.return_value.__enter__ = MagicMock(return_value=None)
        mock_task_tool.ctxm_process_task.return_value.__exit__ = MagicMock(return_value=False)
        mock_tool_stat.get_agent_tool_stat.return_value.total_calls = 5
        self.mock_ai_agent.run.return_value = "Test response"
        self.mock_ai_agent.agent_name = "test-agent"

        agent_chat = AgentChat(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        agent_chat.run(message="Hello", times=1, task_id="task-id")

        self.assertEqual(mock_task.tool_call_count, 5)
        self.assertEqual(mock_task.executor, "test-agent")
        mock_tool_stat.get_agent_tool_stat.assert_called_once_with(self.mock_ai_agent)

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.tool_stat")
    @patch("topsailai.workspace.agent.agent_shell_base.lock_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.task_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.get_agent_step_call")
    def test_run_lazy_warning_when_tool_stat_enabled_and_zero_calls(
        self, mock_get_agent_step_call, mock_task_tool, mock_lock_tool,
        mock_tool_stat, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """When tool-stat is enabled and no tool calls were made, append the warning."""
        from topsailai.workspace.agent.agent_shell_base import (
            AgentChat,
            LAZY_EXECUTION_WARNING,
        )

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = lambda key, default: {
            "TOPSAILAI_INTERACTIVE_MODE": False,
            "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER": False,
            "TOPSAILAI_ENABLE_SESSION_LOCK": False,
            "TOPSAILAI_ENABLE_TOOL_STAT": True,
        }.get(key, default)
        mock_env_tool.is_interactive_mode.return_value = False
        mock_env_tool.is_debug_mode.return_value = False
        mock_lock_tool.ctxm_void.return_value.__enter__ = MagicMock(return_value={})
        mock_lock_tool.ctxm_void.return_value.__exit__ = MagicMock(return_value=False)
        mock_task = mock_task_tool.TaskUtil.return_value
        mock_task.manifest = "---\nstatus: done\n---\n"
        mock_task.tool_call_count = 0
        mock_task_tool.ctxm_process_task.return_value.__enter__ = MagicMock(return_value=None)
        mock_task_tool.ctxm_process_task.return_value.__exit__ = MagicMock(return_value=False)
        mock_tool_stat.get_agent_tool_stat.return_value.total_calls = 0
        self.mock_ai_agent.run.return_value = "Test response"

        agent_chat = AgentChat(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        result = agent_chat.run(message="Hello", times=1, task_id="task-id")

        self.assertIn(LAZY_EXECUTION_WARNING, result)
        self.assertIn("!!! CRITICAL SYSTEM WARNING !!!", result)

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.tool_stat")
    @patch("topsailai.workspace.agent.agent_shell_base.lock_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.task_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.get_agent_step_call")
    def test_run_no_lazy_warning_when_tool_calls_present(
        self, mock_get_agent_step_call, mock_task_tool, mock_lock_tool,
        mock_tool_stat, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """When tool-stat is enabled and tool calls were made, do not append the warning."""
        from topsailai.workspace.agent.agent_shell_base import (
            AgentChat,
            LAZY_EXECUTION_WARNING,
        )

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = lambda key, default: {
            "TOPSAILAI_INTERACTIVE_MODE": False,
            "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER": False,
            "TOPSAILAI_ENABLE_SESSION_LOCK": False,
            "TOPSAILAI_ENABLE_TOOL_STAT": True,
        }.get(key, default)
        mock_env_tool.is_interactive_mode.return_value = False
        mock_env_tool.is_debug_mode.return_value = False
        mock_lock_tool.ctxm_void.return_value.__enter__ = MagicMock(return_value={})
        mock_lock_tool.ctxm_void.return_value.__exit__ = MagicMock(return_value=False)
        mock_task = mock_task_tool.TaskUtil.return_value
        mock_task.manifest = "---\nstatus: done\n---\n"
        mock_task.tool_call_count = 3
        mock_task_tool.ctxm_process_task.return_value.__enter__ = MagicMock(return_value=None)
        mock_task_tool.ctxm_process_task.return_value.__exit__ = MagicMock(return_value=False)
        mock_tool_stat.get_agent_tool_stat.return_value.total_calls = 3
        self.mock_ai_agent.run.return_value = "Test response"

        agent_chat = AgentChat(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        result = agent_chat.run(message="Hello", times=1, task_id="task-id")

        self.assertNotIn(LAZY_EXECUTION_WARNING, result)

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.tool_stat")
    @patch("topsailai.workspace.agent.agent_shell_base.lock_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.task_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.get_agent_step_call")
    def test_run_no_lazy_warning_when_tool_stat_disabled(
        self, mock_get_agent_step_call, mock_task_tool, mock_lock_tool,
        mock_tool_stat, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """When tool-stat is disabled, do not append the warning even with zero calls."""
        from topsailai.workspace.agent.agent_shell_base import (
            AgentChat,
            LAZY_EXECUTION_WARNING,
        )

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = lambda key, default: {
            "TOPSAILAI_INTERACTIVE_MODE": False,
            "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER": False,
            "TOPSAILAI_ENABLE_SESSION_LOCK": False,
            "TOPSAILAI_ENABLE_TOOL_STAT": False,
        }.get(key, default)
        mock_env_tool.is_interactive_mode.return_value = False
        mock_env_tool.is_debug_mode.return_value = False
        mock_lock_tool.ctxm_void.return_value.__enter__ = MagicMock(return_value={})
        mock_lock_tool.ctxm_void.return_value.__exit__ = MagicMock(return_value=False)
        mock_task = mock_task_tool.TaskUtil.return_value
        mock_task.manifest = "---\nstatus: done\n---\n"
        mock_task.tool_call_count = 0
        mock_task_tool.ctxm_process_task.return_value.__enter__ = MagicMock(return_value=None)
        mock_task_tool.ctxm_process_task.return_value.__exit__ = MagicMock(return_value=False)
        self.mock_ai_agent.run.return_value = "Test response"

        agent_chat = AgentChat(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        result = agent_chat.run(message="Hello", times=1, task_id="task-id")

        self.assertNotIn(LAZY_EXECUTION_WARNING, result)
    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.lock_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.task_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.get_agent_step_call")
    def test_run_with_times_limit(
        self, mock_get_agent_step_call, mock_task_tool, mock_lock_tool,
        mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test AgentChat.run respects times parameter."""
        from topsailai.workspace.agent.agent_shell_base import AgentChat

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = lambda key, default: {
            "TOPSAILAI_INTERACTIVE_MODE": False,
            "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER": False,
            "TOPSAILAI_ENABLE_SESSION_LOCK": False,
        }.get(key, default)
        mock_env_tool.is_interactive_mode.return_value = False
        mock_env_tool.is_debug_mode.return_value = False

        mock_lock_tool.ctxm_void.return_value.__enter__ = MagicMock(return_value={})
        mock_lock_tool.ctxm_void.return_value.__exit__ = MagicMock(return_value=False)

        self.mock_ai_agent.run.return_value = "Response"

        agent_chat = AgentChat(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        result = agent_chat.run(message="Test", times=1)

        # Should only call run once due to times=1
        self.assertEqual(self.mock_ai_agent.run.call_count, 1)

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.lock_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.task_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.get_agent_step_call")
    def test_run_with_only_save_final(
        self, mock_get_agent_step_call, mock_task_tool, mock_lock_tool,
        mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test AgentChat.run with only_save_final=True."""
        from topsailai.workspace.agent.agent_shell_base import AgentChat

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = lambda key, default: {
            "TOPSAILAI_INTERACTIVE_MODE": False,
            "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER": False,
            "TOPSAILAI_ENABLE_SESSION_LOCK": False,
        }.get(key, default)
        mock_env_tool.is_interactive_mode.return_value = False
        mock_env_tool.is_debug_mode.return_value = False

        mock_lock_tool.ctxm_void.return_value.__enter__ = MagicMock(return_value={})
        mock_lock_tool.ctxm_void.return_value.__exit__ = MagicMock(return_value=False)

        self.mock_ai_agent.run.return_value = "Final answer"

        agent_chat = AgentChat(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        result = agent_chat.run(message="Hello", times=1, only_save_final=True)

        # Should add session message with assistant role
        self.ctx_rt_aiagent.ctx_runtime_data.add_session_message.assert_called()

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.lock_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.task_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.get_agent_step_call")
    def test_run_with_session_lock_enabled(
        self, mock_get_agent_step_call, mock_task_tool, mock_lock_tool,
        mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test AgentChat.run with session lock enabled."""
        from topsailai.workspace.agent.agent_shell_base import AgentChat

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = lambda key, default: {
            "TOPSAILAI_INTERACTIVE_MODE": False,
            "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER": False,
            "TOPSAILAI_ENABLE_SESSION_LOCK": True,
        }.get(key, default)
        mock_env_tool.is_interactive_mode.return_value = False
        mock_env_tool.is_debug_mode.return_value = False

        mock_context_manager = MagicMock()
        mock_context_manager.__enter__ = MagicMock(return_value={"session_id": "123", "fp": True})
        mock_context_manager.__exit__ = MagicMock(return_value=False)
        mock_lock_tool.ctxm_try_session_lock.return_value = mock_context_manager

        self.mock_ai_agent.run.return_value = "Response"

        agent_chat = AgentChat(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        result = agent_chat.run(message="Hello", times=1, need_session_lock=True)

        # Should use session lock context manager
        mock_lock_tool.ctxm_try_session_lock.assert_called()

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.lock_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.task_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.get_agent_step_call")
    def test_run_with_func_build_message(
        self, mock_get_agent_step_call, mock_task_tool, mock_lock_tool,
        mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test AgentChat.run with func_build_message callback."""
        from topsailai.workspace.agent.agent_shell_base import AgentChat

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = lambda key, default: {
            "TOPSAILAI_INTERACTIVE_MODE": False,
            "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER": False,
            "TOPSAILAI_ENABLE_SESSION_LOCK": False,
        }.get(key, default)
        mock_env_tool.is_interactive_mode.return_value = False
        mock_env_tool.is_debug_mode.return_value = False

        mock_lock_tool.ctxm_void.return_value.__enter__ = MagicMock(return_value={})
        mock_lock_tool.ctxm_void.return_value.__exit__ = MagicMock(return_value=False)

        self.mock_ai_agent.run.return_value = "Response"

        func_build_message = MagicMock(return_value="Modified message")

        agent_chat = AgentChat(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        result = agent_chat.run(message="Original", times=1, func_build_message=func_build_message)

        func_build_message.assert_called_once()
        self.mock_ai_agent.run.assert_called_once()

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.lock_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.task_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.get_agent_step_call")
    def test_run_with_agent_end_process_exception(
        self, mock_get_agent_step_call, mock_task_tool, mock_lock_tool,
        mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test AgentChat.run handles AgentEndProcess exception."""
        from topsailai.workspace.agent.agent_shell_base import AgentChat
        from topsailai.ai_base.agent_types import exception as agent_exception

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = lambda key, default: {
            "TOPSAILAI_INTERACTIVE_MODE": False,
            "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER": False,
            "TOPSAILAI_ENABLE_SESSION_LOCK": False,
        }.get(key, default)
        mock_env_tool.is_interactive_mode.return_value = False
        mock_env_tool.is_debug_mode.return_value = False

        mock_lock_tool.ctxm_void.return_value.__enter__ = MagicMock(return_value={})
        mock_lock_tool.ctxm_void.return_value.__exit__ = MagicMock(return_value=False)

        self.mock_ai_agent.run.side_effect = agent_exception.AgentEndProcess()
        self.mock_ai_agent.messages = [{"role": "assistant", "content": "Last message"}]

        agent_chat = AgentChat(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        result = agent_chat.run(message="Hello", times=1)

        # Should handle exception gracefully
        self.assertEqual(agent_chat.last_message, {"role": "assistant", "content": "Last message"})

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.lock_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.task_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.get_agent_step_call")
    def test_run_with_context_window_limit_exception(
        self, mock_get_agent_step_call, mock_task_tool, mock_lock_tool,
        mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test an unrecoverable context limit terminates the turn gracefully."""
        from topsailai.ai_base.exception import ContextWindowLimitError
        from topsailai.workspace.agent.agent_shell_base import AgentChat

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = lambda key, default: {
            "TOPSAILAI_INTERACTIVE_MODE": False,
            "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER": False,
            "TOPSAILAI_ENABLE_SESSION_LOCK": False,
        }.get(key, default)
        mock_env_tool.is_interactive_mode.return_value = False
        mock_env_tool.is_debug_mode.return_value = False
        mock_lock_tool.ctxm_void.return_value.__enter__ = MagicMock(return_value={})
        mock_lock_tool.ctxm_void.return_value.__exit__ = MagicMock(return_value=False)
        self.mock_ai_agent.run.side_effect = ContextWindowLimitError(
            "context remains above model send limit"
        )

        agent_chat = AgentChat(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        result = agent_chat.run(message="Hello", times=1)

        expected = "Task terminated: context remains above model send limit"
        self.assertEqual(result, expected)
        self.assertEqual(agent_chat.last_message, expected)

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.lock_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.task_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.get_agent_step_call")
    def test_run_with_keyboard_interrupt(
        self, mock_get_agent_step_call, mock_task_tool, mock_lock_tool,
        mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test AgentChat.run handles KeyboardInterrupt."""
        from topsailai.workspace.agent.agent_shell_base import AgentChat

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = lambda key, default: {
            "TOPSAILAI_INTERACTIVE_MODE": False,
            "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER": False,
            "TOPSAILAI_ENABLE_SESSION_LOCK": False,
        }.get(key, default)
        mock_env_tool.is_interactive_mode.return_value = False
        mock_env_tool.is_debug_mode.return_value = False

        mock_lock_tool.ctxm_void.return_value.__enter__ = MagicMock(return_value={})
        mock_lock_tool.ctxm_void.return_value.__exit__ = MagicMock(return_value=False)

        self.mock_ai_agent.run.side_effect = KeyboardInterrupt()

        agent_chat = AgentChat(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        result = agent_chat.run(message="Hello", times=1, need_confirm_abort=False)

        self.assertEqual(result, "failed due to abort by Human")

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.print_warning")
    @patch("topsailai.workspace.agent.agent_shell_base.input_message", return_value="resume")
    @patch("topsailai.workspace.agent.agent_shell_base.lock_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.task_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.get_agent_step_call")
    def test_run_hard_interrupt_prints_warning(
        self, mock_get_agent_step_call, mock_task_tool, mock_lock_tool,
        mock_input_message, mock_print_warning, mock_env_tool,
        mock_set_ai_agent, mock_get_hooks,
    ):
        """Hard interrupts emit a warning from the AgentChat execution thread."""
        from topsailai.ai_base.exception import HardInterruptError
        from topsailai.workspace.agent.agent_shell_base import AgentChat

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = lambda key, default: {
            "TOPSAILAI_INTERACTIVE_MODE": False,
            "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER": False,
            "TOPSAILAI_ENABLE_SESSION_LOCK": False,
        }.get(key, default)
        mock_env_tool.is_interactive_mode.return_value = False
        mock_env_tool.is_debug_mode.return_value = False
        mock_lock_tool.ctxm_void.return_value.__enter__ = MagicMock(return_value={})
        mock_lock_tool.ctxm_void.return_value.__exit__ = MagicMock(return_value=False)
        self.mock_ai_agent.run.side_effect = [
            HardInterruptError("Hard interrupt requested via control channel"),
            "resumed response",
        ]

        agent_chat = AgentChat(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        result = agent_chat.run(message="Hello", times=2)

        self.assertEqual(result, "resumed response")
        mock_input_message.assert_called_once()
        mock_print_warning.assert_called_once_with(
            "Hard interrupt requested: Hard interrupt requested via control channel"
        )

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.lock_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.task_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.get_agent_step_call")
    def test_run_with_empty_answer(
        self, mock_get_agent_step_call, mock_task_tool, mock_lock_tool,
        mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test AgentChat.run handles empty answer from agent."""
        from topsailai.workspace.agent.agent_shell_base import AgentChat

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = lambda key, default: {
            "TOPSAILAI_INTERACTIVE_MODE": False,
            "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER": False,
            "TOPSAILAI_ENABLE_SESSION_LOCK": False,
        }.get(key, default)
        mock_env_tool.is_interactive_mode.return_value = False
        mock_env_tool.is_debug_mode.return_value = False

        mock_lock_tool.ctxm_void.return_value.__enter__ = MagicMock(return_value={})
        mock_lock_tool.ctxm_void.return_value.__exit__ = MagicMock(return_value=False)

        self.mock_ai_agent.run.return_value = ""

        agent_chat = AgentChat(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        result = agent_chat.run(message="Hello", times=1)

        # Should return empty string
        self.assertEqual(result, "")

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.lock_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.task_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.get_agent_step_call")
    def test_run_calls_hooks_pre_run(
        self, mock_get_agent_step_call, mock_task_tool, mock_lock_tool,
        mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test AgentChat.run calls pre-run hooks."""
        from topsailai.workspace.agent.agent_shell_base import AgentChat

        mock_pre_run_hook = MagicMock()
        mock_get_hooks.side_effect = [[mock_pre_run_hook], [], [], []]
        mock_env_tool.EnvReaderInstance.get.return_value = None
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = lambda key, default: {
            "TOPSAILAI_INTERACTIVE_MODE": False,
            "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER": False,
            "TOPSAILAI_ENABLE_SESSION_LOCK": False,
        }.get(key, default)
        mock_env_tool.is_interactive_mode.return_value = False
        mock_env_tool.is_debug_mode.return_value = False

        mock_lock_tool.ctxm_void.return_value.__enter__ = MagicMock(return_value={})
        mock_lock_tool.ctxm_void.return_value.__exit__ = MagicMock(return_value=False)

        self.mock_ai_agent.run.return_value = "Response"

        agent_chat = AgentChat(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        result = agent_chat.run(message="Hello", times=1)

        # Pre-run hook should be called
        mock_pre_run_hook.assert_called()


class TestAgentChatRunEdgeCases(unittest.TestCase):
    """Test cases for AgentChat.run edge cases."""

    def setUp(self):
        """Set up test fixtures."""
        self.hook_instruction = MagicMock()
        self.ctx_rt_aiagent = MagicMock()
        self.ctx_rt_instruction = MagicMock()
        self.mock_ai_agent = MagicMock()
        self.ctx_rt_aiagent.ai_agent = self.mock_ai_agent
        self.ctx_rt_aiagent.ctx_runtime_data = MagicMock()

    def test_agent_chat_attributes(self):
        """Test AgentChat class has expected attributes."""
        from topsailai.workspace.agent.agent_shell_base import AgentChat

        # Verify AgentChat has expected attributes
        self.assertTrue(hasattr(AgentChat, 'run'))
        self.assertTrue(callable(getattr(AgentChat, 'run')))


class TestGetSessionTokenTotals(unittest.TestCase):
    """Test cases for _get_session_token_totals helper."""

    @patch("topsailai.context.ctx_manager.get_session_manager")
    def test_get_session_token_totals_from_session_storage(self, mock_get_session_manager):
        """When session_id is set and storage has totals, return DB values."""
        from topsailai.workspace.agent.agent_shell_base import _get_session_token_totals

        mock_storage = MagicMock()
        mock_storage.get_session_token_totals.return_value = (1234, 567)
        mock_get_session_manager.return_value = mock_storage

        mock_ai_agent = MagicMock()

        result = _get_session_token_totals("session-001", mock_ai_agent)

        self.assertEqual(result, (1234, 567))
        mock_storage.get_session_token_totals.assert_called_once_with("session-001")

    @patch("topsailai.context.ctx_manager.get_session_manager")
    def test_get_session_token_totals_missing_session_falls_back(self, mock_get_session_manager):
        """When session_id is set but storage returns None, fall back to TokenStat."""
        from topsailai.workspace.agent.agent_shell_base import _get_session_token_totals

        mock_storage = MagicMock()
        mock_storage.get_session_token_totals.return_value = None
        mock_get_session_manager.return_value = mock_storage

        mock_token_stat = MagicMock()
        mock_token_stat.total_tokens = 42
        mock_token_stat.total_cached_tokens = 7
        mock_ai_agent = MagicMock()
        mock_ai_agent.llm_model.tokenStat = mock_token_stat

        result = _get_session_token_totals("session-001", mock_ai_agent)

        self.assertEqual(result, (42, 7))

    def test_get_session_token_totals_no_session_id_falls_back(self):
        """When session_id is empty, fall back to TokenStat."""
        from topsailai.workspace.agent.agent_shell_base import _get_session_token_totals

        mock_token_stat = MagicMock()
        mock_token_stat.total_tokens = 99
        mock_token_stat.total_cached_tokens = 11
        mock_ai_agent = MagicMock()
        mock_ai_agent.llm_model.tokenStat = mock_token_stat

        result = _get_session_token_totals("", mock_ai_agent)

        self.assertEqual(result, (99, 11))

    def test_get_session_token_totals_no_token_stat_defaults_to_zero(self):
        """When no session and no TokenStat values are available, return zeros."""
        from topsailai.workspace.agent.agent_shell_base import _get_session_token_totals

        mock_ai_agent = MagicMock()
        mock_ai_agent.llm_model.tokenStat = MagicMock()
        del mock_ai_agent.llm_model.tokenStat.total_tokens
        del mock_ai_agent.llm_model.tokenStat.total_cached_tokens

        result = _get_session_token_totals("", mock_ai_agent)

        self.assertEqual(result, (0, 0))

    @patch("topsailai.context.ctx_manager.get_session_manager")
    def test_get_session_token_totals_storage_exception_falls_back(self, mock_get_session_manager):
        """When storage read raises, fall back to TokenStat."""
        from topsailai.workspace.agent.agent_shell_base import _get_session_token_totals

        mock_get_session_manager.side_effect = RuntimeError("db down")

        mock_token_stat = MagicMock()
        mock_token_stat.total_tokens = 55
        mock_token_stat.total_cached_tokens = 22
        mock_ai_agent = MagicMock()
        mock_ai_agent.llm_model.tokenStat = mock_token_stat

        result = _get_session_token_totals("session-001", mock_ai_agent)

        self.assertEqual(result, (55, 22))



class TestCacheHitRate(unittest.TestCase):
    """Test cases for cache hit rate display in the per-turn summary."""

    def _make_agent_chat(self, mock_env_tool, mock_lock_tool, mock_get_hooks):
        from topsailai.workspace.agent.agent_shell_base import AgentChat

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = lambda key, default: {
            "TOPSAILAI_INTERACTIVE_MODE": False,
            "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER": False,
            "TOPSAILAI_ENABLE_SESSION_LOCK": False,
        }.get(key, default)
        mock_env_tool.is_interactive_mode.return_value = False
        mock_env_tool.is_debug_mode.return_value = False
        mock_env_tool.is_need_print.return_value = True

        mock_lock_tool.ctxm_void.return_value.__enter__ = MagicMock(return_value={})
        mock_lock_tool.ctxm_void.return_value.__exit__ = MagicMock(return_value=False)

        hook_instruction = MagicMock()
        ctx_rt_aiagent = MagicMock()
        ctx_rt_instruction = MagicMock()
        mock_ai_agent = MagicMock()
        ctx_rt_aiagent.ai_agent = mock_ai_agent
        ctx_rt_aiagent.ctx_runtime_data = MagicMock()
        ctx_rt_aiagent.ctx_runtime_data.session_id = "session-001"

        return AgentChat(
            hook_instruction=hook_instruction,
            ctx_rt_aiagent=ctx_rt_aiagent,
            ctx_rt_instruction=ctx_rt_instruction,
        )

    @patch("topsailai.workspace.agent.agent_shell_base.input_message")
    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.lock_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.task_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.get_agent_step_call")
    @patch("topsailai.workspace.agent.agent_shell_base._get_session_token_totals")
    @patch("builtins.print")
    def test_cache_hit_rate_displayed(
        self, mock_print, mock_get_totals, mock_get_agent_step_call,
        mock_task_tool, mock_lock_tool, mock_env_tool, mock_set_ai_agent,
        mock_get_hooks, mock_input_message
    ):
        """Cache hit rate is printed with 3 decimal places after the first turn."""
        mock_get_totals.return_value = (1000, 250)
        mock_input_message.return_value = "continue"

        agent_chat = self._make_agent_chat(mock_env_tool, mock_lock_tool, mock_get_hooks)
        agent_chat.ai_agent.run.return_value = "Response"

        agent_chat.run(message="Hello", times=2)

        printed = "\n".join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
        self.assertIn("cache_hit_rate      : 25.000%", printed)

    @patch("topsailai.workspace.agent.agent_shell_base.input_message")
    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.lock_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.task_tool")
    @patch("topsailai.workspace.agent.agent_shell_base.get_agent_step_call")
    @patch("topsailai.workspace.agent.agent_shell_base._get_session_token_totals")
    @patch("builtins.print")
    def test_cache_hit_rate_zero_total_tokens(
        self, mock_print, mock_get_totals, mock_get_agent_step_call,
        mock_task_tool, mock_lock_tool, mock_env_tool, mock_set_ai_agent,
        mock_get_hooks, mock_input_message
    ):
        """Cache hit rate shows N/A when total_tokens is zero."""
        mock_get_totals.return_value = (0, 0)
        mock_input_message.return_value = "continue"

        agent_chat = self._make_agent_chat(mock_env_tool, mock_lock_tool, mock_get_hooks)
        agent_chat.ai_agent.run.return_value = "Response"

        agent_chat.run(message="Hello", times=2)

        printed = "\n".join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
        self.assertIn("cache_hit_rate      : N/A", printed)

class TestAgentChatControlServer(unittest.TestCase):
    """Test control channel server startup from AgentChat."""

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks", return_value=[])
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    def test_start_control_server_creates_session_socket(
        self, _mock_set_ai_agent, _mock_get_hooks
    ):
        """Starting the agent control server creates its resolved session socket."""
        import tempfile

        from topsailai.workspace.agent.agent_shell_base import AgentChat

        ctx_rt_aiagent = MagicMock()
        ctx_rt_aiagent.ai_agent = MagicMock()
        ctx_rt_aiagent.ctx_runtime_data = MagicMock()
        ctx_rt_aiagent.ctx_runtime_data.session_id = "control-session"
        agent_chat = AgentChat(
            hook_instruction=MagicMock(),
            ctx_rt_aiagent=ctx_rt_aiagent,
            ctx_rt_instruction=MagicMock(),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            socket_path = os.path.join(
                temporary_directory,
                "control-session.123.session.sock",
            )
            with patch(
                "topsailai.workspace.control_channel.server.resolve_socket_path",
                return_value=socket_path,
            ):
                agent_chat._start_control_server()

            try:
                self.assertIsNotNone(agent_chat.control_server)
                self.assertEqual(agent_chat.control_server.socket_path, socket_path)
                self.assertTrue(os.path.exists(socket_path))
            finally:
                agent_chat._stop_control_server()

            self.assertFalse(os.path.exists(socket_path))


if __name__ == "__main__":
    unittest.main()
