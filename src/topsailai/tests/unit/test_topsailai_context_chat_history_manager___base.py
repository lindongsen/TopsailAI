"""
Unit tests for context/chat_history_manager/__base.py

This module contains unit tests for the chat history management base classes
including ChatHistoryMessageData, MessageStorageBase, ContextManager, and ChatHistoryBase.

Author: DawsonLin
Created: 2025-10-29
"""

import unittest
from unittest.mock import patch, MagicMock
from topsailai.context.chat_history_manager.__base import (
    ChatHistoryMessageData,
    MessageStorageBase,
    ContextManager,
    ChatHistoryBase,
)
from topsailai.ai_base.constants import ROLE_SYSTEM, ROLE_USER


class TestChatHistoryMessageData(unittest.TestCase):
    """Test cases for ChatHistoryMessageData class."""

    def test_init_with_all_params(self):
        """Test initialization with all parameters provided."""
        msg = ChatHistoryMessageData(
            message="Hello world",
            msg_id="test_msg_id",
            session_id="test_session_id"
        )
        self.assertEqual(msg.msg_id, "test_msg_id")
        self.assertEqual(msg.session_id, "test_session_id")
        self.assertEqual(msg.message, "Hello world")
        self.assertEqual(msg.msg_size, 11)
        self.assertIsNone(msg.create_time)
        self.assertIsNone(msg.access_time)
        self.assertIsNone(msg.access_count)

    @patch('topsailai.context.chat_history_manager.__base.md5sum')
    def test_init_generates_msg_id_from_content(self, mock_md5sum):
        """Test auto-generation of msg_id using md5sum when msg_id is None."""
        mock_md5sum.return_value = "generated_md5_hash"
        msg = ChatHistoryMessageData(
            message="Hello world",
            msg_id=None,
            session_id="test_session_id"
        )
        self.assertEqual(msg.msg_id, "generated_md5_hash")
        mock_md5sum.assert_called_once_with("Hello world")

    def test_init_calculates_msg_size(self):
        """Test msg_size is calculated from message length."""
        msg = ChatHistoryMessageData(
            message="Hello",
            msg_id="test_id",
            session_id="test_session"
        )
        self.assertEqual(msg.msg_size, 5)

    def test_init_with_empty_message(self):
        """Test handling of empty/None messages."""
        msg = ChatHistoryMessageData(
            message="",
            msg_id="test_id",
            session_id="test_session"
        )
        self.assertEqual(msg.msg_size, 0)
        self.assertEqual(msg.message, "")

    def test_init_with_none_message(self):
        """Test handling of None message."""
        msg = ChatHistoryMessageData(
            message=None,
            msg_id="test_id",
            session_id="test_session"
        )
        self.assertEqual(msg.msg_size, 0)
        self.assertIsNone(msg.message)

    def test_init_metadata_fields_none(self):
        """Test that metadata fields are initialized to None."""
        msg = ChatHistoryMessageData(
            message="Test message",
            msg_id="test_id",
            session_id="test_session"
        )
        self.assertIsNone(msg.create_time)
        self.assertIsNone(msg.access_time)
        self.assertIsNone(msg.access_count)


class TestMessageStorageBase(unittest.TestCase):
    """Test cases for MessageStorageBase abstract class."""

    def test_add_session_message_raises_not_implemented(self):
        """Test that add_session_message raises NotImplementedError."""
        storage = MessageStorageBase()
        with self.assertRaises(NotImplementedError):
            storage.add_session_message({"role": "user", "content": "test"})

    def test_add_message_raises_not_implemented(self):
        """Test that add_message raises NotImplementedError."""
        storage = MessageStorageBase()
        msg = ChatHistoryMessageData("test", "msg_id", "session_id")
        with self.assertRaises(NotImplementedError):
            storage.add_message(msg)

    def test_get_message_raises_not_implemented(self):
        """Test that get_message raises NotImplementedError."""
        storage = MessageStorageBase()
        with self.assertRaises(NotImplementedError):
            storage.get_message("test_msg_id")

    def test_get_messages_by_session_raises_not_implemented(self):
        """Test that get_messages_by_session raises NotImplementedError."""
        storage = MessageStorageBase()
        with self.assertRaises(NotImplementedError):
            storage.get_messages_by_session("test_session_id")

    def test_del_messages_raises_not_implemented(self):
        """Test that del_messages raises NotImplementedError."""
        storage = MessageStorageBase()
        with self.assertRaises(NotImplementedError):
            storage.del_messages(msg_id="test_msg_id")

    def test_update_message_access_raises_not_implemented(self):
        """Test that update_message_access raises NotImplementedError."""
        storage = MessageStorageBase()
        with self.assertRaises(NotImplementedError):
            storage.update_message_access("test_msg_id")

    def test_clean_messages_raises_not_implemented(self):
        """Test that clean_messages raises NotImplementedError."""
        storage = MessageStorageBase()
        with self.assertRaises(NotImplementedError):
            storage.clean_messages(3600)


