#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for topsailai.context.chat_history_manager module.

Tests chat history management classes including:
- ChatHistoryMessageData data structure
- MessageStorageBase abstract interface
- ContextManager message linking and retrieval
- ChatHistoryBase base class
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from topsailai.context.chat_history_manager.__base import (
    ChatHistoryMessageData,
    MessageStorageBase,
    ContextManager,
    ChatHistoryBase,
)


class TestChatHistoryMessageData:
    """Tests for ChatHistoryMessageData class."""

    def test_init_with_all_params(self):
        """Test initialization with all parameters provided."""
        msg = ChatHistoryMessageData(
            message="Hello, world!",
            msg_id="msg_123",
            session_id="session_456"
        )
        assert msg.msg_id == "msg_123"
        assert msg.session_id == "session_456"
        assert msg.message == "Hello, world!"
        assert msg.msg_size == 13
        assert msg.create_time is None
        assert msg.access_time is None
        assert msg.access_count is None

    def test_init_without_msg_id_generates_from_content(self):
        """Test that msg_id is auto-generated from message content."""
        msg = ChatHistoryMessageData(
            message="Test message",
            msg_id=None,
            session_id="session_123"
        )
        assert msg.msg_id is not None
        assert len(msg.msg_id) > 0

    def test_init_empty_message(self):
        """Test initialization with empty message."""
        msg = ChatHistoryMessageData(
            message="",
            msg_id="msg_empty",
            session_id="session_123"
        )
        assert msg.msg_size == 0

    def test_init_none_message(self):
        """Test initialization with None message."""
        msg = ChatHistoryMessageData(
            message=None,
            msg_id="msg_none",
            session_id="session_123"
        )
        assert msg.msg_size == 0

    def test_msg_size_calculation(self):
        """Test that msg_size is correctly calculated."""
        long_message = "A" * 1000
        msg = ChatHistoryMessageData(
            message=long_message,
            msg_id="msg_long",
            session_id="session_123"
        )
        assert msg.msg_size == 1000


class TestMessageStorageBase:
    """Tests for MessageStorageBase abstract class."""

    def test_add_session_message_not_implemented(self):
        """Test that add_session_message raises NotImplementedError."""
        storage = MessageStorageBase()
        with pytest.raises(NotImplementedError):
            storage.add_session_message({"role": "user", "content": "test"})

    def test_add_message_not_implemented(self):
        """Test that add_message raises NotImplementedError."""
        storage = MessageStorageBase()
        msg = ChatHistoryMessageData("test", "msg_1", "session_1")
        with pytest.raises(NotImplementedError):
            storage.add_message(msg)

    def test_get_message_not_implemented(self):
        """Test that get_message raises NotImplementedError."""
        storage = MessageStorageBase()
        with pytest.raises(NotImplementedError):
            storage.get_message("msg_123")

    def test_get_messages_by_session_not_implemented(self):
        """Test that get_messages_by_session raises NotImplementedError."""
        storage = MessageStorageBase()
        with pytest.raises(NotImplementedError):
            storage.get_messages_by_session("session_123")

    def test_del_messages_not_implemented(self):
        """Test that del_messages raises NotImplementedError."""
        storage = MessageStorageBase()
        with pytest.raises(NotImplementedError):
            storage.del_messages(session_id="session_123")

    def test_update_message_access_not_implemented(self):
        """Test that update_message_access raises NotImplementedError."""
        storage = MessageStorageBase()
        with pytest.raises(NotImplementedError):
            storage.update_message_access("msg_123")

    def test_clean_messages_not_implemented(self):
        """Test that clean_messages raises NotImplementedError."""
        storage = MessageStorageBase()
        with pytest.raises(NotImplementedError):
            storage.clean_messages(3600)


