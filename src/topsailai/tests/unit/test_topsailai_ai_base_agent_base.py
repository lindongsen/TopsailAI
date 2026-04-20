"""
Unit tests for ai_base/agent_base.py

Tests AgentBase and AgentRun classes.
"""

import unittest
from unittest.mock import MagicMock, patch


class TestAgentBaseInitialization(unittest.TestCase):
    """Test AgentBase initialization."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_llm_model = MagicMock()
        self.mock_llm_model.max_tokens = 4096
        
        self.patches = [
            patch('topsailai.ai_base.agent_base.LLMModel', return_value=self.mock_llm_model),
            patch('topsailai.ai_base.agent_base.AgentTool.__init__', return_value=None),
            patch('topsailai.ai_base.agent_base.get_tools_for_chat'),
            patch('topsailai.ai_base.agent_base.logger'),
            patch('topsailai.ai_base.agent_base.print_critical'),
            patch('topsailai.ai_base.agent_base.print_step'),
            patch('topsailai.ai_base.agent_base.ctxm_give_agent_name'),
            patch('topsailai.ai_base.agent_base.ctxm_set_agent'),
            patch('topsailai.ai_base.agent_base.env_tool'),
            patch('topsailai.ai_base.agent_base.AgentNoCareResult', Exception),
            patch('topsailai.ai_base.agent_base.AgentNeedRefreshSession', Exception),
            patch('topsailai.ai_base.agent_base.DataAgentRefreshSession', MagicMock),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        """Tear down test fixtures."""
        for p in reversed(self.patches):
            p.stop()

    def test_init_with_system_prompt_and_tools_and_agent_name(self):
        """Test basic initialization with required parameters."""
        from topsailai.ai_base.agent_base import AgentBase

        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={"tool1": MagicMock()},
            agent_name="TestAgent"
        )

        self.assertEqual(agent.agent_name, "TestAgent")
        self.assertEqual(agent.agent_type, "")

    def test_init_with_tool_prompt(self):
        """Test initialization with tool prompt."""
        from topsailai.ai_base.agent_base import AgentBase

        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={"tool1": MagicMock()},
            agent_name="TestAgent",
            tool_prompt="Additional tool instructions"
        )

        self.assertEqual(agent.agent_name, "TestAgent")

    def test_init_with_tool_kits(self):
        """Test initialization with tool kits."""
        from topsailai.ai_base.agent_base import AgentBase

        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={"tool1": MagicMock()},
            agent_name="TestAgent",
            tool_kits=["kit1", "kit2"]
        )

        self.assertEqual(agent.agent_name, "TestAgent")

    def test_init_with_excluded_tool_kits(self):
        """Test initialization with excluded tool kits."""
        from topsailai.ai_base.agent_base import AgentBase

        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={"tool1": MagicMock()},
            agent_name="TestAgent",
            excluded_tool_kits=["excluded_kit"]
        )

        self.assertEqual(agent.agent_name, "TestAgent")


class TestAgentBaseMaxTokens(unittest.TestCase):
    """Test AgentBase max_tokens property."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_llm_model = MagicMock()
        self.mock_llm_model.max_tokens = 4096

        self.patches = [
            patch('topsailai.ai_base.agent_base.LLMModel', return_value=self.mock_llm_model),
            patch('topsailai.ai_base.agent_base.AgentTool.__init__', return_value=None),
            patch('topsailai.ai_base.agent_base.logger'),
            patch('topsailai.ai_base.agent_base.print_critical'),
            patch('topsailai.ai_base.agent_base.print_step'),
            patch('topsailai.ai_base.agent_base.ctxm_give_agent_name'),
            patch('topsailai.ai_base.agent_base.ctxm_set_agent'),
            patch('topsailai.ai_base.agent_base.env_tool'),
            patch('topsailai.ai_base.agent_base.AgentNoCareResult', Exception),
            patch('topsailai.ai_base.agent_base.AgentNeedRefreshSession', Exception),
            patch('topsailai.ai_base.agent_base.DataAgentRefreshSession', MagicMock),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        """Tear down test fixtures."""
        for p in reversed(self.patches):
            p.stop()

    def test_max_tokens_property(self):
        """Test max_tokens property returns LLM model value."""
        from topsailai.ai_base.agent_base import AgentBase

        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={"tool1": MagicMock()},
            agent_name="TestAgent"
        )

        self.assertEqual(agent.max_tokens, 4096)


