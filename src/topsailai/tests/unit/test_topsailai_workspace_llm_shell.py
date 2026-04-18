"""
Unit tests for workspace/llm_shell module.

This module tests the LLMChat class and get_llm_chat factory function
for managing chat sessions with Large Language Models.

Author: AI
Created: 2026-04-18
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestLLMChat(unittest.TestCase):
    """Test cases for the LLMChat class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_prompt_ctl = MagicMock()
        self.mock_llm_model = MagicMock()
        self.mock_prompt_ctl.messages = []

    def test_init_with_valid_inputs(self):
        """Test LLMChat initialization with valid prompt_ctl and llm_model."""
        from topsailai.workspace.llm_shell import LLMChat

        chat = LLMChat(self.mock_prompt_ctl, self.mock_llm_model)

        self.assertEqual(chat.prompt_ctl, self.mock_prompt_ctl)
        self.assertEqual(chat.llm_model, self.mock_llm_model)
        self.assertEqual(chat.first_message, "")
        self.assertEqual(chat.last_message, "")

    def test_init_attributes_initialized(self):
        """Test that all attributes are properly initialized."""
        from topsailai.workspace.llm_shell import LLMChat

        chat = LLMChat(self.mock_prompt_ctl, self.mock_llm_model)

        self.assertIsInstance(chat.prompt_ctl, MagicMock)
        self.assertIsInstance(chat.llm_model, MagicMock)
        self.assertEqual(chat.first_message, "")
        self.assertEqual(chat.last_message, "")

    def test_chat_with_message(self):
        """Test chat method with a user message."""
        from topsailai.workspace.llm_shell import LLMChat

        self.mock_llm_model.chat.return_value = "Hello, I am an AI assistant."

        chat = LLMChat(self.mock_prompt_ctl, self.mock_llm_model)
        response = chat.chat(message="Hi, who are you?")

        self.mock_prompt_ctl.add_user_message.assert_called_once_with("Hi, who are you?", need_print=True)
        self.mock_prompt_ctl.update_message_for_env.assert_called_once()
        self.mock_llm_model.chat.assert_called_once()
        self.mock_prompt_ctl.add_assistant_message.assert_called_once_with("Hello, I am an AI assistant.")
        self.assertEqual(chat.last_message, "Hello, I am an AI assistant.")
        self.assertEqual(response, "Hello, I am an AI assistant.")

    def test_chat_with_empty_message(self):
        """Test chat method with empty message (continuing conversation)."""
        from topsailai.workspace.llm_shell import LLMChat

        self.mock_llm_model.chat.return_value = "Continuing conversation."

        chat = LLMChat(self.mock_prompt_ctl, self.mock_llm_model)
        response = chat.chat(message="")

        self.mock_prompt_ctl.add_user_message.assert_not_called()
        self.mock_prompt_ctl.update_message_for_env.assert_called_once()
        self.assertEqual(response, "Continuing conversation.")

    def test_chat_with_need_print_false(self):
        """Test chat method with need_print=False."""
        from topsailai.workspace.llm_shell import LLMChat

        self.mock_llm_model.chat.return_value = "Response"

        chat = LLMChat(self.mock_prompt_ctl, self.mock_llm_model)
        chat.chat(message="Test", need_print=False)

        self.mock_prompt_ctl.add_user_message.assert_called_once_with("Test", need_print=False)

    def test_chat_with_whitespace_response(self):
        """Test chat method with response containing only whitespace."""
        from topsailai.workspace.llm_shell import LLMChat

        self.mock_llm_model.chat.return_value = "   \n\t  "

        chat = LLMChat(self.mock_prompt_ctl, self.mock_llm_model)
        response = chat.chat(message="Test")

        self.assertEqual(response, "")
        self.mock_prompt_ctl.add_assistant_message.assert_called_once_with("")

    def test_chat_with_none_response(self):
        """Test chat method when LLM returns None."""
        from topsailai.workspace.llm_shell import LLMChat

        self.mock_llm_model.chat.return_value = None

        chat = LLMChat(self.mock_prompt_ctl, self.mock_llm_model)
        response = chat.chat(message="Test")

        # When answer is None, if answer: is False, so answer stays None
        self.assertIsNone(response)
        self.mock_prompt_ctl.add_assistant_message.assert_called_once_with(None)

    def test_chat_updates_last_message(self):
        """Test that last_message attribute is updated after chat."""
        from topsailai.workspace.llm_shell import LLMChat

        self.mock_llm_model.chat.return_value = "Test response"

        chat = LLMChat(self.mock_prompt_ctl, self.mock_llm_model)
        self.assertEqual(chat.last_message, "")

        chat.chat(message="Hello")
        self.assertEqual(chat.last_message, "Test response")


