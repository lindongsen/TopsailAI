"""
Unit tests for workspace/context module.

Tests for ContextRuntimeBase, ContextRuntimeAgent2LLM, ContextRuntimeData,
ContextRuntimeUtils, ContextRuntimeAIAgent, and summary_tool.

Author: mm-m25
Created: 2026-04-19
"""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock


class TestContextRuntimeBase(unittest.TestCase):
    """Test cases for ContextRuntimeBase class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_agent = MagicMock()
        self.mock_agent.agent_type = "test_agent"
        self.mock_agent.messages = []

    @patch("topsailai.workspace.context.base.ctx_manager")
    @patch("topsailai.workspace.context.base.get_llm_chat")
    @patch("topsailai.workspace.context.base.summary_tool")
    @patch("topsailai.workspace.context.base.story_tool")
    @patch("topsailai.workspace.context.base.file_tool")
    @patch("topsailai.workspace.context.base.env_tool")
    @patch("topsailai.workspace.context.base.json_tool")
    def test_init(self, mock_json, mock_env, mock_file, mock_story, mock_summary, mock_llm, mock_ctx):
        """Test ContextRuntimeBase initialization."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()

        self.assertEqual(runtime.session_id, "")
        self.assertEqual(runtime.messages, [])
        self.assertIsNone(runtime.ai_agent)

    @patch("topsailai.workspace.context.base.json_tool")
    def test_last_user_message(self, mock_json):
        """Test getting last user message."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_json.json_load.side_effect = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "How are you?"},
        ]

        runtime = ContextRuntimeBase()
        runtime.messages = ["msg1", "msg2", "msg3"]

        result = runtime.last_user_message
        self.assertEqual(result, "msg3")

    @patch("topsailai.workspace.context.base.json_tool")
    def test_last_user_message_no_user(self, mock_json):
        """Test getting last user message when no user message exists."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_json.json_load.side_effect = [
            {"role": "assistant", "content": "Hi"},
            {"role": "system", "content": "System"},
        ]

        runtime = ContextRuntimeBase()
        runtime.messages = ["msg1", "msg2"]

        result = runtime.last_user_message
        self.assertIsNone(result)

    @patch("topsailai.workspace.context.base.ctx_manager")
    def test_init_with_session(self, mock_ctx):
        """Test initialization with session and agent."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.init("session123", self.mock_agent)

        self.assertEqual(runtime.session_id, "session123")
        self.assertEqual(runtime.ai_agent, self.mock_agent)

    def test_append_message(self):
        """Test appending message to messages list."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.append_message({"role": "user", "content": "test"})

        self.assertEqual(len(runtime.messages), 1)
        self.assertEqual(runtime.messages[0], {"role": "user", "content": "test"})

    def test_append_message_none(self):
        """Test appending None message does nothing."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.append_message(None)

        self.assertEqual(len(runtime.messages), 0)

    def test_set_messages(self):
        """Test setting messages list."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.set_messages([{"role": "user", "content": "msg1"}])

        self.assertEqual(len(runtime.messages), 1)

    def test_set_messages_empty(self):
        """Test setting empty messages list."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.messages = [{"role": "user", "content": "msg1"}]
        runtime.set_messages([])

        self.assertEqual(len(runtime.messages), 0)

    def test_set_messages_none(self):
        """Test setting None converts to empty list."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.set_messages(None)

        self.assertEqual(runtime.messages, [])

    @patch("topsailai.workspace.context.base.ctx_manager")
    def test_reset_messages(self, mock_ctx):
        """Test resetting messages from session storage."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_ctx.get_messages_by_session.return_value = [{"role": "user", "content": "session_msg"}]

        runtime = ContextRuntimeBase()
        runtime.session_id = "session123"
        runtime.reset_messages()

        self.assertEqual(len(runtime.messages), 1)

    @patch("topsailai.workspace.context.base.ctx_manager")
    def test_reset_messages_no_session(self, mock_ctx):
        """Test resetting messages with no session ID."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.session_id = ""
        runtime.reset_messages()

        mock_ctx.get_messages_by_session.assert_not_called()

    @patch("topsailai.workspace.context.base.env_tool")
    def test_get_quantity_threshold_disabled(self, mock_env):
        """Test quantity threshold when disabled."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env.EnvReaderInstance.get.return_value = 0

        runtime = ContextRuntimeBase()
        result = runtime._get_quantity_threshold()

        self.assertEqual(result, 0)

    @patch("topsailai.workspace.context.base.env_tool")
    def test_get_quantity_threshold_enabled(self, mock_env):
        """Test quantity threshold when enabled."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env.EnvReaderInstance.get.return_value = 15

        runtime = ContextRuntimeBase()
        result = runtime._get_quantity_threshold()

        self.assertGreater(result, 0)

    @patch("topsailai.workspace.context.base.env_tool")
    def test_get_head_offset_to_keep_negative(self, mock_env):
        """Test head offset with negative value returns 0."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env.EnvReaderInstance.get.return_value = -5

        runtime = ContextRuntimeBase()
        result = runtime._get_head_offset_to_keep_in_summary()

        self.assertEqual(result, 0)

    @patch("topsailai.workspace.context.base.env_tool")
    def test_get_head_offset_to_keep_positive(self, mock_env):
        """Test head offset with positive value."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env.EnvReaderInstance.get.return_value = 10

        runtime = ContextRuntimeBase()
        result = runtime._get_head_offset_to_keep_in_summary()

        self.assertEqual(result, 10)