class TestContextManagerConstants:
    """Tests for ContextManager class constants."""

    def test_ignored_roles(self):
        """Test that ignored_roles contains system and user roles."""
        assert hasattr(ContextManager, 'ignored_roles')
        assert isinstance(ContextManager.ignored_roles, set)
        assert len(ContextManager.ignored_roles) > 0

    def test_attention_step_names(self):
        """Test that attention_step_names contains action and observation."""
        assert hasattr(ContextManager, 'attention_step_names')
        assert isinstance(ContextManager.attention_step_names, set)
        assert "action" in ContextManager.attention_step_names
        assert "observation" in ContextManager.attention_step_names

    def test_prefix_raw_text_retrieve_msg(self):
        """Test that prefix for archived message references is defined."""
        assert hasattr(ContextManager, 'prefix_raw_text_retrieve_msg')
        assert isinstance(ContextManager.prefix_raw_text_retrieve_msg, str)
        assert "msg_id" in ContextManager.prefix_raw_text_retrieve_msg


class TestContextManagerLinkMessages:
    """Tests for ContextManager.link_messages method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.ctx_mgr = ContextManager.__new__(ContextManager)
        self.ctx_mgr.conn = MagicMock()

    def test_link_messages_empty_list(self):
        """Test that empty message list is handled."""
        messages = []
        self.ctx_mgr.link_messages(messages)
        assert messages == []

    def test_link_messages_skips_system_role(self):
        """Test that system role messages are skipped."""
        messages = [
            {"role": "system", "content": '{"step_name": "test"}'}
        ]
        with patch.object(self.ctx_mgr, 'add_message'):
            self.ctx_mgr.link_messages(messages)
        # System messages should be skipped
        assert len(messages) == 1

    def test_link_messages_skips_user_role_without_tool_call(self):
        """Test that user messages without tool_call_id are skipped."""
        messages = [
            {"role": "user", "content": '{"step_name": "test"}'}
        ]
        with patch.object(self.ctx_mgr, 'add_message'):
            self.ctx_mgr.link_messages(messages)
        # User messages without tool_call_id should be skipped
        assert len(messages) == 1

    def test_link_messages_processes_user_with_tool_call(self):
        """Test that user messages with tool_call_id are processed."""
        messages = [
            {"role": "user", "content": '{"step_name": "action", "raw_text": "test content"}', "tool_call_id": "call_123"}
        ]
        with patch.object(self.ctx_mgr, 'add_message'):
            with patch.object(self.ctx_mgr, '_link_msg_id'):
                self.ctx_mgr.link_messages(messages)

    def test_link_messages_skips_non_json_content(self):
        """Test that non-JSON content is skipped."""
        messages = [
            {"role": "assistant", "content": "This is plain text"}
        ]
        with patch.object(self.ctx_mgr, 'add_message'):
            self.ctx_mgr.link_messages(messages)
        assert len(messages) == 1

    def test_link_messages_skips_non_attention_steps(self):
        """Test that steps not in attention_step_names are skipped."""
        messages = [
            {"role": "assistant", "content": '{"step_name": "thought", "raw_text": "thinking"}'}
        ]
        with patch.object(self.ctx_mgr, 'add_message'):
            self.ctx_mgr.link_messages(messages)
        assert len(messages) == 1

    def test_link_messages_custom_index_range(self):
        """Test link_messages with custom index range."""
        messages = [
            {"role": "system", "content": '{"step_name": "action"}'},
            {"role": "assistant", "content": '{"step_name": "action"}'},
            {"role": "assistant", "content": '{"step_name": "action"}'},
        ]
        with patch.object(self.ctx_mgr, 'add_message'):
            with patch.object(self.ctx_mgr, '_link_msg_id'):
                self.ctx_mgr.link_messages(messages, index_start=1, index_end=2)

    def test_link_messages_custom_max_size(self):
        """Test link_messages with custom max_size threshold."""
        small_content = '{"step_name": "action", "raw_text": "small"}'
        messages = [
            {"role": "assistant", "content": small_content}
        ]
        with patch.object(self.ctx_mgr, 'add_message'):
            with patch.object(self.ctx_mgr, '_link_msg_id') as mock_link:
                self.ctx_mgr.link_messages(messages, max_size=10000)
                # Small content should not trigger linking
                mock_link.assert_not_called()


class TestContextManagerLinkMsgId:
    """Tests for ContextManager._link_msg_id method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.ctx_mgr = ContextManager.__new__(ContextManager)
        self.ctx_mgr.conn = MagicMock()

    def test_link_msg_id_with_raw_text(self):
        """Test archiving content with raw_text key."""
        content_dict = {"raw_text": "Large content here"}
        with patch.object(self.ctx_mgr, 'add_message') as mock_add:
            mock_msg = MagicMock()
            mock_msg.msg_id = "archived_msg_id"
            mock_add.return_value = None
            self.ctx_mgr._link_msg_id(content_dict)
            mock_add.assert_called_once()
            # Content should be replaced with archive reference
            assert "step_name" in content_dict
            assert "msg_id" in content_dict["raw_text"]

    def test_link_msg_id_with_dict_content(self):
        """Test archiving content with multiple keys."""
        content_dict = {"step_name": "action", "raw_text": "test", "extra": "data"}
        with patch.object(self.ctx_mgr, 'add_message') as mock_add:
            mock_add.return_value = None
            self.ctx_mgr._link_msg_id(content_dict)
            mock_add.assert_called_once()

    def test_link_msg_id_non_string_converted(self):
        """Test that non-string content is converted to JSON."""
        content_dict = {"raw_text": {"nested": "data"}}
        with patch.object(self.ctx_mgr, 'add_message') as mock_add:
            mock_add.return_value = None
            self.ctx_mgr._link_msg_id(content_dict)
            mock_add.assert_called_once()