class TestGetLLMChat(unittest.TestCase):
    """Test cases for the get_llm_chat factory function."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_session_id = "test-session-123"
        self.test_message = "Hello, AI!"
        self.test_system_prompt = "You are a helpful assistant."

    @patch('topsailai.workspace.input_tool.get_message')
    @patch('topsailai.workspace.llm_shell.LLMModel')
    @patch('topsailai.workspace.llm_shell.PromptBase')
    @patch('topsailai.workspace.llm_shell.file_tool')
    @patch('topsailai.workspace.llm_shell.env_tool')
    @patch('topsailai.workspace.llm_shell.ctx_manager')
    @patch('topsailai.workspace.llm_shell.set_thread_var')
    @patch('topsailai.workspace.llm_shell.set_thread_name')
    def test_get_llm_chat_with_message_and_session(
        self, mock_set_thread_name, mock_set_thread_var, mock_ctx, mock_env_tool, 
        mock_file_tool, mock_prompt_base, mock_llm_model_class, mock_get_message
    ):
        """Test get_llm_chat with explicit message and session_id."""
        from topsailai.workspace.llm_shell import get_llm_chat

        mock_get_message.return_value = "User input"
        mock_env_tool.get_session_id.return_value = self.test_session_id
        mock_file_tool.get_file_content_fuzzy.return_value = (True, self.test_system_prompt)

        # Create a mock LLMModel with proper numeric attributes
        mock_llm_instance = MagicMock()
        mock_llm_instance.max_tokens = 4096
        mock_llm_instance.temperature = 0.8
        mock_llm_instance.content_senders = []
        mock_llm_model_class.return_value = mock_llm_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.messages = []
        mock_prompt_base.return_value = mock_prompt_instance

        mock_ctx.get_messages_by_session.return_value = []
        mock_ctx.create_session.return_value = None

        chat = get_llm_chat(
            message=self.test_message,
            session_id=self.test_session_id,
            system_prompt="",
            need_input_message=False,
            need_print_session=False
        )

        self.assertIsNotNone(chat)
        self.assertEqual(chat.first_message, self.test_message)
        mock_prompt_instance.new_session.assert_called_once()

    @patch('topsailai.workspace.input_tool.get_message')
    @patch('topsailai.workspace.llm_shell.LLMModel')
    @patch('topsailai.workspace.llm_shell.PromptBase')
    @patch('topsailai.workspace.llm_shell.file_tool')
    @patch('topsailai.workspace.llm_shell.env_tool')
    @patch('topsailai.workspace.llm_shell.ctx_manager')
    @patch('topsailai.workspace.llm_shell.set_thread_var')
    @patch('topsailai.workspace.llm_shell.set_thread_name')
    def test_get_llm_chat_without_session_id(
        self, mock_set_thread_name, mock_set_thread_var, mock_ctx, mock_env_tool,
        mock_file_tool, mock_prompt_base, mock_llm_model_class, mock_get_message
    ):
        """Test get_llm_chat when session_id is None (gets from env)."""
        from topsailai.workspace.llm_shell import get_llm_chat

        mock_get_message.return_value = "User input"
        mock_env_tool.get_session_id.return_value = self.test_session_id
        mock_file_tool.get_file_content_fuzzy.return_value = (True, self.test_system_prompt)

        mock_llm_instance = MagicMock()
        mock_llm_instance.max_tokens = 4096
        mock_llm_instance.temperature = 0.8
        mock_llm_instance.content_senders = []
        mock_llm_model_class.return_value = mock_llm_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.messages = []
        mock_prompt_base.return_value = mock_prompt_instance

        mock_ctx.get_messages_by_session.return_value = []
        mock_ctx.create_session.return_value = None

        chat = get_llm_chat(
            message=self.test_message,
            session_id=None,
            need_input_message=False,
            need_print_session=False
        )

        mock_env_tool.get_session_id.assert_called_once()

    @patch('topsailai.workspace.input_tool.get_message')
    @patch('topsailai.workspace.llm_shell.LLMModel')
    @patch('topsailai.workspace.llm_shell.PromptBase')
    @patch('topsailai.workspace.llm_shell.file_tool')
    def test_get_llm_chat_with_empty_session_id(
        self, mock_file_tool, mock_prompt_base, mock_llm_model_class, mock_get_message
    ):
        """Test get_llm_chat with empty session_id (no session management)."""
        from topsailai.workspace.llm_shell import get_llm_chat

        mock_get_message.return_value = "User input"
        mock_file_tool.get_file_content_fuzzy.return_value = (True, self.test_system_prompt)

        mock_llm_instance = MagicMock()
        mock_llm_instance.max_tokens = 4096
        mock_llm_instance.temperature = 0.8
        mock_llm_instance.content_senders = []
        mock_llm_model_class.return_value = mock_llm_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.messages = []
        mock_prompt_base.return_value = mock_prompt_instance

        chat = get_llm_chat(
            message=self.test_message,
            session_id="",
            need_input_message=False
        )

        self.assertIsNotNone(chat)
        mock_prompt_instance.new_session.assert_called_once()

    @patch('topsailai.workspace.input_tool.get_message')
    @patch('topsailai.workspace.llm_shell.LLMModel')
    @patch('topsailai.workspace.llm_shell.PromptBase')
    @patch('topsailai.workspace.llm_shell.file_tool')
    @patch('topsailai.workspace.llm_shell.env_tool')
    @patch('topsailai.workspace.llm_shell.ctx_manager')
    @patch('topsailai.workspace.llm_shell.set_thread_var')
    @patch('topsailai.workspace.llm_shell.set_thread_name')
    def test_get_llm_chat_with_existing_session(
        self, mock_set_thread_name, mock_set_thread_var, mock_ctx, mock_env_tool,
        mock_file_tool, mock_prompt_base, mock_llm_model_class, mock_get_message
    ):
        """Test get_llm_chat with existing session messages."""
        from topsailai.workspace.llm_shell import get_llm_chat

        mock_get_message.return_value = "New message"
        mock_env_tool.get_session_id.return_value = self.test_session_id
        mock_file_tool.get_file_content_fuzzy.return_value = (True, self.test_system_prompt)

        existing_messages = [
            {"role": "user", "content": "Previous message"},
            {"role": "assistant", "content": "Previous response"}
        ]

        mock_llm_instance = MagicMock()
        mock_llm_instance.max_tokens = 4096
        mock_llm_instance.temperature = 0.8
        mock_llm_instance.content_senders = []
        mock_llm_model_class.return_value = mock_llm_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.messages = []
        mock_prompt_base.return_value = mock_prompt_instance

        mock_ctx.get_messages_by_session.return_value = existing_messages

        chat = get_llm_chat(
            message=self.test_message,
            session_id=self.test_session_id,
            need_input_message=False,
            need_print_session=False
        )

        mock_prompt_instance.new_session.assert_not_called()
        self.assertEqual(mock_prompt_instance.messages, existing_messages)

    @patch('topsailai.workspace.input_tool.get_message')
    @patch('topsailai.workspace.llm_shell.LLMModel')
    @patch('topsailai.workspace.llm_shell.PromptBase')
    @patch('topsailai.workspace.llm_shell.file_tool')
    @patch('topsailai.workspace.llm_shell.env_tool')
    @patch('topsailai.workspace.llm_shell.ctx_manager')
    @patch('topsailai.workspace.llm_shell.set_thread_var')
    @patch('topsailai.workspace.llm_shell.set_thread_name')
    def test_get_llm_chat_with_system_prompt_from_env(
        self, mock_set_thread_name, mock_set_thread_var, mock_ctx, mock_env_tool,
        mock_file_tool, mock_prompt_base, mock_llm_model_class, mock_get_message
    ):
        """Test get_llm_chat gets system prompt from environment variable."""
        from topsailai.workspace.llm_shell import get_llm_chat

        mock_get_message.return_value = "User input"
        mock_env_tool.get_session_id.return_value = self.test_session_id

        mock_file_tool.get_file_content_fuzzy.return_value = (True, "Environment system prompt")

        mock_llm_instance = MagicMock()
        mock_llm_instance.max_tokens = 4096
        mock_llm_instance.temperature = 0.8
        mock_llm_instance.content_senders = []
        mock_llm_model_class.return_value = mock_llm_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.messages = []
        mock_prompt_base.return_value = mock_prompt_instance

        mock_ctx.get_messages_by_session.return_value = []
        mock_ctx.create_session.return_value = None

        with patch.dict(os.environ, {"SYSTEM_PROMPT": "env_prompt_path"}):
            chat = get_llm_chat(
                message=self.test_message,
                session_id=self.test_session_id,
                system_prompt="",
                need_input_message=False,
                need_print_session=False
            )

        mock_prompt_base.assert_called_once()

    @patch('topsailai.workspace.input_tool.get_message')
    @patch('topsailai.workspace.llm_shell.LLMModel')
    @patch('topsailai.workspace.llm_shell.PromptBase')
    @patch('topsailai.workspace.llm_shell.file_tool')
    @patch('topsailai.workspace.llm_shell.env_tool')
    @patch('topsailai.workspace.llm_shell.ctx_manager')
    @patch('topsailai.workspace.llm_shell.set_thread_var')
    @patch('topsailai.workspace.llm_shell.set_thread_name')
    def test_get_llm_chat_with_more_prompt(
        self, mock_set_thread_name, mock_set_thread_var, mock_ctx, mock_env_tool,
        mock_file_tool, mock_prompt_base, mock_llm_model_class, mock_get_message
    ):
        """Test get_llm_chat appends more_prompt to system prompt."""
        from topsailai.workspace.llm_shell import get_llm_chat

        mock_get_message.return_value = "User input"
        mock_env_tool.get_session_id.return_value = self.test_session_id

        def file_content_side_effect(path):
            if "system" in path.lower():
                return (True, "Base system prompt")
            elif "more" in path.lower():
                return (True, "\n\nAdditional instructions")
            return (True, "")

        mock_file_tool.get_file_content_fuzzy.side_effect = file_content_side_effect

        mock_llm_instance = MagicMock()
        mock_llm_instance.max_tokens = 4096
        mock_llm_instance.temperature = 0.8
        mock_llm_instance.content_senders = []
        mock_llm_model_class.return_value = mock_llm_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.messages = []
        mock_prompt_base.return_value = mock_prompt_instance

        mock_ctx.get_messages_by_session.return_value = []
        mock_ctx.create_session.return_value = None

        chat = get_llm_chat(
            message=self.test_message,
            session_id=self.test_session_id,
            system_prompt="system_prompt",
            more_prompt="more_prompt",
            need_input_message=False,
            need_print_session=False
        )

        # Verify more_prompt was appended
        call_args = mock_prompt_base.call_args[0][0]
        self.assertIn("Base system prompt", call_args)
        self.assertIn("Additional instructions", call_args)

    @patch('topsailai.workspace.input_tool.get_message')
    @patch('topsailai.workspace.llm_shell.LLMModel')
    @patch('topsailai.workspace.llm_shell.PromptBase')
    @patch('topsailai.workspace.llm_shell.file_tool')
    @patch('topsailai.workspace.llm_shell.env_tool')
    @patch('topsailai.workspace.llm_shell.ctx_manager')
    @patch('topsailai.workspace.llm_shell.set_thread_var')
    @patch('topsailai.workspace.llm_shell.set_thread_name')
    @patch('topsailai.workspace.llm_shell.ContentStdout')
    def test_get_llm_chat_with_need_stdout_true(
        self, mock_content_stdout, mock_set_thread_name, mock_set_thread_var, mock_ctx,
        mock_env_tool, mock_file_tool, mock_prompt_base, mock_llm_model_class, mock_get_message
    ):
        """Test get_llm_chat adds ContentStdout when need_stdout=True."""
        from topsailai.workspace.llm_shell import get_llm_chat

        mock_get_message.return_value = "User input"
        mock_env_tool.get_session_id.return_value = self.test_session_id
        mock_file_tool.get_file_content_fuzzy.return_value = (True, self.test_system_prompt)

        mock_llm_instance = MagicMock()
        mock_llm_instance.max_tokens = 4096
        mock_llm_instance.temperature = 0.8
        mock_llm_instance.content_senders = []
        mock_llm_model_class.return_value = mock_llm_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.messages = []
        mock_prompt_base.return_value = mock_prompt_instance

        mock_ctx.get_messages_by_session.return_value = []
        mock_ctx.create_session.return_value = None

        mock_content_stdout_instance = MagicMock()
        mock_content_stdout.return_value = mock_content_stdout_instance

        chat = get_llm_chat(
            message=self.test_message,
            session_id=self.test_session_id,
            need_stdout=True,
            need_input_message=False,
            need_print_session=False
        )

        self.assertEqual(len(mock_llm_instance.content_senders), 1)

    @patch('topsailai.workspace.input_tool.get_message')
    @patch('topsailai.workspace.llm_shell.LLMModel')
    @patch('topsailai.workspace.llm_shell.PromptBase')
    @patch('topsailai.workspace.llm_shell.file_tool')
    @patch('topsailai.workspace.llm_shell.env_tool')
    @patch('topsailai.workspace.llm_shell.ctx_manager')
    @patch('topsailai.workspace.llm_shell.set_thread_var')
    @patch('topsailai.workspace.llm_shell.set_thread_name')
    def test_get_llm_chat_max_tokens_enforced(
        self, mock_set_thread_name, mock_set_thread_var, mock_ctx, mock_env_tool,
        mock_file_tool, mock_prompt_base, mock_llm_model_class, mock_get_message
    ):
        """Test get_llm_chat enforces minimum max_tokens of 3000."""
        from topsailai.workspace.llm_shell import get_llm_chat

        mock_get_message.return_value = "User input"
        mock_env_tool.get_session_id.return_value = self.test_session_id
        mock_file_tool.get_file_content_fuzzy.return_value = (True, self.test_system_prompt)

        mock_llm_instance = MagicMock()
        mock_llm_instance.max_tokens = 2000  # Lower than minimum
        mock_llm_instance.temperature = 0.8
        mock_llm_instance.content_senders = []
        mock_llm_model_class.return_value = mock_llm_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.messages = []
        mock_prompt_base.return_value = mock_prompt_instance

        mock_ctx.get_messages_by_session.return_value = []
        mock_ctx.create_session.return_value = None

        chat = get_llm_chat(
            message=self.test_message,
            session_id=self.test_session_id,
            max_tokens=2000,  # Requesting 2000
            need_input_message=False,
            need_print_session=False
        )

        # Should be set to max(3000, 2000, 2000) = 3000
        self.assertEqual(mock_llm_instance.max_tokens, 3000)

    @patch('topsailai.workspace.input_tool.get_message')
    @patch('topsailai.workspace.llm_shell.LLMModel')
    @patch('topsailai.workspace.llm_shell.PromptBase')
    @patch('topsailai.workspace.llm_shell.file_tool')
    @patch('topsailai.workspace.llm_shell.env_tool')
    @patch('topsailai.workspace.llm_shell.ctx_manager')
    @patch('topsailai.workspace.llm_shell.set_thread_var')
    @patch('topsailai.workspace.llm_shell.set_thread_name')
    def test_get_llm_chat_temperature_enforced(
        self, mock_set_thread_name, mock_set_thread_var, mock_ctx, mock_env_tool,
        mock_file_tool, mock_prompt_base, mock_llm_model_class, mock_get_message
    ):
        """Test get_llm_chat enforces minimum temperature of 0.97."""
        from topsailai.workspace.llm_shell import get_llm_chat

        mock_get_message.return_value = "User input"
        mock_env_tool.get_session_id.return_value = self.test_session_id
        mock_file_tool.get_file_content_fuzzy.return_value = (True, self.test_system_prompt)

        mock_llm_instance = MagicMock()
        mock_llm_instance.max_tokens = 4096
        mock_llm_instance.temperature = 0.5  # Lower than minimum
        mock_llm_instance.content_senders = []
        mock_llm_model_class.return_value = mock_llm_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.messages = []
        mock_prompt_base.return_value = mock_prompt_instance

        mock_ctx.get_messages_by_session.return_value = []
        mock_ctx.create_session.return_value = None

        chat = get_llm_chat(
            message=self.test_message,
            session_id=self.test_session_id,
            temperature=0.5,  # Requesting 0.5
            need_input_message=False,
            need_print_session=False
        )

        # Should be set to max(0.97, 0.5, 0.5) = 0.97
        self.assertEqual(mock_llm_instance.temperature, 0.97)

    @patch('topsailai.workspace.input_tool.get_message')
    @patch('topsailai.workspace.llm_shell.LLMModel')
    @patch('topsailai.workspace.llm_shell.PromptBase')
    @patch('topsailai.workspace.llm_shell.file_tool')
    @patch('topsailai.workspace.llm_shell.env_tool')
    @patch('topsailai.workspace.llm_shell.ctx_manager')
    @patch('topsailai.workspace.llm_shell.set_thread_var')
    @patch('topsailai.workspace.llm_shell.set_thread_name')
    def test_get_llm_chat_func_formatter_messages(
        self, mock_set_thread_name, mock_set_thread_var, mock_ctx, mock_env_tool,
        mock_file_tool, mock_prompt_base, mock_llm_model_class, mock_get_message
    ):
        """Test get_llm_chat uses func_formatter_messages when provided."""
        from topsailai.workspace.llm_shell import get_llm_chat

        mock_get_message.return_value = "New message"
        mock_env_tool.get_session_id.return_value = self.test_session_id
        mock_file_tool.get_file_content_fuzzy.return_value = (True, self.test_system_prompt)

        existing_messages = [{"role": "user", "content": "Old message"}]
        formatted_messages = [{"role": "user", "content": "Formatted: Old message"}]

        mock_formatter = MagicMock(return_value=formatted_messages)

        mock_llm_instance = MagicMock()
        mock_llm_instance.max_tokens = 4096
        mock_llm_instance.temperature = 0.8
        mock_llm_instance.content_senders = []
        mock_llm_model_class.return_value = mock_llm_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.messages = []
        mock_prompt_base.return_value = mock_prompt_instance

        mock_ctx.get_messages_by_session.return_value = existing_messages

        chat = get_llm_chat(
            message=self.test_message,
            session_id=self.test_session_id,
            func_formatter_messages=mock_formatter,
            need_input_message=False,
            need_print_session=False
        )

        mock_formatter.assert_called_once_with(existing_messages)
        self.assertEqual(mock_prompt_instance.messages, formatted_messages)

    @patch('topsailai.workspace.input_tool.get_message')
    @patch('topsailai.workspace.llm_shell.LLMModel')
    @patch('topsailai.workspace.llm_shell.PromptBase')
    @patch('topsailai.workspace.llm_shell.file_tool')
    @patch('topsailai.workspace.llm_shell.env_tool')
    @patch('topsailai.workspace.llm_shell.ctx_manager')
    @patch('topsailai.workspace.llm_shell.set_thread_var')
    @patch('topsailai.workspace.llm_shell.set_thread_name')
    def test_get_llm_chat_default_system_prompt(
        self, mock_set_thread_name, mock_set_thread_var, mock_ctx, mock_env_tool,
        mock_file_tool, mock_prompt_base, mock_llm_model_class, mock_get_message
    ):
        """Test get_llm_chat uses default system prompt when none provided."""
        from topsailai.workspace.llm_shell import get_llm_chat

        mock_get_message.return_value = "User input"
        mock_env_tool.get_session_id.return_value = self.test_session_id
        mock_file_tool.get_file_content_fuzzy.return_value = (False, "")  # No file found

        mock_llm_instance = MagicMock()
        mock_llm_instance.max_tokens = 4096
        mock_llm_instance.temperature = 0.8
        mock_llm_instance.content_senders = []
        mock_llm_model_class.return_value = mock_llm_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.messages = []
        mock_prompt_base.return_value = mock_prompt_instance

        mock_ctx.get_messages_by_session.return_value = []
        mock_ctx.create_session.return_value = None

        chat = get_llm_chat(
            message=self.test_message,
            session_id=self.test_session_id,
            system_prompt="",
            need_input_message=False,
            need_print_session=False
        )

        # Should use default "You are a helpful assistant."
        mock_prompt_base.assert_called_once_with("You are a helpful assistant.")


if __name__ == '__main__':
    unittest.main()
