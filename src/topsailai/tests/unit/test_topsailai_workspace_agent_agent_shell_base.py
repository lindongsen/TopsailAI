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
        mock_get_hooks.side_effect = [[mock_pre_run_hook], []]
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


if __name__ == "__main__":
    unittest.main()