class TestAgentBaseRun(unittest.TestCase):
    """Test AgentBase run method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_llm_model = MagicMock()
        self.step_call_mock = MagicMock()

        self.patches = [
            patch('topsailai.ai_base.agent_base.LLMModel', return_value=self.mock_llm_model),
            patch('topsailai.ai_base.agent_base.AgentTool.__init__', return_value=None),
            patch('topsailai.ai_base.agent_base.get_tools_for_chat'),
            patch('topsailai.ai_base.agent_base.logger'),
            patch('topsailai.ai_base.agent_base.print_critical'),
            patch('topsailai.ai_base.agent_base.print_step'),
            patch('topsailai.ai_base.agent_base.ctxm_give_agent_name'),
            patch('topsailai.ai_base.agent_base.ctxm_set_agent'),
            patch('topsailai.ai_base.agent_base.env_tool'),
            patch('topsailai.ai_base.agent_base.AgentNoCareResult', Exception),
            patch('topsailai.ai_base.agent_base.AgentNeedRefreshSession', Exception),
            patch('topsailai.ai_base.agent_base.DataAgentRefreshSession', MagicMock),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        """Tear down test fixtures."""
        for p in reversed(self.patches):
            p.stop()

    def test_run_sets_context_and_calls_run(self):
        """Test run method sets context and calls internal _run."""
        from topsailai.ai_base.agent_base import AgentBase

        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={"tool1": MagicMock()},
            agent_name="TestAgent"
        )
        agent._run = MagicMock(return_value="result")
        agent.flag_dump_messages = False

        result = agent.run(self.step_call_mock, "test input")

        self.assertEqual(result, "result")
        agent._run.assert_called_once_with(self.step_call_mock, "test input")

    def test_run_dumps_messages_when_flag_set(self):
        """Test run method dumps messages when flag is set."""
        from topsailai.ai_base.agent_base import AgentBase

        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={"tool1": MagicMock()},
            agent_name="TestAgent"
        )
        agent._run = MagicMock(return_value="result")
        agent.dump_messages = MagicMock()
        agent.flag_dump_messages = True

        result = agent.run(self.step_call_mock, "test input")

        self.assertEqual(result, "result")
        agent.dump_messages.assert_called_once()

    def test_run_catches_exception_and_dumps_messages(self):
        """Test run method catches exception and still dumps messages."""
        from topsailai.ai_base.agent_base import AgentBase

        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={"tool1": MagicMock()},
            agent_name="TestAgent"
        )
        agent._run = MagicMock(side_effect=Exception("Test error"))
        agent.dump_messages = MagicMock()
        agent.flag_dump_messages = True

        with self.assertRaises(Exception):
            agent.run(self.step_call_mock, "test input")

        agent.dump_messages.assert_called_once()


class TestAgentRunRunEdgeCases(unittest.TestCase):
    """Test AgentRun._run edge cases with proper setup."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_llm_model = MagicMock()
        self.step_call_mock = MagicMock()

        self.patches = [
            patch('topsailai.ai_base.agent_base.LLMModel', return_value=self.mock_llm_model),
            patch('topsailai.ai_base.agent_base.AgentTool.__init__', return_value=None),
            patch('topsailai.ai_base.agent_base.get_tools_for_chat'),
            patch('topsailai.ai_base.agent_base.logger'),
            patch('topsailai.ai_base.agent_base.print_critical'),
            patch('topsailai.ai_base.agent_base.print_step'),
            patch('topsailai.ai_base.agent_base.env_tool'),
            patch('topsailai.ai_base.agent_base.AgentNoCareResult', Exception),
            patch('topsailai.ai_base.agent_base.AgentNeedRefreshSession', Exception),
            patch('topsailai.ai_base.agent_base.DataAgentRefreshSession', MagicMock),
        ]
        for p in self.patches:
            p.start()

        # Configure env_tool mock
        import topsailai.ai_base.agent_base as module
        module.env_tool.is_use_tool_calls.return_value = True

    def tearDown(self):
        """Tear down test fixtures."""
        for p in reversed(self.patches):
            p.stop()

    def test_run_with_empty_user_input(self):
        """Test _run handles empty user input."""
        from topsailai.ai_base.agent_base import AgentRun

        agent = AgentRun(
            system_prompt="You are a helpful assistant",
            tools={},
            agent_name="TestAgent"
        )
        agent.available_tools = {}
        agent.messages = []  # Initialize messages
        agent.new_session = MagicMock()
        agent.llm_model.chat = MagicMock(return_value=(None, None))

        result = agent._run(self.step_call_mock, "")

        self.assertIsNone(result)

    def test_run_with_no_response_from_llm(self):
        """Test _run handles no response from LLM."""
        from topsailai.ai_base.agent_base import AgentRun

        agent = AgentRun(
            system_prompt="You are a helpful assistant",
            tools={},
            agent_name="TestAgent"
        )
        agent.available_tools = {}
        agent.messages = []  # Initialize messages
        agent.new_session = MagicMock()
        agent.llm_model.chat = MagicMock(return_value=(None, None))

        result = agent._run(self.step_call_mock, "test input")

        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