class TestContextManagerRetrieve:
    """Tests for ContextManager message retrieval methods."""

    def setup_method(self):
        """Set up test fixtures."""
        self.ctx_mgr = ContextManager.__new__(ContextManager)
        self.ctx_mgr.conn = MagicMock()

    def test_retrieve_message(self):
        """Test retrieving a message by ID."""
        mock_msg = MagicMock()
        mock_msg.message = "Retrieved message content"
        with patch.object(self.ctx_mgr, 'get_message', return_value=mock_msg):
            result = self.ctx_mgr.retrieve_message("msg_123")
            assert result == "Retrieved message content"

    def test_retrieve_messages(self):
        """Test retrieving all messages for a session."""
        mock_msg1 = MagicMock()
        mock_msg1.message = '{"role": "user", "content": "hello"}'
        mock_msg2 = MagicMock()
        mock_msg2.message = '{"role": "assistant", "content": "hi"}'
        with patch.object(self.ctx_mgr, 'get_messages_by_session', return_value=[mock_msg1, mock_msg2]):
            result = self.ctx_mgr.retrieve_messages("session_123")
            assert len(result) == 2
            assert result[0]["role"] == "user"
            assert result[1]["role"] == "assistant"


class TestContextManagerCall:
    """Tests for ContextManager __call__ method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.ctx_mgr = ContextManager.__new__(ContextManager)
        self.ctx_mgr.conn = MagicMock()

    def test_call_invokes_link_messages(self):
        """Test that __call__ invokes link_messages."""
        messages = [
            {"role": "assistant", "content": '{"step_name": "action"}'}
        ]
        with patch.object(self.ctx_mgr, 'link_messages') as mock_link:
            self.ctx_mgr(messages)
            mock_link.assert_called_once_with(messages)


class TestContextManagerAddSessionMessage:
    """Tests for ContextManager.add_session_message method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.ctx_mgr = ContextManager.__new__(ContextManager)
        self.ctx_mgr.conn = MagicMock()

    def test_add_session_message_no_session_id(self):
        """Test that message is not added when session_id is None."""
        with patch('topsailai.context.chat_history_manager.__base.get_session_id', return_value=None):
            with patch.object(self.ctx_mgr, 'add_message') as mock_add:
                self.ctx_mgr.add_session_message({"role": "user", "content": "test"})
                mock_add.assert_not_called()

    def test_add_session_message_string_none(self):
        """Test that message is not added when session_id is 'None' string."""
        with patch('topsailai.context.chat_history_manager.__base.get_session_id', return_value="None"):
            with patch.object(self.ctx_mgr, 'add_message') as mock_add:
                self.ctx_mgr.add_session_message({"role": "user", "content": "test"})
                mock_add.assert_not_called()

    def test_add_session_message_system_role_no_create_time(self):
        """Test that system messages don't get create_time added."""
        with patch('topsailai.context.chat_history_manager.__base.get_session_id', return_value="session_123"):
            with patch.object(self.ctx_mgr, 'add_message') as mock_add:
                mock_add.return_value = None
                self.ctx_mgr.add_session_message({"role": "system", "content": "You are helpful"})
                # System messages should not have create_time added
                call_args = mock_add.call_args
                msg_data = call_args[0][0]
                # Check that message contains the expected content (JSON may have formatting)
                parsed = json.loads(msg_data.message)
                assert parsed["role"] == "system"
                assert parsed["content"] == "You are helpful"
                assert "create_time" not in parsed

    def test_add_session_message_user_role_adds_create_time(self):
        """Test that non-system messages get create_time added."""
        with patch('topsailai.context.chat_history_manager.__base.get_session_id', return_value="session_123"):
            with patch('topsailai.context.chat_history_manager.__base.get_current_date', return_value="2025-01-01"):
                with patch.object(self.ctx_mgr, 'add_message') as mock_add:
                    mock_add.return_value = None
                    self.ctx_mgr.add_session_message({"role": "user", "content": "hello"})
                    mock_add.assert_called_once()

    def test_add_session_message_with_explicit_session_id(self):
        """Test adding message with explicit session_id parameter."""
        with patch.object(self.ctx_mgr, 'add_message') as mock_add:
            mock_add.return_value = None
            self.ctx_mgr.add_session_message(
                {"role": "user", "content": "test"},
                session_id="explicit_session"
            )
            mock_add.assert_called_once()


