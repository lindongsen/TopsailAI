"""
Unit tests for workspace/agent_shell module.

Tests the get_ai_agent and get_agent_chat factory functions.
"""

import os
import unittest
from unittest.mock import MagicMock, patch


class TestGetAIAgent(unittest.TestCase):
    """Test suite for get_ai_agent function."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock environment variables
        self.env_patcher = patch.dict(os.environ, {}, clear=True)
        self.env_patcher.start()
        
        # Mock env_tool
        self.env_tool_patcher = patch('topsailai.workspace.agent_shell.env_tool')
        self.mock_env_tool = self.env_tool_patcher.start()
        self.mock_env_tool.EnvReaderInstance.get_list_str.return_value = None
        self.mock_env_tool.is_debug_mode.return_value = False
        
        # Mock get_agent_type
        self.agent_type_patcher = patch('topsailai.workspace.agent_shell.get_agent_type')
        self.mock_get_agent_type = self.agent_type_patcher.start()
        
        # Mock AgentRun
        self.agent_run_patcher = patch('topsailai.workspace.agent_shell.AgentRun')
        self.mock_agent_run = self.agent_run_patcher.start()
        
        # Mock ContentDots
        self.content_dots_patcher = patch('topsailai.workspace.agent_shell.ContentDots')
        self.mock_content_dots = self.content_dots_patcher.start()
        
        # Setup mock agent_type
        self.mock_agent_type = MagicMock()
        self.mock_agent_type.SYSTEM_PROMPT = "You are a helpful assistant."
        self.mock_agent_type.AGENT_NAME = "ReActAgent"
        self.mock_get_agent_type.return_value = self.mock_agent_type
        
        # Setup mock agent instance
        self.mock_agent_instance = MagicMock()
        self.mock_agent_instance.llm_model = MagicMock()
        self.mock_agent_instance.llm_model.content_senders = []
        self.mock_agent_instance.flag_dump_messages = False
        self.mock_agent_run.return_value = self.mock_agent_instance

    def tearDown(self):
        """Clean up test fixtures."""
        self.env_patcher.stop()
        self.env_tool_patcher.stop()
        self.agent_type_patcher.stop()
        self.agent_run_patcher.stop()
        self.content_dots_patcher.stop()

    def test_get_ai_agent_default_parameters(self):
        """Test get_ai_agent with default parameters."""
        from topsailai.workspace.agent_shell import get_ai_agent
        
        agent = get_ai_agent()
        
        # Verify AgentRun was called with correct parameters
        self.mock_agent_run.assert_called_once()
        call_args = self.mock_agent_run.call_args[0]
        call_kwargs = self.mock_agent_run.call_args[1]
        
        # First positional arg is system_prompt
        self.assertIn(self.mock_agent_type.SYSTEM_PROMPT, call_args[0])
        self.assertEqual(call_kwargs['agent_name'], self.mock_agent_type.AGENT_NAME)
        self.assertIsNone(call_kwargs['tools'])
        self.assertEqual(call_kwargs['excluded_tool_kits'], None)
        
        # Verify agent_type attribute is set
        self.assertEqual(agent.agent_type, self.mock_agent_type.AGENT_NAME)

    def test_get_ai_agent_with_system_prompt(self):
        """Test get_ai_agent with custom system prompt."""
        from topsailai.workspace.agent_shell import get_ai_agent
        
        custom_prompt = "You are a coding assistant."
        agent = get_ai_agent(system_prompt=custom_prompt)
        
        call_args = self.mock_agent_run.call_args[0]
        self.assertIn(custom_prompt, call_args[0])

    def test_get_ai_agent_with_disabled_tools(self):
        """Test get_ai_agent with disabled tools."""
        from topsailai.workspace.agent_shell import get_ai_agent
        
        disabled = ["tool1", "tool2"]
        agent = get_ai_agent(disabled_tools=disabled)
        
        call_kwargs = self.mock_agent_run.call_args[1]
        self.assertEqual(call_kwargs['excluded_tool_kits'], disabled)

    def test_get_ai_agent_with_env_disabled_tools(self):
        """Test get_ai_agent reads disabled tools from environment."""
        from topsailai.workspace.agent_shell import get_ai_agent
        
        self.mock_env_tool.EnvReaderInstance.get_list_str.return_value = ["env_tool1"]
        
        agent = get_ai_agent()
        
        call_kwargs = self.mock_agent_run.call_args[1]
        self.assertEqual(call_kwargs['excluded_tool_kits'], ["env_tool1"])

    def test_get_ai_agent_with_empty_env_disabled_tools(self):
        """Test get_ai_agent handles empty env disabled tools."""
        from topsailai.workspace.agent_shell import get_ai_agent
        
        self.mock_env_tool.EnvReaderInstance.get_list_str.return_value = []
        
        agent = get_ai_agent()
        
        call_kwargs = self.mock_agent_run.call_args[1]
        self.assertEqual(call_kwargs['excluded_tool_kits'], [])

    def test_get_ai_agent_with_enabled_tools(self):
        """Test get_ai_agent with enabled tools."""
        from topsailai.workspace.agent_shell import get_ai_agent
        
        enabled = ["tool1", "tool2"]
        agent = get_ai_agent(enabled_tools=enabled)
        
        call_kwargs = self.mock_agent_run.call_args[1]
        self.assertEqual(call_kwargs['tool_kits'], enabled)

    def test_get_ai_agent_with_tool_map(self):
        """Test get_ai_agent with custom tool map."""
        from topsailai.workspace.agent_shell import get_ai_agent
        
        tool_map = {"custom_tool": lambda x: x}
        agent = get_ai_agent(tool_map=tool_map)
        
        call_kwargs = self.mock_agent_run.call_args[1]
        self.assertEqual(call_kwargs['tools'], tool_map)

    def test_get_ai_agent_with_to_dump_messages(self):
        """Test get_ai_agent sets dump_messages flag."""
        from topsailai.workspace.agent_shell import get_ai_agent
        
        agent = get_ai_agent(to_dump_messages=True)
        
        self.assertTrue(agent.flag_dump_messages)

    def test_get_ai_agent_without_dump_messages(self):
        """Test get_ai_agent does not set dump_messages flag by default."""
        from topsailai.workspace.agent_shell import get_ai_agent
        
        agent = get_ai_agent(to_dump_messages=False)
        
        self.assertFalse(agent.flag_dump_messages)

    def test_get_ai_agent_debug_mode_with_stream(self):
        """Test get_ai_agent adds ContentDots in debug mode with stream."""
        from topsailai.workspace.agent_shell import get_ai_agent
        
        self.mock_env_tool.is_debug_mode.return_value = True
        self.mock_env_tool.EnvReaderInstance.check_bool.return_value = True
        
        agent = get_ai_agent()
        
        self.assertIn(self.mock_content_dots.return_value, agent.llm_model.content_senders)

    def test_get_ai_agent_debug_mode_without_stream(self):
        """Test get_ai_agent does not add ContentDots without stream."""
        from topsailai.workspace.agent_shell import get_ai_agent
        
        self.mock_env_tool.is_debug_mode.return_value = True
        self.mock_env_tool.EnvReaderInstance.check_bool.return_value = False
        
        agent = get_ai_agent()
        
        self.assertEqual(len(agent.llm_model.content_senders), 0)

    def test_get_ai_agent_with_custom_agent_type(self):
        """Test get_ai_agent with custom agent type name."""
        from topsailai.workspace.agent_shell import get_ai_agent
        
        custom_type = "CustomAgent"
        agent = get_ai_agent(agent_type=custom_type)
        
        self.assertEqual(agent.agent_type, custom_type)

    def test_get_ai_agent_with_env_agent_name(self):
        """Test get_ai_agent uses environment agent name."""
        from topsailai.workspace.agent_shell import get_ai_agent
        
        os.environ["TOPSAILAI_AGENT_NAME"] = "EnvAgent"
        
        agent = get_ai_agent()
        
        call_kwargs = self.mock_agent_run.call_args[1]
        self.assertEqual(call_kwargs['agent_name'], "EnvAgent")

    def test_get_ai_agent_env_disabled_tools_takes_precedence(self):
        """Test that env disabled tools takes precedence over arg disabled tools."""
        from topsailai.workspace.agent_shell import get_ai_agent
        
        self.mock_env_tool.EnvReaderInstance.get_list_str.return_value = ["env_tool"]
        
        agent = get_ai_agent(disabled_tools=["arg_tool"])
        
        call_kwargs = self.mock_agent_run.call_args[1]
        self.assertEqual(call_kwargs['excluded_tool_kits'], ["env_tool"])


class TestGetAgentChat(unittest.TestCase):
    """Test suite for get_agent_chat function."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock environment variables
        self.env_patcher = patch.dict(os.environ, {
            "TOPSAILAI_TASK": "",
            "SESSION_ID": "",
            "TOPSAILAI_SESSION_ID": "",
        }, clear=False)
        self.env_patcher.start()
        
        # Mock env_tool
        self.env_tool_patcher = patch('topsailai.workspace.agent_shell.env_tool')
        self.mock_env_tool = self.env_tool_patcher.start()
        self.mock_env_tool.is_debug_mode.return_value = False
        self.mock_env_tool.is_interactive_mode.return_value = True
        self.mock_env_tool.get_session_id.return_value = "test-session-123"
        
        # Mock file_tool
        self.file_tool_patcher = patch('topsailai.workspace.agent_shell.file_tool')
        self.mock_file_tool = self.file_tool_patcher.start()
        self.mock_file_tool.get_file_content_fuzzy.return_value = (True, "")
        
        # Mock thread_local_tool
        self.thread_local_patcher = patch('topsailai.workspace.agent_shell.thread_local_tool')
        self.mock_thread_local = self.thread_local_patcher.start()
        
        # Mock get_agent_type
        self.agent_type_patcher = patch('topsailai.workspace.agent_shell.get_agent_type')
        self.mock_get_agent_type = self.agent_type_patcher.start()
        
        # Mock AgentRun
        self.agent_run_patcher = patch('topsailai.workspace.agent_shell.AgentRun')
        self.mock_agent_run = self.agent_run_patcher.start()
        
        # Mock ContentDots
        self.content_dots_patcher = patch('topsailai.workspace.agent_shell.ContentDots')
        self.mock_content_dots = self.content_dots_patcher.start()
        
        # Mock HookInstruction
        self.hook_instruction_patcher = patch('topsailai.workspace.agent_shell.HookInstruction')
        self.mock_hook_instruction = self.hook_instruction_patcher.start()
        
        # Mock ContextRuntimeData
        self.ctx_data_patcher = patch('topsailai.workspace.agent_shell.ContextRuntimeData')
        self.mock_ctx_data = self.ctx_data_patcher.start()
        
        # Mock ContextRuntimeAIAgent
        self.ctx_aiagent_patcher = patch('topsailai.workspace.agent_shell.ContextRuntimeAIAgent')
        self.mock_ctx_aiagent = self.ctx_aiagent_patcher.start()
        
        # Mock ContextRuntimeInstructions
        self.ctx_instruction_patcher = patch('topsailai.workspace.agent_shell.ContextRuntimeInstructions')
        self.mock_ctx_instruction = self.ctx_instruction_patcher.start()
        
        # Mock get_message
        self.get_message_patcher = patch('topsailai.workspace.agent_shell.get_message')
        self.mock_get_message = self.get_message_patcher.start()
        self.mock_get_message.return_value = ""
        
        # Mock ctx_manager
        self.ctx_manager_patcher = patch('topsailai.workspace.agent_shell.ctx_manager')
        self.mock_ctx_manager = self.ctx_manager_patcher.start()
        self.mock_ctx_manager.exists_session.return_value = False
        
        # Mock AgentChat
        self.agent_chat_patcher = patch('topsailai.workspace.agent_shell.AgentChat')
        self.mock_agent_chat = self.agent_chat_patcher.start()
        
        # Setup mock agent_type
        self.mock_agent_type = MagicMock()
        self.mock_agent_type.SYSTEM_PROMPT = "You are a helpful assistant."
        self.mock_agent_type.AGENT_NAME = "ReActAgent"
        self.mock_get_agent_type.return_value = self.mock_agent_type
        
        # Setup mock agent instance
        self.mock_agent_instance = MagicMock()
        self.mock_agent_instance.llm_model = MagicMock()
        self.mock_agent_instance.llm_model.content_senders = []
        self.mock_agent_instance.llm_model.max_tokens = 1000
        self.mock_agent_instance.llm_model.temperature = 0.5
        self.mock_agent_instance.flag_dump_messages = False
        self.mock_agent_run.return_value = self.mock_agent_instance
        
        # Setup mock context runtime data
        self.mock_ctx_data_instance = MagicMock()
        self.mock_ctx_data_instance.messages = []
        self.mock_ctx_data.return_value = self.mock_ctx_data_instance
        
        # Setup mock hook instruction
        self.mock_hook_instruction_instance = MagicMock()
        self.mock_hook_instruction.return_value = self.mock_hook_instruction_instance
        
        # Setup mock agent chat
        self.mock_agent_chat_instance = MagicMock()
        self.mock_agent_chat.return_value = self.mock_agent_chat_instance

    def tearDown(self):
        """Clean up test fixtures."""
        self.env_patcher.stop()
        self.env_tool_patcher.stop()
        self.file_tool_patcher.stop()
        self.thread_local_patcher.stop()
        self.agent_type_patcher.stop()
        self.agent_run_patcher.stop()
        self.content_dots_patcher.stop()
        self.hook_instruction_patcher.stop()
        self.ctx_data_patcher.stop()
        self.ctx_aiagent_patcher.stop()
        self.ctx_instruction_patcher.stop()
        self.get_message_patcher.stop()
        self.ctx_manager_patcher.stop()
        self.agent_chat_patcher.stop()

    def test_get_agent_chat_default_parameters(self):
        """Test get_agent_chat with default parameters."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        agent_chat = get_agent_chat()
        
        # Verify AgentChat was created
        self.mock_agent_chat.assert_called_once()
        call_kwargs = self.mock_agent_chat.call_args[1]
        self.assertEqual(call_kwargs['hook_instruction'], self.mock_hook_instruction_instance)
        self.assertEqual(call_kwargs['session_head_tail_offset'], None)
        
        # Verify first_message is set
        self.assertEqual(agent_chat.first_message, "")

    def test_get_agent_chat_with_message(self):
        """Test get_agent_chat with provided message."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        message = "Hello, how are you?"
        agent_chat = get_agent_chat(message=message)
        
        self.assertEqual(agent_chat.first_message, message)

    def test_get_agent_chat_with_session_id(self):
        """Test get_agent_chat with provided session_id."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        session_id = "my-session-456"
        agent_chat = get_agent_chat(session_id=session_id)
        
        # Verify thread name was set
        self.mock_thread_local.set_thread_name.assert_called_with(session_id)
        
        # Verify session was created
        self.mock_ctx_manager.create_session.assert_called_once()

    def test_get_agent_chat_with_agent_name(self):
        """Test get_agent_chat with provided agent_name."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        agent_name = "MyAgent"
        agent_chat = get_agent_chat(agent_name=agent_name, session_id="test-session")
        
        # Verify thread variable was set
        self.mock_thread_local.set_thread_var.assert_called()
        
        # Verify agent name was set on ai_agent
        self.assertEqual(self.mock_agent_instance.agent_name, agent_name)

    def test_get_agent_chat_with_session_head_tail_offset(self):
        """Test get_agent_chat with session_head_tail_offset."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        offset = 5
        agent_chat = get_agent_chat(session_head_tail_offset=offset)
        
        call_kwargs = self.mock_agent_chat.call_args[1]
        self.assertEqual(call_kwargs['session_head_tail_offset'], offset)

    def test_get_agent_chat_debug_mode_need_print_session_false(self):
        """Test get_agent_chat sets need_print_session=False in debug mode."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        self.mock_env_tool.is_debug_mode.return_value = True
        
        agent_chat = get_agent_chat()
        
        # In debug mode, need_print_session should be False
        self.mock_thread_local.set_thread_var.assert_not_called()

    def test_get_agent_chat_non_interactive_mode(self):
        """Test get_agent_chat disables print and input in non-interactive mode."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        self.mock_env_tool.is_interactive_mode.return_value = False
        
        agent_chat = get_agent_chat()
        
        # Should not print session info
        # Should not prompt for input

    def test_get_agent_chat_with_existing_session(self):
        """Test get_agent_chat with existing session (no new session created)."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        self.mock_ctx_manager.exists_session.return_value = True
        
        agent_chat = get_agent_chat(session_id="existing-session")
        
        # Should not create new session
        self.mock_ctx_manager.create_session.assert_not_called()

    def test_get_agent_chat_with_system_prompt_from_env(self):
        """Test get_agent_chat reads system prompt from environment."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        os.environ["SYSTEM_PROMPT"] = "Custom system prompt from env"
        self.mock_file_tool.get_file_content_fuzzy.return_value = (True, "Custom system prompt from env")
        
        agent_chat = get_agent_chat(session_id="test-session")
        
        # Verify file_tool was called to read system prompt
        self.mock_file_tool.get_file_content_fuzzy.assert_called()

    def test_get_agent_chat_max_tokens_enforcement(self):
        """Test get_agent_chat enforces max_tokens minimum of 3000."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        self.mock_agent_instance.llm_model.max_tokens = 1000  # Below minimum
        
        agent_chat = get_agent_chat(session_id="test-session")
        
        # Should be increased to 3000
        self.assertEqual(self.mock_agent_instance.llm_model.max_tokens, 3000)

    def test_get_agent_chat_temperature_enforcement(self):
        """Test get_agent_chat enforces temperature maximum of 0.97."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        self.mock_agent_instance.llm_model.temperature = 1.5  # Above maximum
        
        agent_chat = get_agent_chat(session_id="test-session")
        
        # Should be capped at 0.97
        self.assertEqual(self.mock_agent_instance.llm_model.temperature, 0.97)

    def test_get_agent_chat_with_disabled_tools(self):
        """Test get_agent_chat passes disabled tools to agent."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        disabled = ["tool1", "tool2"]
        agent_chat = get_agent_chat(disabled_tools=disabled, session_id="test-session")
        
        # Verify disabled tools were passed
        call_kwargs = self.mock_agent_run.call_args[1]
        self.assertEqual(call_kwargs['excluded_tool_kits'], disabled)

    def test_get_agent_chat_with_enabled_tools(self):
        """Test get_agent_chat passes enabled tools to agent."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        enabled = ["tool1", "tool2"]
        agent_chat = get_agent_chat(enabled_tools=enabled, session_id="test-session")
        
        # Verify enabled tools were passed
        call_kwargs = self.mock_agent_run.call_args[1]
        self.assertEqual(call_kwargs['tool_kits'], enabled)

    def test_get_agent_chat_with_tool_map(self):
        """Test get_agent_chat passes tool_map to agent."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        tool_map = {"custom_tool": lambda x: x}
        agent_chat = get_agent_chat(tool_map=tool_map, session_id="test-session")
        
        # Verify tool_map was passed
        call_kwargs = self.mock_agent_run.call_args[1]
        self.assertEqual(call_kwargs['tools'], tool_map)

    def test_get_agent_chat_with_to_dump_messages(self):
        """Test get_agent_chat enables message dumping."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        agent_chat = get_agent_chat(to_dump_messages=True, session_id="test-session")
        
        self.assertTrue(self.mock_agent_instance.flag_dump_messages)

    def test_get_agent_chat_need_input_message_false(self):
        """Test get_agent_chat with need_input_message=False."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        self.mock_get_message.return_value = "Input from args"
        
        agent_chat = get_agent_chat(
            need_input_message=False,
            session_id="test-session"
        )
        
        # get_message should be called with need_input=False
        self.mock_get_message.assert_called_with(need_input=False)

    def test_get_agent_chat_message_from_env(self):
        """Test get_agent_chat reads message from TOPSAILAI_TASK env."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        os.environ["TOPSAILAI_TASK"] = "task_from_env"
        self.mock_file_tool.get_file_content_fuzzy.return_value = (True, "task_from_env")
        
        agent_chat = get_agent_chat(session_id="test-session")
        
        # Message should be read from env
        self.assertEqual(agent_chat.first_message, "task_from_env")

    def test_get_agent_chat_combines_messages(self):
        """Test get_agent_chat combines message_from_args with existing message."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        self.mock_get_message.return_value = "Input message"
        
        agent_chat = get_agent_chat(
            message="Existing message",
            need_input_message=False,
            session_id="test-session"
        )
        
        # Messages should be combined
        expected = "Input message\nExisting message"
        self.assertEqual(agent_chat.first_message, expected)

    def test_get_agent_chat_context_runtime_initialized(self):
        """Test get_agent_chat initializes context runtime with ai_agent."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        agent_chat = get_agent_chat(session_id="test-session")
        
        # Verify context runtime was initialized twice
        # First with ai_agent=None, then with actual agent
        self.assertEqual(self.mock_ctx_data_instance.init.call_count, 2)

    def test_get_agent_chat_hooked_instructions_loaded(self):
        """Test get_agent_chat loads hooked instructions."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        agent_chat = get_agent_chat(session_id="test-session")
        
        # Verify hook_instruction loaded instructions
        self.mock_hook_instruction_instance.load_instructions.assert_called_once()

    def test_get_agent_chat_env_session_id_fallback(self):
        """Test get_agent_chat uses env session_id when not provided."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        agent_chat = get_agent_chat()
        
        # Verify env_tool.get_session_id was called
        self.mock_env_tool.get_session_id.assert_called_once()

    def test_get_agent_chat_sets_env_variables(self):
        """Test get_agent_chat sets SESSION_ID and TOPSAILAI_SESSION_ID."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        session_id = "test-session-xyz"
        agent_chat = get_agent_chat(session_id=session_id)
        
        self.assertEqual(os.environ.get("SESSION_ID"), session_id)
        self.assertEqual(os.environ.get("TOPSAILAI_SESSION_ID"), session_id)

    def test_get_agent_chat_clears_task_env_after_read(self):
        """Test get_agent_chat clears TOPSAILAI_TASK after reading."""
        from topsailai.workspace.agent_shell import get_agent_chat
        
        os.environ["TOPSAILAI_TASK"] = "original_task"
        self.mock_file_tool.get_file_content_fuzzy.return_value = (True, "original_task")
        
        agent_chat = get_agent_chat(session_id="test-session")
        
        # TOPSAILAI_TASK should be cleared after reading
        self.assertEqual(os.environ.get("TOPSAILAI_TASK"), "")


if __name__ == '__main__':
    unittest.main()
