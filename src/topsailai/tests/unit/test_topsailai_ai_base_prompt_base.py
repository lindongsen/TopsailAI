"""
Unit tests for ai_base/prompt_base module - PromptBase class.

Test coverage:
- PromptBase class initialization and configuration
- Message management (add_user_message, add_assistant_message, add_tool_message)
- Context history hooks integration
- Session management (new_session, init_prompt)
- Utility methods (dump_messages, load_messages, get_tool_call_id, etc.)

Author: mm-m25
"""

import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock, mock_open


class TestPromptBase(unittest.TestCase):
    """Test cases for PromptBase class."""

    def setUp(self):
        """Set up test fixtures."""
        # Store original env vars
        self.original_env = {}
        for var in ["TOPSAILAI_FLAG_DUMP_MESSAGES", "TOPSAILAI_OBTAIN_SYSTEM_PROMPT_SCRIPT",
                    "TOPSAILAI_OBTAIN_TOOL_PROMPT_SCRIPT"]:
            self.original_env[var] = os.environ.get(var)
            # Clear to avoid interference
            if var in os.environ:
                del os.environ[var]

    def tearDown(self):
        """Restore original environment variables."""
        # Clear module cache to ensure fresh imports
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

        for var, original_value in self.original_env.items():
            if original_value is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = original_value

    # =========================================================================
    # Group A: Initialization Tests
    # =========================================================================

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_init_basic(self, mock_generate_prompt, mock_get_managers):
        """Test basic initialization with system_prompt."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")

        self.assertEqual(pb.system_prompt, "test")
        self.assertEqual(pb.tool_prompt, "")
        self.assertEqual(len(pb.messages), 2)  # system + env
        self.assertEqual(pb.messages[0]["role"], "system")
        self.assertEqual(pb.messages[0]["content"], "test")
        self.assertEqual(pb.messages[1]["role"], "system")
        self.assertEqual(pb.messages[1]["content"], "env_prompt")

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_init_with_tool_prompt(self, mock_generate_prompt, mock_get_managers):
        """Test initialization with tool_prompt."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test", tool_prompt="tool instructions")

        self.assertEqual(pb.tool_prompt, "tool instructions")
        self.assertEqual(len(pb.messages), 3)  # system + env + tool
        self.assertEqual(pb.messages[2]["role"], "system")
        self.assertEqual(pb.messages[2]["content"], "tool instructions")

    def test_init_missing_system_prompt(self):
        """Test assertion error when system_prompt is empty."""
        from topsailai.ai_base.prompt_base import PromptBase

        with self.assertRaises(AssertionError) as context:
            PromptBase(system_prompt="")

        self.assertEqual(str(context.exception), "missing system_prompt")

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_init_with_system_prompt_script(self, mock_generate_prompt, mock_get_managers):
        """Test initialization appends script prompt when env var is set."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        os.environ["TOPSAILAI_OBTAIN_SYSTEM_PROMPT_SCRIPT"] = "/path/to/script.sh"

        with patch("topsailai.ai_base.prompt_base.get_prompt_by_cmd") as mock_cmd:
            mock_cmd.return_value = "script content"
            pb = PromptBase(system_prompt="test")

        self.assertIn("script content", pb.system_prompt)

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_init_hooks_initialized(self, mock_generate_prompt, mock_get_managers):
        """Test that hooks lists are properly initialized."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")

        self.assertEqual(pb.hooks_after_init_prompt, [])
        self.assertEqual(pb.hooks_after_new_session, [])
        self.assertEqual(pb.hooks_pre_chat, [])

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_init_flag_dump_messages(self, mock_generate_prompt, mock_get_managers):
        """Test flag_dump_messages is set based on env var."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        os.environ["TOPSAILAI_FLAG_DUMP_MESSAGES"] = "1"
        pb = PromptBase(system_prompt="test")

        self.assertTrue(pb.flag_dump_messages)

    # =========================================================================
    # Group B: Message Management Tests
    # =========================================================================

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_reset_messages(self, mock_generate_prompt, mock_get_managers):
        """Test reset clears and reinitializes messages."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        pb.add_user_message("user message")  # Add more messages

        pb.reset_messages(to_suppress_log=True)

        self.assertEqual(len(pb.messages), 2)  # Back to system + env
        self.assertEqual(pb.messages[0]["role"], "system")

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    @patch("topsailai.ai_base.prompt_base.print_step")
    def test_add_user_message_string(self, mock_print, mock_generate_prompt, mock_get_managers):
        """Test adding string user message."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        initial_count = len(pb.messages)

        pb.add_user_message("hello")

        self.assertEqual(pb.messages[-1]["role"], "user")
        self.assertEqual(pb.messages[-1]["content"], "hello")
        self.assertEqual(len(pb.messages), initial_count + 1)

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    @patch("topsailai.ai_base.prompt_base.print_step")
    def test_add_user_message_dict(self, mock_print, mock_generate_prompt, mock_get_managers):
        """Test adding dict user message (needs formatting)."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        pb.add_user_message({"key": "value"})

        # Content should be JSON string
        content = pb.messages[-1]["content"]
        parsed = json.loads(content)
        self.assertEqual(parsed, {"key": "value"})

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_add_user_message_none(self, mock_generate_prompt, mock_get_managers):
        """Test adding None user message (should return early)."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        initial_count = len(pb.messages)

        pb.add_user_message(None)

        self.assertEqual(len(pb.messages), initial_count)  # No message added

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    @patch("topsailai.ai_base.prompt_base.print_step")
    def test_add_user_message_no_print(self, mock_print, mock_generate_prompt, mock_get_managers):
        """Test adding user message without printing."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        pb.add_user_message("silent message", need_print=False)

        self.assertEqual(pb.messages[-1]["role"], "user")
        mock_print.assert_not_called()

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    @patch("topsailai.ai_base.prompt_base.print_step")
    def test_add_assistant_message(self, mock_print, mock_generate_prompt, mock_get_managers):
        """Test adding assistant message."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        pb.add_assistant_message("I am an assistant")

        self.assertEqual(pb.messages[-1]["role"], "assistant")
        self.assertEqual(pb.messages[-1]["content"], "I am an assistant")

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    @patch("topsailai.ai_base.prompt_base.print_step")
    def test_add_assistant_message_with_tool_calls(self, mock_print, mock_generate_prompt, mock_get_managers):
        """Test assistant message with tool_calls."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        tool_calls = MagicMock()
        tool_calls.__getitem__ = MagicMock(return_value=MagicMock(id="call_123"))
        tool_calls.__iter__ = MagicMock(return_value=iter([MagicMock(id="call_123")]))

        pb.add_assistant_message("using tool", tool_calls=[tool_calls])

        self.assertEqual(pb.messages[-1]["role"], "assistant")
        self.assertIn("tool_calls", pb.messages[-1])

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    @patch("topsailai.ai_base.prompt_base.print_step")
    def test_add_assistant_message_none(self, mock_print, mock_generate_prompt, mock_get_managers):
        """Test adding None assistant message (should return early)."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        initial_count = len(pb.messages)

        pb.add_assistant_message(None)

        self.assertEqual(len(pb.messages), initial_count)

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    @patch("topsailai.ai_base.prompt_base.print_step")
    def test_add_tool_message_with_tool_call_id(self, mock_print, mock_generate_prompt, mock_get_managers):
        """Test tool message when last message has tool_calls."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")

        # Add assistant message with tool_calls
        tool_call_mock = MagicMock()
        tool_call_mock.id = "call_abc"
        pb.add_assistant_message("using tool", tool_calls=[tool_call_mock])

        # Add tool message
        pb.add_tool_message("tool result")

        self.assertEqual(pb.messages[-1]["role"], "tool")
        self.assertEqual(pb.messages[-1]["tool_call_id"], "call_abc")

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    @patch("topsailai.ai_base.prompt_base.print_step")
    def test_add_tool_message_without_tool_call_id(self, mock_print, mock_generate_prompt, mock_get_managers):
        """Test tool message when no tool_calls (falls back to user role)."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        pb.add_user_message("user message")

        pb.add_tool_message("tool result")

        # Falls back to user role when no tool_call_id
        self.assertEqual(pb.messages[-1]["role"], "user")
        self.assertIsNone(pb.messages[-1]["tool_call_id"])

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    @patch("topsailai.ai_base.prompt_base.print_step")
    def test_add_tool_message_none(self, mock_print, mock_generate_prompt, mock_get_managers):
        """Test adding None tool message (should return early)."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        initial_count = len(pb.messages)

        pb.add_tool_message(None)

        self.assertEqual(len(pb.messages), initial_count)

    # =========================================================================
    # Group C: Hook Tests
    # =========================================================================

    @patch("topsailai.ai_base.prompt_base.logger")
    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_call_hooks_pre_chat(self, mock_generate_prompt, mock_get_managers, mock_logger):
        """Test hooks are called before chatting."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        mock_hook = MagicMock()
        pb.hooks_pre_chat.append(mock_hook)

        pb.call_hooks_pre_chat()

        mock_hook.assert_called_once_with(pb)

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_call_hooks_pre_chat_exception(self, mock_generate_prompt, mock_get_managers):
        """Test hooks_pre_chat handles exceptions gracefully."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")

        def failing_hook(obj):
            raise ValueError("hook failed")

        pb.hooks_pre_chat.append(failing_hook)

        # Should not raise
        pb.call_hooks_pre_chat()

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_call_hooks_ctx_history_no_hooks(self, mock_generate_prompt, mock_get_managers):
        """Test no error when hooks list is empty."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")

        # Should not raise
        pb.call_hooks_ctx_history()

    @patch("topsailai.ai_base.prompt_base.get_session_id")
    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_call_hooks_ctx_history_with_session(self, mock_generate_prompt, mock_get_managers, mock_get_session):
        """Test session message recording."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        mock_hook = MagicMock()
        pb.hooks_ctx_history.append(mock_hook)
        mock_get_session.return_value = "session_123"

        pb.add_user_message("test message")

        mock_hook.add_session_message.assert_called()

    @patch("topsailai.ai_base.prompt_base.count_tokens")
    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_call_hooks_ctx_history_threshold_exceeded(self, mock_generate_prompt, mock_get_managers, mock_count_tokens):
        """Test link_messages called when threshold exceeded."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        mock_hook = MagicMock()
        pb.hooks_ctx_history.append(mock_hook)

        # Mock count_tokens to return high value
        mock_count_tokens.return_value = 1500000

        # Add enough messages to trigger threshold
        for i in range(50):
            pb.add_user_message(f"message {i}")

        mock_hook.link_messages.assert_called()

    # =========================================================================
    # Group D: Session Management Tests
    # =========================================================================

    @patch("topsailai.ai_base.prompt_base.logger")
    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    @patch("topsailai.ai_base.prompt_base.print_step")
    def test_new_session_with_message(self, mock_print, mock_generate_prompt, mock_get_managers, mock_logger):
        """Test new session initializes and adds user message."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        pb.reset_messages = MagicMock()

        pb.new_session("hello world")

        pb.reset_messages.assert_called_once()
        self.assertEqual(pb.messages[-1]["role"], "user")

    @patch("topsailai.ai_base.prompt_base.logger")
    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_new_session_without_message(self, mock_generate_prompt, mock_get_managers, mock_logger):
        """Test new session with None message."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        initial_count = len(pb.messages)

        pb.new_session(None)

        # No user message added
        self.assertEqual(len(pb.messages), initial_count)

    @patch("topsailai.ai_base.prompt_base.logger")
    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_new_session_calls_hooks(self, mock_generate_prompt, mock_get_managers, mock_logger):
        """Test new_session calls after_new_session hooks."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        mock_hook = MagicMock()
        pb.hooks_after_new_session.append(mock_hook)

        pb.new_session("test")

        mock_hook.assert_called_once_with(pb)

    @patch("topsailai.ai_base.prompt_base.logger")
    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_init_prompt(self, mock_generate_prompt, mock_get_managers, mock_logger):
        """Test prompt initialization."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        pb.reset_messages = MagicMock()
        mock_hook = MagicMock()
        pb.hooks_after_init_prompt.append(mock_hook)

        pb.init_prompt()

        pb.reset_messages.assert_called_once()
        mock_hook.assert_called_once_with(pb)

    # =========================================================================
    # Group E: Utility Method Tests
    # =========================================================================

    def test_hook_format_content_dict(self):
        """Test formatting dict content."""
        from topsailai.ai_base.prompt_base import PromptBase

        pb = PromptBase.__new__(PromptBase)

        result = pb.hook_format_content({"key": "value"})

        # JSON with indent=2
        self.assertEqual(result, '{\n  "key": "value"\n}')

    def test_hook_format_content_string(self):
        """Test formatting string content."""
        from topsailai.ai_base.prompt_base import PromptBase

        pb = PromptBase.__new__(PromptBase)

        result = pb.hook_format_content("hello")

        self.assertEqual(result, "hello")

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_update_message_for_env(self, mock_generate_prompt, mock_get_managers):
        """Test updating environment message."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "new_env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        pb.update_message_for_env()

        self.assertEqual(pb.messages[1]["content"], "new_env_prompt")

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_update_message_for_tool(self, mock_generate_prompt, mock_get_managers):
        """Test updating tool message."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test", tool_prompt="old tool")
        pb.update_message_for_tool()

        self.assertEqual(pb.messages[2]["content"], "old tool")

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_get_tool_call_id_with_tool_calls(self, mock_generate_prompt, mock_get_managers):
        """Test getting tool_call_id from last message."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")

        # Add assistant message with tool_calls
        tool_call_mock = MagicMock()
        tool_call_mock.id = "call_xyz"
        pb.add_assistant_message("using tool", tool_calls=[tool_call_mock])

        result = pb.get_tool_call_id()

        self.assertEqual(result, "call_xyz")

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    @patch("topsailai.ai_base.prompt_base.print_step")
    def test_get_tool_call_id_without_tool_calls(self, mock_print, mock_generate_prompt, mock_get_managers):
        """Test getting tool_call_id when none exists."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        pb.add_user_message("hello")

        result = pb.get_tool_call_id()

        self.assertIsNone(result)

    @patch("topsailai.ai_base.prompt_base.time_tool")
    @patch("topsailai.ai_base.prompt_base.get_agent_name")
    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    @patch("topsailai.ai_base.prompt_base.print_step")
    def test_dump_messages(self, mock_print, mock_generate_prompt, mock_get_managers,
                           mock_get_agent, mock_time):
        """Test dumping messages to file."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []
        mock_get_agent.return_value = "test_agent"
        mock_time.get_current_date.return_value = "2025-01-01"

        pb = PromptBase(system_prompt="test")
        pb.add_user_message("test")

        result = pb.dump_messages()

        self.assertIsNotNone(result)
        self.assertTrue(os.path.exists(result))
        self.assertIn("test_agent", result)

        # Cleanup
        if os.path.exists(result):
            os.remove(result)

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_load_messages(self, mock_generate_prompt, mock_get_managers):
        """Test loading messages from file."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")

        # Create temp file
        test_messages = [{"role": "user", "content": "loaded"}]
        temp_file = "/tmp/test_messages.json"
        with open(temp_file, 'w') as f:
            f.write(json.dumps(test_messages))

        pb.load_messages(temp_file)

        self.assertEqual(len(pb.messages), 1)
        self.assertEqual(pb.messages[0]["content"], "loaded")

        # Cleanup
        os.remove(temp_file)

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_get_work_memory_first_position(self, mock_generate_prompt, mock_get_managers):
        """Test finding first non-system message."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")

        # No non-system messages, only system at 0 and 1
        result = pb.get_work_memory_first_position()

        self.assertIsNone(result)

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    @patch("topsailai.ai_base.prompt_base.print_step")
    def test_get_work_memory_first_position_with_user(self, mock_print, mock_generate_prompt, mock_get_managers):
        """Test finding first non-system message after user message added."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        pb.add_user_message("user message")

        result = pb.get_work_memory_first_position()

        self.assertEqual(result, 2)  # Index 2 is the user message

    @patch("topsailai.ai_base.prompt_base.get_managers_by_env")
    @patch("topsailai.ai_base.prompt_base.generate_prompt_for_env")
    def test_append_message(self, mock_generate_prompt, mock_get_managers):
        """Test append_message adds to context."""
        from topsailai.ai_base.prompt_base import PromptBase

        mock_generate_prompt.return_value = "env_prompt"
        mock_get_managers.return_value = []

        pb = PromptBase(system_prompt="test")
        initial_count = len(pb.messages)

        pb.append_message({"role": "user", "content": "test"})

        self.assertEqual(len(pb.messages), initial_count + 1)
        self.assertEqual(pb.messages[-1]["content"], "test")


if __name__ == "__main__":
    unittest.main()