class TestChatHistoryBase:
    """Tests for ChatHistoryBase class."""

    def test_table_names_defined(self):
        """Test that table names are defined as class attributes."""
        assert hasattr(ChatHistoryBase, 'tb_chat_history_messages')
        assert hasattr(ChatHistoryBase, 'tb_map_session_message')
        assert isinstance(ChatHistoryBase.tb_chat_history_messages, str)
        assert isinstance(ChatHistoryBase.tb_map_session_message, str)

    def test_inherits_from_context_manager(self):
        """Test that ChatHistoryBase inherits from ContextManager."""
        assert issubclass(ChatHistoryBase, ContextManager)


class TestContextManagerEdgeCases:
    """Edge case tests for ContextManager."""

    def setup_method(self):
        """Set up test fixtures."""
        self.ctx_mgr = ContextManager.__new__(ContextManager)
        self.ctx_mgr.conn = MagicMock()

    def test_link_messages_invalid_json(self):
        """Test handling of invalid JSON content."""
        messages = [
            {"role": "assistant", "content": "{ invalid json }"}
        ]
        with patch.object(self.ctx_mgr, 'add_message'):
            self.ctx_mgr.link_messages(messages)
        # Should not crash, message should remain unchanged
        assert len(messages) == 1

    def test_link_messages_list_content(self):
        """Test handling of list content (array)."""
        messages = [
            {"role": "assistant", "content": '[{"step_name": "action"}]'}
        ]
        with patch.object(self.ctx_mgr, 'add_message'):
            with patch.object(self.ctx_mgr, '_link_msg_id'):
                self.ctx_mgr.link_messages(messages)

    def test_retrieve_message_not_found(self):
        """Test retrieving non-existent message."""
        with patch.object(self.ctx_mgr, 'get_message', return_value=None):
            with pytest.raises(AttributeError):
                self.ctx_mgr.retrieve_message("nonexistent")


class TestContextManagerIntegration:
    """Integration tests for context manager module."""

    def test_module_import(self):
        """Test that all expected classes are importable."""
        from topsailai.context.chat_history_manager.__base import (
            ChatHistoryMessageData,
            MessageStorageBase,
            ContextManager,
            ChatHistoryBase,
        )
        assert ChatHistoryMessageData is not None
        assert MessageStorageBase is not None
        assert ContextManager is not None
        assert ChatHistoryBase is not None

    def test_class_inheritance_hierarchy(self):
        """Test class inheritance hierarchy."""
        assert issubclass(MessageStorageBase, object)
        assert issubclass(ContextManager, MessageStorageBase)
        assert issubclass(ChatHistoryBase, ContextManager)

    def test_context_manager_instantiation(self):
        """Test that ContextManager can be instantiated."""
        ctx = ContextManager.__new__(ContextManager)
        assert ctx is not None
        assert hasattr(ctx, 'ignored_roles')
        assert hasattr(ctx, 'attention_step_names')
        assert hasattr(ctx, 'prefix_raw_text_retrieve_msg')
