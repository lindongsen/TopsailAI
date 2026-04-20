"""
Unit tests for workspace/agent/agent_chat_base.py module.

This module contains unit tests for the AgentChatBase class which
coordinates the interaction between human users and AI agents.
"""

import os
import unittest
from unittest.mock import MagicMock, patch


class TestAgentChatBaseInit(unittest.TestCase):
    """Test cases for AgentChatBase class initialization."""

    def setUp(self):
        """Set up test fixtures."""
        self.hook_instruction = MagicMock()
        self.ctx_rt_aiagent = MagicMock()
        self.ctx_rt_instruction = MagicMock()
        self.session_head_tail_offset = 5

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    def test_init_with_default_offset(
        self, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test AgentChatBase initialization with default session_head_tail_offset."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        self.assertEqual(agent_chat.hook_instruction, self.hook_instruction)
        self.assertEqual(agent_chat.ctx_rt_aiagent, self.ctx_rt_aiagent)
        self.assertEqual(agent_chat.ctx_rt_instruction, self.ctx_rt_instruction)

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    def test_init_with_custom_offset(
        self, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test AgentChatBase initialization with custom session_head_tail_offset."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
            session_head_tail_offset=self.session_head_tail_offset,
        )

        self.assertEqual(agent_chat.session_head_tail_offset, self.session_head_tail_offset)

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    def test_init_with_none_offset_uses_default(
        self, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test that None session_head_tail_offset falls back to default."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase
        from topsailai.workspace.agent.agent_constants import DEFAULT_HEAD_TAIL_OFFSET

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
            session_head_tail_offset=None,
        )

        self.assertEqual(agent_chat.session_head_tail_offset, DEFAULT_HEAD_TAIL_OFFSET)

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    def test_init_sets_ai_agent(
        self, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test that ai_agent is set from ctx_rt_aiagent."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_ai_agent = MagicMock()
        self.ctx_rt_aiagent.ai_agent = mock_ai_agent

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        self.assertEqual(agent_chat.ai_agent, mock_ai_agent)
        mock_set_ai_agent.assert_called_once_with(mock_ai_agent)

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    def test_init_initializes_hooks(
        self, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test that pre_run and final_answer hooks are initialized."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_pre_run_hooks = [MagicMock(), MagicMock()]
        mock_post_hooks = [MagicMock()]
        mock_get_hooks.side_effect = [mock_pre_run_hooks, mock_post_hooks]
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        self.assertEqual(agent_chat.hooks_pre_run, mock_pre_run_hooks)
        self.assertEqual(agent_chat.hooks_for_final_answer, mock_post_hooks)


class TestAgentChatBaseProperties(unittest.TestCase):
    """Test cases for AgentChatBase properties."""

    def setUp(self):
        """Set up test fixtures."""
        self.hook_instruction = MagicMock()
        self.ctx_rt_aiagent = MagicMock()
        self.ctx_rt_instruction = MagicMock()

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    def test_agent_name_property(
        self, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test that agent_name property returns ai_agent's name."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_ai_agent = MagicMock()
        mock_ai_agent.agent_name = "test_agent"
        self.ctx_rt_aiagent.ai_agent = mock_ai_agent

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        self.assertEqual(agent_chat.agent_name, "test_agent")

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    def test_messages_property(
        self, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test that messages property returns ai_agent's messages."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_messages = [{"role": "user", "content": "hello"}]
        mock_ai_agent = MagicMock()
        mock_ai_agent.messages = mock_messages
        self.ctx_rt_aiagent.ai_agent = mock_ai_agent

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        self.assertEqual(agent_chat.messages, mock_messages)

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    def test_ctx_runtime_data_property(
        self, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test that ctx_runtime_data property returns ctx_rt_aiagent's data."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_ctx_runtime_data = MagicMock()
        self.ctx_rt_aiagent.ctx_runtime_data = mock_ctx_runtime_data

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        self.assertEqual(agent_chat.ctx_runtime_data, mock_ctx_runtime_data)


class TestAgentChatBaseCallHooksPreRun(unittest.TestCase):
    """Test cases for call_hooks_pre_run method."""

    def setUp(self):
        """Set up test fixtures."""
        self.hook_instruction = MagicMock()
        self.ctx_rt_aiagent = MagicMock()
        self.ctx_rt_instruction = MagicMock()

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_chat_base.logger")
    def test_call_hooks_pre_run_executes_all_hooks(
        self, mock_logger, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test that call_hooks_pre_run executes all registered hooks."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_hook1 = MagicMock()
        mock_hook2 = MagicMock()
        mock_get_hooks.return_value = [mock_hook1, mock_hook2]
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        agent_chat.call_hooks_pre_run()

        mock_hook1.assert_called_once_with(agent_chat)
        mock_hook2.assert_called_once_with(agent_chat)

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_chat_base.logger")
    def test_call_hooks_pre_run_handles_exception(
        self, mock_logger, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test that call_hooks_pre_run continues on hook exception."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_hook1 = MagicMock(side_effect=Exception("Hook error"))
        mock_hook2 = MagicMock()
        mock_get_hooks.return_value = [mock_hook1, mock_hook2]
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        # Should not raise exception
        agent_chat.call_hooks_pre_run()

        mock_hook1.assert_called_once_with(agent_chat)
        mock_hook2.assert_called_once_with(agent_chat)
        mock_logger.exception.assert_called()

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    def test_call_hooks_pre_run_with_empty_hooks(
        self, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test that call_hooks_pre_run handles empty hooks list."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        # Should not raise exception
        agent_chat.call_hooks_pre_run()


class TestAgentChatBaseCallHookForFinalAnswer(unittest.TestCase):
    """Test cases for call_hook_for_final_answer method."""

    def setUp(self):
        """Set up test fixtures."""
        self.hook_instruction = MagicMock()
        self.ctx_rt_aiagent = MagicMock()
        self.ctx_rt_instruction = MagicMock()

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_chat_base.logger")
    def test_call_hook_for_final_answer_executes_all_hooks(
        self, mock_logger, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test that call_hook_for_final_answer executes all registered hooks."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_hook1 = MagicMock()
        mock_hook2 = MagicMock()
        mock_get_hooks.side_effect = [[], [mock_hook1, mock_hook2]]
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        agent_chat.call_hook_for_final_answer()

        mock_hook1.assert_called_once_with(agent_chat)
        mock_hook2.assert_called_once_with(agent_chat)

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("topsailai.workspace.agent.agent_chat_base.logger")
    def test_call_hook_for_final_answer_handles_exception(
        self, mock_logger, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test that call_hook_for_final_answer continues on hook exception."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_hook1 = MagicMock(side_effect=Exception("Hook error"))
        mock_hook2 = MagicMock()
        mock_get_hooks.side_effect = [[], [mock_hook1, mock_hook2]]
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        # Should not raise exception
        agent_chat.call_hook_for_final_answer()

        mock_hook1.assert_called_once_with(agent_chat)
        mock_hook2.assert_called_once_with(agent_chat)
        mock_logger.exception.assert_called()


class TestAgentChatBaseHookBuildAnswer(unittest.TestCase):
    """Test cases for hook_build_answer method."""

    def setUp(self):
        """Set up test fixtures."""
        self.hook_instruction = MagicMock()
        self.ctx_rt_aiagent = MagicMock()
        self.ctx_rt_instruction = MagicMock()

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    def test_hook_build_answer_with_empty_answer(
        self, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test that hook_build_answer returns empty string as-is."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        result = agent_chat.hook_build_answer("")

        self.assertEqual(result, "")

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    def test_hook_build_answer_without_symbol(
        self, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test that hook_build_answer returns answer without symbol when need_symbol=False."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        answer = "This is the answer"
        result = agent_chat.hook_build_answer(answer, need_symbol=False)

        self.assertEqual(result, answer)

    @patch.dict(os.environ, {"TOPSAILAI_SYMBOL_STARTSWITH_ANSWER": "CustomPrefix: "})
    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    def test_hook_build_answer_with_symbol_from_env(
        self, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test that hook_build_answer prepends symbol from environment variable."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_ai_agent = MagicMock()
        mock_ai_agent.agent_name = "TestAgent"
        self.ctx_rt_aiagent.ai_agent = mock_ai_agent

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        answer = "This is the answer"
        result = agent_chat.hook_build_answer(answer, need_symbol=True)

        self.assertEqual(result, "CustomPrefix: This is the answer")

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    def test_hook_build_answer_with_default_symbol(
        self, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test that hook_build_answer uses default symbol when env var not set."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_ai_agent = MagicMock()
        mock_ai_agent.agent_name = "TestAgent"
        self.ctx_rt_aiagent.ai_agent = mock_ai_agent

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        answer = "This is the answer"
        result = agent_chat.hook_build_answer(answer, need_symbol=True)

        self.assertEqual(result, "From 'TestAgent':\nThis is the answer")

    @patch.dict(os.environ, {"TOPSAILAI_SYMBOL_STARTSWITH_ANSWER": "Prefix: "})
    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    def test_hook_build_answer_does_not_duplicate_symbol(
        self, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test that hook_build_answer does not add symbol if already present."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_ai_agent = MagicMock()
        mock_ai_agent.agent_name = "TestAgent"
        self.ctx_rt_aiagent.ai_agent = mock_ai_agent

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        answer = "Prefix: This is the answer"
        result = agent_chat.hook_build_answer(answer, need_symbol=True)

        self.assertEqual(result, "Prefix: This is the answer")


class TestAgentChatBaseHookForAnswer(unittest.TestCase):
    """Test cases for hook_for_answer method."""

    def setUp(self):
        """Set up test fixtures."""
        self.hook_instruction = MagicMock()
        self.ctx_rt_aiagent = MagicMock()
        self.ctx_rt_instruction = MagicMock()

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    def test_hook_for_answer_with_empty_answer(
        self, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test that hook_for_answer returns early for empty answer."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        # Should not raise exception
        agent_chat.hook_for_answer("")

    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    def test_hook_for_answer_without_file_path(
        self, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test that hook_for_answer does not save when env var not set."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        # Should not raise exception
        agent_chat.hook_for_answer("Test answer")

    @patch.dict(os.environ, {"TOPSAILAI_SAVE_RESULT_TO_FILE": "/tmp/result.txt"})
    @patch("topsailai.workspace.agent.hooks.base.init.get_hooks")
    @patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent")
    @patch("topsailai.workspace.agent.agent_chat_base.env_tool")
    @patch("builtins.open", create=True)
    def test_hook_for_answer_saves_to_file(
        self, mock_open, mock_env_tool, mock_set_ai_agent, mock_get_hooks
    ):
        """Test that hook_for_answer saves answer to file when env var is set."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        mock_get_hooks.return_value = []
        mock_env_tool.EnvReaderInstance.get.return_value = None

        agent_chat = AgentChatBase(
            hook_instruction=self.hook_instruction,
            ctx_rt_aiagent=self.ctx_rt_aiagent,
            ctx_rt_instruction=self.ctx_rt_instruction,
        )

        answer = "Test answer content"
        agent_chat.hook_for_answer(answer)

        mock_open.assert_called_once_with("/tmp/result.txt", encoding="utf-8", mode="w")
        mock_open.return_value.__enter__.return_value.write.assert_called_once_with(answer)


if __name__ == "__main__":
    unittest.main()