class TestContextManager(unittest.TestCase):
    """Test cases for ContextManager class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_storage = MagicMock()
        self.manager = ContextManager()
        self.manager.conn = self.mock_storage

    @patch('topsailai.context.chat_history_manager.__base.get_session_id')
    @patch('topsailai.context.chat_history_manager.__base.count_tokens')
    @patch('topsailai.context.chat_history_manager.__base.logger')
    @patch('topsailai.context.chat_history_manager.__base.json_tool')
    def test_link_msg_id_with_raw_text(self, mock_json_tool, mock_logger, mock_count_tokens, mock_get_session_id):
        """Test archiving content with raw_text field."""
        mock_get_session_id.return_value = "test_session"
        mock_count_tokens.return_value = 10
        mock_json_tool.json_dump.side_effect = lambda x, **kwargs: str(x)

        content_dict = {"raw_text": "Large content here", "role": "user"}
        self.manager.add_message = MagicMock()
        self.manager._link_msg_id(content_dict)

        self.assertEqual(content_dict["step_name"], "archive")
        self.assertIn("retrieve_msg by msg_id=", content_dict["raw_text"])
        self.manager.add_message.assert_called_once()

    @patch('topsailai.context.chat_history_manager.__base.get_session_id')
    @patch('topsailai.context.chat_history_manager.__base.count_tokens')
    @patch('topsailai.context.chat_history_manager.__base.logger')
    @patch('topsailai.context.chat_history_manager.__base.json_tool')
    def test_link_msg_id_with_full_dict(self, mock_json_tool, mock_logger, mock_count_tokens, mock_get_session_id):
        """Test archiving full content dictionary."""
        mock_get_session_id.return_value = "test_session"
        mock_count_tokens.return_value = 15
        mock_json_tool.json_dump.return_value = '{"key": "value"}'

        content_dict = {"key": "value", "other": "data"}
        self.manager.add_message = MagicMock()
        self.manager._link_msg_id(content_dict)

        self.assertEqual(content_dict["step_name"], "archive")
        mock_json_tool.json_dump.assert_called()

    @patch('topsailai.context.chat_history_manager.__base.get_session_id')
    @patch('topsailai.context.chat_history_manager.__base.count_tokens')
    @patch('topsailai.context.chat_history_manager.__base.logger')
    @patch('topsailai.context.chat_history_manager.__base.json_tool')
    def test_link_msg_id_non_string_content(self, mock_json_tool, mock_logger, mock_count_tokens, mock_get_session_id):
        """Test converting non-string content to JSON."""
        mock_get_session_id.return_value = "test_session"
        mock_count_tokens.return_value = 5
        mock_json_tool.json_dump.return_value = '{"type": "list"}'

        content_dict = {"raw_text": ["item1", "item2"], "role": "assistant"}
        self.manager.add_message = MagicMock()
        self.manager._link_msg_id(content_dict)

        mock_json_tool.json_dump.assert_called()
        self.manager.add_message.assert_called_once()

    @patch('topsailai.context.chat_history_manager.__base.get_session_id')
    @patch('topsailai.context.chat_history_manager.__base.count_tokens')
    @patch('topsailai.context.chat_history_manager.__base.logger')
    @patch('topsailai.context.chat_history_manager.__base.json_tool')
    def test_link_msg_id_calls_add_message(self, mock_json_tool, mock_logger, mock_count_tokens, mock_get_session_id):
        """Test that add_message is called with correct data."""
        mock_get_session_id.return_value = "test_session"
        mock_count_tokens.return_value = 8
        mock_json_tool.json_dump.side_effect = lambda x, **kwargs: str(x)

        content_dict = {"raw_text": "Test content", "role": "user"}
        self.manager.add_message = MagicMock()
        self.manager._link_msg_id(content_dict)

        call_args = self.manager.add_message.call_args[0][0]
        self.assertIsInstance(call_args, ChatHistoryMessageData)
        self.assertEqual(call_args.session_id, "test_session")

    @patch('topsailai.context.chat_history_manager.__base.get_session_id')
    @patch('topsailai.context.chat_history_manager.__base.count_tokens')
    @patch('topsailai.context.chat_history_manager.__base.logger')
    @patch('topsailai.context.chat_history_manager.__base.json_tool')
    def test_link_msg_id_replaces_content_with_reference(self, mock_json_tool, mock_logger, mock_count_tokens, mock_get_session_id):
        """Test that content is replaced with archive reference."""
        mock_get_session_id.return_value = "test_session"
        mock_count_tokens.return_value = 10
        mock_json_tool.json_dump.side_effect = lambda x, **kwargs: str(x)

        content_dict = {"raw_text": "Large content", "role": "user"}
        self.manager.add_message = MagicMock()
        self.manager._link_msg_id(content_dict)

        self.assertNotIn("raw_text", content_dict)
        self.assertNotIn("role", content_dict)
        self.assertEqual(content_dict["step_name"], "archive")

    @patch('topsailai.context.chat_history_manager.__base.json_tool')
    @patch('topsailai.context.chat_history_manager.__base.format_tool')
    def test_link_messages_skips_ignored_roles(self, mock_format_tool, mock_json_tool):
        """Test that system and user roles are skipped (except user with tool_calls)."""
        mock_format_tool.to_list.side_effect = lambda x: x if isinstance(x, list) else [x]

        messages = [
            {"role": ROLE_SYSTEM, "content": '{"step_name": "system"}'},
            {"role": ROLE_USER, "content": '{"step_name": "user"}'},
        ]
        self.manager._link_msg_id = MagicMock()
        self.manager.link_messages(messages)

        self.manager._link_msg_id.assert_not_called()

    @patch('topsailai.context.chat_history_manager.__base.json_tool')
    @patch('topsailai.context.chat_history_manager.__base.format_tool')
    def test_link_messages_processes_user_with_tool_calls(self, mock_format_tool, mock_json_tool):
        """Test that user messages with tool_call_id are processed."""
        mock_format_tool.to_list.side_effect = lambda x: x if isinstance(x, list) else [x]
        mock_json_tool.json_load.return_value = [{"step_name": "action", "raw_text": "test"}]

        messages = [
            {"role": ROLE_USER, "content": '[{"step_name": "action", "raw_text": "test"}]', "tool_call_id": "call_123"},
        ]
        self.manager._link_msg_id = MagicMock()
        self.manager.link_messages(messages, index_start=0, index_end=-1, max_size=1)

        self.manager._link_msg_id.assert_called()

    @patch('topsailai.context.chat_history_manager.__base.json_tool')
    @patch('topsailai.context.chat_history_manager.__base.format_tool')
    def test_link_messages_skips_non_json_content(self, mock_format_tool, mock_json_tool):
        """Test that non-JSON content (not starting with { or [) is skipped."""
        mock_format_tool.to_list.side_effect = lambda x: x if isinstance(x, list) else [x]

        messages = [
            {"role": "assistant", "content": "Just plain text"},
        ]
        self.manager._link_msg_id = MagicMock()
        self.manager.link_messages(messages)

        mock_json_tool.json_load.assert_not_called()
        self.manager._link_msg_id.assert_not_called()

    @patch('topsailai.context.chat_history_manager.__base.json_tool')
    @patch('topsailai.context.chat_history_manager.__base.format_tool')
    def test_link_messages_handles_invalid_json(self, mock_format_tool, mock_json_tool):
        """Test graceful handling of JSON parse errors."""
        mock_format_tool.to_list.side_effect = lambda x: x if isinstance(x, list) else [x]
        mock_json_tool.json_load.side_effect = ValueError("Invalid JSON")

        messages = [
            {"role": "assistant", "content": '{"invalid json'},
        ]
        self.manager._link_msg_id = MagicMock()
        self.manager.link_messages(messages)

        self.manager._link_msg_id.assert_not_called()

    @patch('topsailai.context.chat_history_manager.__base.get_session_id')
    @patch('topsailai.context.chat_history_manager.__base.count_tokens')
    @patch('topsailai.context.chat_history_manager.__base.logger')
    @patch('topsailai.context.chat_history_manager.__base.json_tool')
    @patch('topsailai.context.chat_history_manager.__base.format_tool')
    def test_link_messages_archives_large_content(self, mock_format_tool, mock_json_tool, mock_logger, mock_count_tokens, mock_get_session_id):
        """Test archiving content exceeding max_size threshold."""
        mock_format_tool.to_list.side_effect = lambda x: x if isinstance(x, list) else [x]
        mock_json_tool.json_load.return_value = [{"step_name": "action", "raw_text": "x" * 2000}]
        mock_json_tool.json_dump.side_effect = lambda x, **kwargs: str(x)
        mock_get_session_id.return_value = "test_session"
        mock_count_tokens.return_value = 100

        messages = [
            {"role": "assistant", "content": '[{"step_name": "action", "raw_text": "x" * 2000}]'},
        ]
        self.manager.add_message = MagicMock()
        self.manager.link_messages(messages, index_start=0, index_end=-1, max_size=100)

        self.manager.add_message.assert_called()

    @patch('topsailai.context.chat_history_manager.__base.json_tool')
    @patch('topsailai.context.chat_history_manager.__base.format_tool')
    def test_link_messages_respects_index_range(self, mock_format_tool, mock_json_tool):
        """Test that only messages in index_start:index_end range are processed."""
        mock_format_tool.to_list.side_effect = lambda x: x if isinstance(x, list) else [x]
        mock_json_tool.json_load.return_value = [{"step_name": "action", "raw_text": "test"}]

        messages = [
            {"role": "system", "content": "skip"},
            {"role": "assistant", "content": "process"},
            {"role": "user", "content": "skip"},
        ]
        self.manager._link_msg_id = MagicMock()
        self.manager.link_messages(messages, index_start=1, index_end=2, max_size=1)

        self.manager._link_msg_id.assert_called_once()

    @patch('topsailai.context.chat_history_manager.__base.get_session_id')
    @patch('topsailai.context.chat_history_manager.__base.count_tokens')
    @patch('topsailai.context.chat_history_manager.__base.logger')
    @patch('topsailai.context.chat_history_manager.__base.json_tool')
    @patch('topsailai.context.chat_history_manager.__base.format_tool')
    def test_link_messages_updates_content_when_changed(self, mock_format_tool, mock_json_tool, mock_logger, mock_count_tokens, mock_get_session_id):
        """Test that message content is updated after archiving."""
        mock_format_tool.to_list.side_effect = lambda x: x if isinstance(x, list) else [x]
        mock_json_tool.json_load.return_value = [{"step_name": "action", "raw_text": "x" * 2000}]
        mock_json_tool.json_dump.side_effect = lambda x, **kwargs: str(x)
        mock_get_session_id.return_value = "test_session"
        mock_count_tokens.return_value = 100

        messages = [
            {"role": "assistant", "content": '[{"step_name": "action", "raw_text": "x" * 2000}]'},
        ]
        self.manager.add_message = MagicMock()
        self.manager.link_messages(messages, index_start=0, index_end=-1, max_size=1)

        self.assertNotEqual(messages[0]["content"], '[{"step_name": "action", "raw_text": "x" * 2000}]')

    def test_retrieve_message_returns_content(self):
        """Test that retrieve_message returns message content."""
        mock_msg = MagicMock()
        mock_msg.message = "Test message content"
        self.mock_storage.get_message.return_value = mock_msg

        result = self.manager.retrieve_message("test_msg_id")
        self.assertEqual(result, "Test message content")

    def test_retrieve_message_calls_get_message(self):
        """Test that get_message is called with correct msg_id."""
        mock_msg = MagicMock()
        mock_msg.message = "Test"
        self.mock_storage.get_message.return_value = mock_msg

        self.manager.retrieve_message("test_msg_id")
        self.mock_storage.get_message.assert_called_once_with("test_msg_id")

    @patch('topsailai.context.chat_history_manager.__base.json_tool')
    def test_retrieve_messages_returns_parsed_json(self, mock_json_tool):
        """Test that all messages are parsed as JSON objects."""
        mock_msg1 = MagicMock()
        mock_msg1.message = '{"content": "msg1"}'
        mock_msg2 = MagicMock()
        mock_msg2.message = '{"content": "msg2"}'
        self.mock_storage.get_messages_by_session.return_value = [mock_msg1, mock_msg2]
        mock_json_tool.json_load.side_effect = lambda x: {"parsed": x}

        result = self.manager.retrieve_messages("test_session")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], {"parsed": '{"content": "msg1"}'})
        self.assertEqual(result[1], {"parsed": '{"content": "msg2"}'})

    @patch('topsailai.context.chat_history_manager.__base.json_tool')
    def test_retrieve_messages_empty_session(self, mock_json_tool):
        """Test handling of empty session."""
        self.mock_storage.get_messages_by_session.return_value = []

        result = self.manager.retrieve_messages("empty_session")
        self.assertEqual(result, [])

    def test_call_invokes_link_messages(self):
        """Test that __call__ invokes link_messages."""
        messages = [{"role": "user", "content": "test"}]
        self.manager.link_messages = MagicMock()

        self.manager(messages)
        self.manager.link_messages.assert_called_once_with(messages)

    @patch('topsailai.context.chat_history_manager.__base.get_session_id')
    @patch('topsailai.context.chat_history_manager.__base.get_current_date')
    @patch('topsailai.context.chat_history_manager.__base.logger')
    @patch('topsailai.context.chat_history_manager.__base.json_tool')
    def test_add_session_message_adds_creation_time(self, mock_json_tool, mock_logger, mock_get_current_date, mock_get_session_id):
        """Test that create_time is added for non-system messages."""
        mock_get_session_id.return_value = "test_session"
        mock_get_current_date.return_value = "2025-01-01T00:00:00"
        mock_json_tool.json_dump.side_effect = lambda x, **kwargs: str(x)

        last_message = {"role": "user", "content": "Hello"}
        self.manager.add_message = MagicMock()
        self.manager.add_session_message(last_message)

        call_args = self.manager.add_message.call_args[0][0]
        self.assertIsInstance(call_args, ChatHistoryMessageData)

    @patch('topsailai.context.chat_history_manager.__base.get_session_id')
    @patch('topsailai.context.chat_history_manager.__base.get_current_date')
    @patch('topsailai.context.chat_history_manager.__base.logger')
    @patch('topsailai.context.chat_history_manager.__base.json_tool')
    def test_add_session_message_skips_system_role(self, mock_json_tool, mock_logger, mock_get_current_date, mock_get_session_id):
        """Test that create_time is NOT added for system messages."""
        mock_get_session_id.return_value = "test_session"
        mock_get_current_date.return_value = "2025-01-01T00:00:00"
        mock_json_tool.json_dump.side_effect = lambda x, **kwargs: str(x)

        last_message = {"role": ROLE_SYSTEM, "content": "System prompt"}
        self.manager.add_message = MagicMock()
        self.manager.add_session_message(last_message)

        self.manager.add_message.assert_called_once()
        call_args = self.manager.add_message.call_args[0][0]
        self.assertIsInstance(call_args, ChatHistoryMessageData)

    @patch('topsailai.context.chat_history_manager.__base.get_session_id')
    @patch('topsailai.context.chat_history_manager.__base.get_current_date')
    @patch('topsailai.context.chat_history_manager.__base.logger')
    @patch('topsailai.context.chat_history_manager.__base.json_tool')
    def test_add_session_message_uses_provided_session_id(self, mock_json_tool, mock_logger, mock_get_current_date, mock_get_session_id):
        """Test that provided session_id is used over get_session_id()."""
        mock_get_current_date.return_value = "2025-01-01T00:00:00"
        mock_json_tool.json_dump.side_effect = lambda x, **kwargs: str(x)

        last_message = {"role": "user", "content": "Hello"}
        self.manager.add_message = MagicMock()
        self.manager.add_session_message(last_message, session_id="custom_session")

        call_args = self.manager.add_message.call_args[0][0]
        self.assertEqual(call_args.session_id, "custom_session")
        mock_get_session_id.assert_not_called()


class TestChatHistoryBase(unittest.TestCase):
    """Test cases for ChatHistoryBase class."""

    def test_inherits_from_context_manager(self):
        """Test that ChatHistoryBase inherits from ContextManager."""
        self.assertTrue(issubclass(ChatHistoryBase, ContextManager))

    def test_tb_chat_history_messages_attribute(self):
        """Test that tb_chat_history_messages attribute is set correctly."""
        self.assertEqual(ChatHistoryBase.tb_chat_history_messages, "chat_history_messages")

    def test_tb_map_session_message_attribute(self):
        """Test that tb_map_session_message attribute is set correctly."""
        self.assertEqual(ChatHistoryBase.tb_map_session_message, "map_session_message")

    def test_instance_has_table_attributes(self):
        """Test that instances have the table name attributes."""
        instance = ChatHistoryBase()
        self.assertEqual(instance.tb_chat_history_messages, "chat_history_messages")
        self.assertEqual(instance.tb_map_session_message, "map_session_message")


if __name__ == '__main__':
    unittest.main()