class TestContextRuntimeAgent2LLM(unittest.TestCase):
    """Test cases for ContextRuntimeAgent2LLM class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_agent = MagicMock()
        self.mock_agent.agent_type = "test_agent"
        self.mock_agent.messages = []
        self.mock_agent.get_work_memory_first_position.return_value = 0

    def test_init(self):
        """Test ContextRuntimeAgent2LLM initialization."""
        from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM

        runtime = ContextRuntimeAgent2LLM.__new__(ContextRuntimeAgent2LLM)
        self.assertIsInstance(runtime, ContextRuntimeAgent2LLM)

    def test_del_agent_messages_empty_indexes(self):
        """Test deleting with empty indexes list."""
        from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM

        runtime = ContextRuntimeAgent2LLM.__new__(ContextRuntimeAgent2LLM)
        runtime.ai_agent = self.mock_agent

        result = runtime.del_agent_messages([])

        self.assertEqual(result, [])

    def test_del_agent_messages_no_work_memory(self):
        """Test deleting when work memory position is None."""
        from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM

        self.mock_agent.get_work_memory_first_position.return_value = None

        runtime = ContextRuntimeAgent2LLM.__new__(ContextRuntimeAgent2LLM)
        runtime.ai_agent = self.mock_agent

        result = runtime.del_agent_messages([0, 1])

        self.assertEqual(result, [])

    @patch("topsailai.workspace.context.agent2llm.json_tool")
    def test_del_agent_messages_success(self, mock_json):
        """Test successful message deletion."""
        from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM

        mock_json.json_load.side_effect = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "msg2"},
            {"role": "user", "content": "msg3"},
        ]

        self.mock_agent.messages = ["msg1", "msg2", "msg3"]

        runtime = ContextRuntimeAgent2LLM.__new__(ContextRuntimeAgent2LLM)
        runtime.ai_agent = self.mock_agent

        result = runtime.del_agent_messages([0])

        self.assertEqual(result, [0])

    @patch("topsailai.workspace.context.agent2llm.json_tool")
    def test_del_agent_messages_with_last(self, mock_json):
        """Test deleting messages including last one."""
        from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM

        mock_json.json_load.side_effect = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "msg2"},
        ]

        self.mock_agent.messages = ["msg1", "msg2"]

        runtime = ContextRuntimeAgent2LLM.__new__(ContextRuntimeAgent2LLM)
        runtime.ai_agent = self.mock_agent

        result = runtime.del_agent_messages([0], to_del_last=True)

        self.assertEqual(result, [0])

    @patch("topsailai.workspace.context.agent2llm.env_tool")
    def test_is_need_summarize_disabled(self, mock_env):
        """Test summarization check when disabled."""
        from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM

        mock_env.EnvReaderInstance.get.return_value = 0

        runtime = ContextRuntimeAgent2LLM.__new__(ContextRuntimeAgent2LLM)
        runtime.ai_agent = self.mock_agent

        result = runtime.is_need_summarize_for_processing()

        self.assertFalse(result)

    @patch("topsailai.workspace.context.agent2llm.env_tool")
    def test_is_need_summarize_below_threshold(self, mock_env):
        """Test summarization check when below threshold."""
        from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM

        mock_env.EnvReaderInstance.get.return_value = 100

        self.mock_agent.messages = ["msg"] * 50

        runtime = ContextRuntimeAgent2LLM.__new__(ContextRuntimeAgent2LLM)
        runtime.ai_agent = self.mock_agent

        result = runtime.is_need_summarize_for_processing()

        self.assertFalse(result)


class TestContextRuntimeData(unittest.TestCase):
    """Test cases for ContextRuntimeData class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_agent = MagicMock()
        self.mock_agent.agent_type = "test_agent"
        self.mock_agent.messages = []

    def test_init(self):
        """Test ContextRuntimeData initialization."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        runtime = ContextRuntimeData.__new__(ContextRuntimeData)
        runtime.session_id = ""
        runtime.messages = []
        runtime.ai_agent = None

        self.assertIsInstance(runtime, ContextRuntimeData)

    @patch("topsailai.workspace.context.ctx_runtime.ctx_manager")
    def test_add_session_message(self, mock_ctx):
        """Test adding session message."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        runtime = ContextRuntimeData.__new__(ContextRuntimeData)
        runtime.session_id = "session123"
        runtime.messages = []

        runtime.add_session_message("user", "Hello")

        self.assertEqual(len(runtime.messages), 1)
        mock_ctx.add_session_message.assert_called_once()

    @patch("topsailai.workspace.context.ctx_runtime.ctx_manager")
    def test_add_session_message_no_session(self, mock_ctx):
        """Test adding session message without session ID."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        runtime = ContextRuntimeData.__new__(ContextRuntimeData)
        runtime.session_id = ""
        runtime.messages = []

        runtime.add_session_message("user", "Hello")

        self.assertEqual(len(runtime.messages), 1)
        mock_ctx.add_session_message.assert_not_called()

    @patch("topsailai.workspace.context.ctx_runtime.ctx_manager")
    def test_add_session_message_dict(self, mock_ctx):
        """Test adding session message as dict."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        runtime = ContextRuntimeData.__new__(ContextRuntimeData)
        runtime.session_id = "session123"
        runtime.messages = []

        runtime.add_session_message_dict({"role": "user", "content": "test"})

        self.assertEqual(len(runtime.messages), 1)

    def test_add_session_message_dict_invalid(self):
        """Test adding invalid message dict raises assertion."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        runtime = ContextRuntimeData.__new__(ContextRuntimeData)

        with self.assertRaises(AssertionError):
            runtime.add_session_message_dict("not a dict")

    @patch("topsailai.workspace.context.ctx_runtime.ctx_manager")
    def test_del_session_message(self, mock_ctx):
        """Test deleting session message by index."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        mock_msg = MagicMock()
        mock_msg.msg_id = "msg123"
        mock_ctx.get_messages_by_session.return_value = [mock_msg]

        runtime = ContextRuntimeData.__new__(ContextRuntimeData)
        runtime.session_id = "session123"
        runtime.messages = [{"role": "user", "content": "msg1"}]

        runtime.del_session_message(0)

        self.assertEqual(len(runtime.messages), 0)

    def test_del_session_message_invalid_index(self):
        """Test deleting with invalid index raises assertion."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        runtime = ContextRuntimeData.__new__(ContextRuntimeData)
        runtime.session_id = "session123"
        runtime.messages = [{"role": "user", "content": "msg1"}]

        with self.assertRaises(AssertionError):
            runtime.del_session_message(1)

    @patch("topsailai.workspace.context.ctx_runtime.ctx_manager")
    @patch("topsailai.workspace.context.ctx_runtime.json_tool")
    def test_del_session_messages(self, mock_json, mock_ctx):
        """Test deleting multiple session messages."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        mock_json.json_load.side_effect = [
            {"role": "user", "content": "msg1"},
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "msg2"},
        ]

        mock_msg = MagicMock()
        mock_msg.msg_id = "msg123"
        mock_ctx.get_messages_by_session.return_value = [mock_msg]

        runtime = ContextRuntimeData.__new__(ContextRuntimeData)
        runtime.session_id = "session123"
        runtime.messages = ["msg1", "sys", "msg2"]

        result = runtime.del_session_messages([0])

        self.assertEqual(result, [0])

    def test_del_session_messages_empty(self):
        """Test deleting with empty indexes returns empty list."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        runtime = ContextRuntimeData.__new__(ContextRuntimeData)
        runtime.messages = ["msg1", "msg2"]

        result = runtime.del_session_messages([])

        self.assertEqual(result, [])

    @patch("topsailai.workspace.context.ctx_runtime.ctx_manager")
    @patch("topsailai.workspace.context.ctx_runtime.env_tool")
    def test_is_need_summarize_for_processed_disabled(self, mock_env, mock_ctx):
        """Test summarization check for processed when disabled."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        mock_env.EnvReaderInstance.get.return_value = 0

        runtime = ContextRuntimeData.__new__(ContextRuntimeData)
        runtime.messages = ["msg"] * 50

        result = runtime.is_need_summarize_for_processed()

        self.assertFalse(result)

    def test_is_need_summarize_for_processed_enabled(self):
        """Test summarization check for processed when enabled."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        runtime = ContextRuntimeData.__new__(ContextRuntimeData)
        # Patch the _get_quantity_threshold method to return a low threshold
        runtime._get_quantity_threshold = MagicMock(return_value=10)
        runtime.messages = ["msg"] * 50

        result = runtime.is_need_summarize_for_processed()

        self.assertTrue(result)


class TestSummaryTool(unittest.TestCase):
    """Test cases for summary_tool module."""

    def setUp(self):
        """Reset global state before each test."""
        import topsailai.workspace.context.summary_tool as summary_module
        summary_module.g_summary_prompt_map = {}

    @patch("topsailai.workspace.context.summary_tool.env_tool")
    @patch("topsailai.workspace.context.summary_tool.format_tool")
    def test_get_summary_prompt_extra_map_empty(self, mock_format, mock_env):
        """Test getting summary prompt extra map when empty."""
        from topsailai.workspace.context.summary_tool import get_summary_prompt_extra_map

        mock_env.EnvReaderInstance.get.return_value = ""

        result = get_summary_prompt_extra_map()

        self.assertIsNone(result)

    @patch("topsailai.workspace.context.summary_tool.env_tool")
    @patch("topsailai.workspace.context.summary_tool.format_tool")
    def test_get_summary_prompt_extra_map_parsed(self, mock_format, mock_env):
        """Test getting summary prompt extra map with content."""
        from topsailai.workspace.context.summary_tool import get_summary_prompt_extra_map
        import topsailai.workspace.context.summary_tool as summary_module

        summary_module.g_summary_prompt_map = {}

        mock_env.EnvReaderInstance.get.return_value = "agent1=file1,file2"
        mock_format.parse_str_to_dict.return_value = {"agent1": "file1,file2"}

        result = get_summary_prompt_extra_map()

        self.assertIn("agent1", result)

    @patch("topsailai.workspace.context.summary_tool.env_tool")
    @patch("topsailai.workspace.context.summary_tool.format_tool")
    def test_get_summary_prompt_extra_map_cached(self, mock_format, mock_env):
        """Test getting summary prompt extra map returns cached value."""
        from topsailai.workspace.context.summary_tool import get_summary_prompt_extra_map
        import topsailai.workspace.context.summary_tool as summary_module

        summary_module.g_summary_prompt_map = {"cached": ["file1"]}

        result = get_summary_prompt_extra_map()

        self.assertIn("cached", result)
        mock_env.EnvReaderInstance.get.assert_not_called()

    @patch("topsailai.workspace.context.summary_tool.prompt_tool")
    @patch("topsailai.workspace.context.summary_tool.get_summary_prompt_extra_map")
    def test_get_summary_prompt(self, mock_get_map, mock_prompt):
        """Test getting summary prompt for agent type."""
        from topsailai.workspace.context.summary_tool import get_summary_prompt

        mock_get_map.return_value = {"test_agent": ["prompt_file"]}
        mock_prompt.read_prompt.return_value = "summary prompt content"

        result = get_summary_prompt("test_agent")

        self.assertEqual(result, "summary prompt content")

    @patch("topsailai.workspace.context.summary_tool.get_summary_prompt_extra_map")
    def test_get_summary_prompt_no_map(self, mock_get_map):
        """Test getting summary prompt when no map exists."""
        from topsailai.workspace.context.summary_tool import get_summary_prompt

        mock_get_map.return_value = None

        result = get_summary_prompt("unknown_agent")

        self.assertEqual(result, "")

    @patch("topsailai.workspace.context.summary_tool.prompt_tool")
    @patch("topsailai.workspace.context.summary_tool.get_summary_prompt_extra_map")
    def test_get_summary_prompt_agent_not_in_map(self, mock_get_map, mock_prompt):
        """Test getting summary prompt for agent not in map."""
        from topsailai.workspace.context.summary_tool import get_summary_prompt

        mock_get_map.return_value = {"other_agent": ["file1"]}

        result = get_summary_prompt("unknown_agent")

        self.assertEqual(result, "")


class TestContextRuntimeUtils(unittest.TestCase):
    """Test cases for ContextRuntimeUtils class."""

    def test_session_id_property(self):
        """Test session_id property returns from ctx_runtime_data."""
        from topsailai.workspace.context.agent import ContextRuntimeUtils

        mock_data = MagicMock()
        mock_data.session_id = "test_session"

        utils = ContextRuntimeUtils(mock_data)

        self.assertEqual(utils.session_id, "test_session")

    def test_messages_property(self):
        """Test messages property returns from ctx_runtime_data."""
        from topsailai.workspace.context.agent import ContextRuntimeUtils

        mock_data = MagicMock()
        mock_data.messages = [{"role": "user", "content": "test"}]

        utils = ContextRuntimeUtils(mock_data)

        self.assertEqual(utils.messages, [{"role": "user", "content": "test"}])

    def test_ai_agent_property(self):
        """Test ai_agent property returns from ctx_runtime_data."""
        from topsailai.workspace.context.agent import ContextRuntimeUtils

        mock_agent = MagicMock()
        mock_data = MagicMock()
        mock_data.ai_agent = mock_agent

        utils = ContextRuntimeUtils(mock_data)

        self.assertEqual(utils.ai_agent, mock_agent)


class TestContextRuntimeAIAgent(unittest.TestCase):
    """Test cases for ContextRuntimeAIAgent class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_agent = MagicMock()
        self.mock_agent.messages = [{"role": "user", "content": "last message"}]

    @patch("topsailai.workspace.context.agent.ctx_manager")
    def test_add_session_message_with_provided_message(self, mock_ctx):
        """Test adding provided message to session."""
        from topsailai.workspace.context.agent import ContextRuntimeAIAgent

        mock_data = MagicMock()
        mock_data.session_id = "session123"
        mock_data.messages = []
        mock_data.ai_agent = self.mock_agent
        mock_data.append_message = MagicMock()

        agent = ContextRuntimeAIAgent(mock_data)
        agent.add_session_message({"role": "user", "content": "test"})

        mock_data.append_message.assert_called_once()
        mock_ctx.add_session_message.assert_called_once()

    @patch("topsailai.workspace.context.agent.ctx_manager")
    def test_add_session_message_from_agent(self, mock_ctx):
        """Test adding message from agent's last message."""
        from topsailai.workspace.context.agent import ContextRuntimeAIAgent

        mock_data = MagicMock()
        mock_data.session_id = "session123"
        mock_data.messages = []
        mock_data.ai_agent = self.mock_agent
        mock_data.append_message = MagicMock()

        agent = ContextRuntimeAIAgent(mock_data)
        agent.add_session_message()

        mock_data.append_message.assert_called_once()

    @patch("topsailai.workspace.context.agent.ctx_manager")
    def test_add_session_message_no_session(self, mock_ctx):
        """Test adding message without session ID."""
        from topsailai.workspace.context.agent import ContextRuntimeAIAgent

        mock_data = MagicMock()
        mock_data.session_id = ""
        mock_data.messages = []
        mock_data.ai_agent = self.mock_agent
        mock_data.append_message = MagicMock()

        agent = ContextRuntimeAIAgent(mock_data)
        agent.add_session_message({"role": "user", "content": "test"})

        mock_ctx.add_session_message.assert_not_called()
        mock_data.append_message.assert_called_once()

    def test_add_runtime_messages(self):
        """Test adding runtime messages to agent."""
        from topsailai.workspace.context.agent import ContextRuntimeAIAgent

        mock_data = MagicMock()
        mock_data.messages = [{"role": "user", "content": "runtime msg"}]
        mock_data.ai_agent = self.mock_agent

        agent = ContextRuntimeAIAgent(mock_data)
        agent.add_runtime_messages()

        self.assertEqual(len(self.mock_agent.messages), 2)

    def test_add_runtime_messages_empty(self):
        """Test adding empty runtime messages."""
        from topsailai.workspace.context.agent import ContextRuntimeAIAgent

        mock_data = MagicMock()
        mock_data.messages = []
        mock_data.ai_agent = self.mock_agent

        initial_count = len(self.mock_agent.messages)

        agent = ContextRuntimeAIAgent(mock_data)
        agent.add_runtime_messages()

        self.assertEqual(len(self.mock_agent.messages), initial_count)


if __name__ == "__main__":
    unittest.main()
