"""
Unit tests for storage base classes.

Tests SessionData, SessionStorageBase, MessageData, and MessageStorageBase classes.

Author: mm-m25
Created: 2026-04-17
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch


class TestSessionData:
    """Tests for SessionData class."""

    def test_init_with_required_params(self):
        """Test SessionData initialization with required parameters only."""
        from topsailai_server.agent_daemon.storage.session_manager.base import SessionData

        session = SessionData(session_id="test_123", task="Test task")

        assert session.session_id == "test_123"
        assert session.task == "Test task"
        assert session.session_name is None
        assert session.create_time is None
        assert session.update_time is None
        assert session.processed_msg_id is None

    def test_init_with_all_params(self):
        """Test SessionData initialization with all parameters."""
        from topsailai_server.agent_daemon.storage.session_manager.base import SessionData

        now = datetime.now()
        session = SessionData(
            session_id="test_456",
            task="Full test task",
            session_name="Test Session",
            create_time=now,
            update_time=now,
            processed_msg_id="msg_789"
        )

        assert session.session_id == "test_456"
        assert session.task == "Full test task"
        assert session.session_name == "Test Session"
        assert session.create_time == now
        assert session.update_time == now
        assert session.processed_msg_id == "msg_789"

    def test_init_with_optional_params(self):
        """Test SessionData initialization with optional parameters."""
        from topsailai_server.agent_daemon.storage.session_manager.base import SessionData

        session = SessionData(
            session_id="opt_123",
            task="Optional params test",
            session_name="Optional Session"
        )

        assert session.session_id == "opt_123"
        assert session.task == "Optional params test"
        assert session.session_name == "Optional Session"


class TestSessionStorageBase:
    """Tests for SessionStorageBase abstract class."""

    def test_tb_session_default_value(self):
        """Test that tb_session has correct default value."""
        from topsailai_server.agent_daemon.storage.session_manager.base import SessionStorageBase

        assert SessionStorageBase.tb_session == "session"

    def test_message_manager_initialization(self):
        """Test that message_manager is initialized to None."""
        from topsailai_server.agent_daemon.storage.session_manager.base import SessionStorageBase

        storage = SessionStorageBase()
        assert storage.message_manager is None

    def test_exists_session_not_implemented(self):
        """Test that exists_session raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.session_manager.base import SessionStorageBase

        storage = SessionStorageBase()
        with pytest.raises(NotImplementedError):
            storage.exists_session("test_id")

    def test_create_not_implemented(self):
        """Test that create raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.session_manager.base import SessionStorageBase

        storage = SessionStorageBase()
        with pytest.raises(NotImplementedError):
            storage.create(MagicMock())

    def test_update_not_implemented(self):
        """Test that update raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.session_manager.base import SessionStorageBase

        storage = SessionStorageBase()
        with pytest.raises(NotImplementedError):
            storage.update(MagicMock())

    def test_delete_not_implemented(self):
        """Test that delete raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.session_manager.base import SessionStorageBase

        storage = SessionStorageBase()
        with pytest.raises(NotImplementedError):
            storage.delete("test_id")

    def test_get_not_implemented(self):
        """Test that get raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.session_manager.base import SessionStorageBase

        storage = SessionStorageBase()
        with pytest.raises(NotImplementedError):
            storage.get("test_id")

    def test_get_all_not_implemented(self):
        """Test that get_all raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.session_manager.base import SessionStorageBase

        storage = SessionStorageBase()
        with pytest.raises(NotImplementedError):
            storage.get_all()

    def test_get_sessions_before_not_implemented(self):
        """Test that get_sessions_before raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.session_manager.base import SessionStorageBase

        storage = SessionStorageBase()
        with pytest.raises(NotImplementedError):
            storage.get_sessions_before(datetime.now())

    def test_get_sessions_older_than_not_implemented(self):
        """Test that get_sessions_older_than raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.session_manager.base import SessionStorageBase

        storage = SessionStorageBase()
        with pytest.raises(NotImplementedError):
            storage.get_sessions_older_than(datetime.now())

    def test_update_processed_msg_id_not_implemented(self):
        """Test that update_processed_msg_id raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.session_manager.base import SessionStorageBase

        storage = SessionStorageBase()
        with pytest.raises(NotImplementedError):
            storage.update_processed_msg_id("session_id", "msg_id")

    def test_get_or_create_not_implemented(self):
        """Test that get_or_create raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.session_manager.base import SessionStorageBase

        storage = SessionStorageBase()
        with pytest.raises(NotImplementedError):
            storage.get_or_create("session_id")


class TestMessageData:
    """Tests for MessageData class."""

    def test_init_with_required_params(self):
        """Test MessageData initialization with required parameters only."""
        from topsailai_server.agent_daemon.storage.message_manager.base import MessageData

        message = MessageData(message="Hello, world!")

        assert message.message == "Hello, world!"
        assert message.msg_id is not None  # Should be auto-generated
        assert message.session_id is None
        assert message.role == "user"
        assert message.create_time is None
        assert message.update_time is None
        assert message.task_id is None
        assert message.task_result is None

    def test_init_with_all_params(self):
        """Test MessageData initialization with all parameters."""
        from topsailai_server.agent_daemon.storage.message_manager.base import MessageData

        now = datetime.now()
        message = MessageData(
            message="Test message",
            msg_id="msg_123",
            session_id="session_456",
            role="assistant",
            create_time=now,
            update_time=now,
            task_id="task_789",
            task_result="Task completed"
        )

        assert message.message == "Test message"
        assert message.msg_id == "msg_123"
        assert message.session_id == "session_456"
        assert message.role == "assistant"
        assert message.create_time == now
        assert message.update_time == now
        assert message.task_id == "task_789"
        assert message.task_result == "Task completed"

    def test_init_with_custom_role(self):
        """Test MessageData initialization with custom role."""
        from topsailai_server.agent_daemon.storage.message_manager.base import MessageData

        message = MessageData(message="Assistant response", role="assistant")

        assert message.role == "assistant"

    def test_init_with_task_info(self):
        """Test MessageData initialization with task information."""
        from topsailai_server.agent_daemon.storage.message_manager.base import MessageData

        message = MessageData(
            message="Task message",
            task_id="task_001",
            task_result="Result data"
        )

        assert message.task_id == "task_001"
        assert message.task_result == "Result data"


class TestMessageStorageBase:
    """Tests for MessageStorageBase abstract class."""

    def test_tb_message_default_value(self):
        """Test that tb_message has correct default value."""
        from topsailai_server.agent_daemon.storage.message_manager.base import MessageStorageBase

        assert MessageStorageBase.tb_message == "message"

    def test_create_not_implemented(self):
        """Test that create raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.message_manager.base import MessageStorageBase

        storage = MessageStorageBase()
        with pytest.raises(NotImplementedError):
            storage.create(MagicMock())

    def test_get_not_implemented(self):
        """Test that get raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.message_manager.base import MessageStorageBase

        storage = MessageStorageBase()
        with pytest.raises(NotImplementedError):
            storage.get("msg_id", "session_id")

    def test_get_by_session_not_implemented(self):
        """Test that get_by_session raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.message_manager.base import MessageStorageBase

        storage = MessageStorageBase()
        with pytest.raises(NotImplementedError):
            storage.get_by_session("session_id")

    def test_get_by_session_sorted_not_implemented(self):
        """Test that get_by_session_sorted raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.message_manager.base import MessageStorageBase

        storage = MessageStorageBase()
        with pytest.raises(NotImplementedError):
            storage.get_by_session_sorted("session_id")

    def test_get_latest_message_not_implemented(self):
        """Test that get_latest_message raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.message_manager.base import MessageStorageBase

        storage = MessageStorageBase()
        with pytest.raises(NotImplementedError):
            storage.get_latest_message("session_id")

    def test_get_unprocessed_messages_not_implemented(self):
        """Test that get_unprocessed_messages raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.message_manager.base import MessageStorageBase

        storage = MessageStorageBase()
        with pytest.raises(NotImplementedError):
            storage.get_unprocessed_messages("session_id", "processed_msg_id")

    def test_get_messages_since_not_implemented(self):
        """Test that get_messages_since raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.message_manager.base import MessageStorageBase

        storage = MessageStorageBase()
        with pytest.raises(NotImplementedError):
            storage.get_messages_since(datetime.now())

    def test_update_task_info_not_implemented(self):
        """Test that update_task_info raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.message_manager.base import MessageStorageBase

        storage = MessageStorageBase()
        with pytest.raises(NotImplementedError):
            storage.update_task_info("msg_id", "session_id", "task_id", "task_result")

    def test_delete_messages_by_session_not_implemented(self):
        """Test that delete_messages_by_session raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.message_manager.base import MessageStorageBase

        storage = MessageStorageBase()
        with pytest.raises(NotImplementedError):
            storage.delete_messages_by_session("session_id")

    def test_add_message_not_implemented(self):
        """Test that add_message raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.message_manager.base import MessageStorageBase

        storage = MessageStorageBase()
        with pytest.raises(NotImplementedError):
            storage.add_message(MagicMock())

    def test_get_message_not_implemented(self):
        """Test that get_message raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.message_manager.base import MessageStorageBase

        storage = MessageStorageBase()
        with pytest.raises(NotImplementedError):
            storage.get_message("msg_id")

    def test_get_messages_by_session_not_implemented(self):
        """Test that get_messages_by_session raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.message_manager.base import MessageStorageBase

        storage = MessageStorageBase()
        with pytest.raises(NotImplementedError):
            storage.get_messages_by_session("session_id")

    def test_del_messages_not_implemented(self):
        """Test that del_messages raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.message_manager.base import MessageStorageBase

        storage = MessageStorageBase()
        with pytest.raises(NotImplementedError):
            storage.del_messages(msg_id="msg_id")

    def test_clean_messages_not_implemented(self):
        """Test that clean_messages raises NotImplementedError."""
        from topsailai_server.agent_daemon.storage.message_manager.base import MessageStorageBase

        storage = MessageStorageBase()
        with pytest.raises(NotImplementedError):
            storage.clean_messages(3600)
