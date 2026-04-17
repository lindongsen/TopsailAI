"""
Unit tests for MessageSQLAlchemy storage implementation.

Tests CRUD operations, filtering, sorting, and pagination for message storage.

Author: mm-m25
Created: 2026-04-17
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine

from topsailai_server.agent_daemon.storage.message_manager.base import MessageData
from topsailai_server.agent_daemon.storage.message_manager.sql import MessageSQLAlchemy, Message
from topsailai_server.agent_daemon.storage.message_manager.constants import (
    MESSAGE_ROLE_USER,
    MESSAGE_ROLE_ASSISTANT,
)


class TestMessageSQLAlchemyInit:
    """Tests for MessageSQLAlchemy initialization."""

    def test_init_creates_tables(self):
        """Test that initialization creates the message table."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        # Verify table exists
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        assert "message" in tables

    def test_get_engine(self):
        """Test that get_engine returns the correct engine."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        assert storage.get_engine() == engine


class TestMessageSQLAlchemyCreate:
    """Tests for MessageSQLAlchemy create operation."""

    def test_create_message_success(self):
        """Test successful message creation."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        message_data = MessageData(
            msg_id="msg_001",
            session_id="session_001",
            message="Hello, world!",
            role="user"
        )

        result = storage.create(message_data)

        assert result is True
        # Verify message was created
        created = storage.get("msg_001", "session_001")
        assert created is not None
        assert created.msg_id == "msg_001"
        assert created.message == "Hello, world!"

    def test_create_message_with_task_info(self):
        """Test message creation with task information."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        message_data = MessageData(
            msg_id="msg_task_001",
            session_id="session_001",
            message="Task message",
            role="assistant",
            task_id="task_001",
            task_result="Task result"
        )

        storage.create(message_data)
        created = storage.get("msg_task_001", "session_001")

        assert created.task_id == "task_001"
        assert created.task_result == "Task result"

    def test_create_message_default_role(self):
        """Test message creation with default role."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        message_data = MessageData(
            msg_id="msg_default_role",
            session_id="session_001",
            message="Default role test"
        )

        storage.create(message_data)
        created = storage.get("msg_default_role", "session_001")

        assert created.role == MESSAGE_ROLE_USER


class TestMessageSQLAlchemyGet:
    """Tests for MessageSQLAlchemy get operations."""

    def test_get_existing_message(self):
        """Test getting an existing message."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        message_data = MessageData(
            msg_id="get_msg_001",
            session_id="session_001",
            message="Get test message"
        )
        storage.create(message_data)

        result = storage.get("get_msg_001", "session_001")

        assert result is not None
        assert result.msg_id == "get_msg_001"
        assert result.message == "Get test message"

    def test_get_nonexistent_message(self):
        """Test getting a non-existent message."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        result = storage.get("nonexistent", "session_001")

        assert result is None

    def test_get_by_session(self):
        """Test getting messages by session."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        session_id = "session_by_001"
        for i in range(3):
            storage.create(MessageData(
                msg_id=f"by_session_{i}",
                session_id=session_id,
                message=f"Message {i}"
            ))

        result = storage.get_by_session(session_id)

        assert len(result) == 3

    def test_get_latest_message(self):
        """Test getting the latest message for a session."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        session_id = "session_latest"
        now = datetime.now()

        # Create messages with different times
        for i in range(3):
            storage.create(MessageData(
                msg_id=f"latest_{i}",
                session_id=session_id,
                message=f"Message {i}",
                create_time=now - timedelta(minutes=3-i)
            ))

        result = storage.get_latest_message(session_id)

        assert result is not None
        assert result.msg_id == "latest_2"  # Most recent

    def test_get_message_by_id(self):
        """Test getting a message by msg_id only."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        storage.create(MessageData(
            msg_id="get_by_id_001",
            session_id="session_001",
            message="Get by ID test"
        ))

        result = storage.get_message("get_by_id_001")

        assert result is not None
        assert result.msg_id == "get_by_id_001"


class TestMessageSQLAlchemyUpdate:
    """Tests for MessageSQLAlchemy update operations."""

    def test_update_task_info(self):
        """Test updating task information."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        storage.create(MessageData(
            msg_id="update_task_001",
            session_id="session_001",
            message="Task message"
        ))

        result = storage.update_task_info(
            msg_id="update_task_001",
            session_id="session_001",
            task_id="new_task_001",
            task_result="New result"
        )

        assert result is not None
        assert result.task_id == "new_task_001"
        assert result.task_result == "New result"

    def test_update_task_info_nonexistent(self):
        """Test updating task info for non-existent message."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        result = storage.update_task_info(
            msg_id="nonexistent",
            session_id="session_001",
            task_id="task",
            task_result="result"
        )

        assert result is None


class TestMessageSQLAlchemyDelete:
    """Tests for MessageSQLAlchemy delete operations."""

    def test_delete_message(self):
        """Test deleting a single message."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        storage.create(MessageData(
            msg_id="delete_msg_001",
            session_id="session_001",
            message="Delete test"
        ))

        result = storage.delete("delete_msg_001", "session_001")

        assert result is True
        assert storage.get("delete_msg_001", "session_001") is None

    def test_delete_messages_by_session(self):
        """Test deleting all messages for a session."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        session_id = "session_delete"
        for i in range(3):
            storage.create(MessageData(
                msg_id=f"del_session_{i}",
                session_id=session_id,
                message=f"Message {i}"
            ))

        count = storage.delete_messages_by_session(session_id)

        assert count == 3
        assert len(storage.get_by_session(session_id)) == 0

    def test_del_messages_by_msg_id(self):
        """Test deleting messages by msg_id."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        storage.create(MessageData(
            msg_id="del_by_id_001",
            session_id="session_001",
            message="Test"
        ))
        storage.create(MessageData(
            msg_id="del_by_id_001",
            session_id="session_002",
            message="Test 2"
        ))

        storage.del_messages(msg_id="del_by_id_001")

        # Should be deleted from both sessions
        assert storage.get_message("del_by_id_001") is None


class TestMessageSQLAlchemyUnprocessed:
    """Tests for MessageSQLAlchemy unprocessed messages operations."""

    def test_get_unprocessed_messages_basic(self):
        """Test getting unprocessed messages."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        session_id = "session_unprocessed"
        now = datetime.now()

        # Create processed message
        storage.create(MessageData(
            msg_id="processed_001",
            session_id=session_id,
            message="Processed message",
            role="user",
            create_time=now - timedelta(minutes=10)
        ))

        # Create unprocessed messages
        for i in range(2):
            storage.create(MessageData(
                msg_id=f"unprocessed_{i}",
                session_id=session_id,
                message=f"Unprocessed {i}",
                role="user",
                create_time=now - timedelta(minutes=5-i)
            ))

        result = storage.get_unprocessed_messages(session_id, "processed_001")

        assert len(result) == 2
        msg_ids = [m.msg_id for m in result]
        assert "unprocessed_0" in msg_ids
        assert "unprocessed_1" in msg_ids

    def test_get_unprocessed_messages_empty_processed_id(self):
        """Test getting unprocessed messages with empty processed_msg_id."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        session_id = "session_empty_processed"
        for i in range(3):
            storage.create(MessageData(
                msg_id=f"empty_proc_{i}",
                session_id=session_id,
                message=f"Message {i}",
                role="user"
            ))

        result = storage.get_unprocessed_messages(session_id, "")

        assert len(result) == 3

    def test_get_unprocessed_messages_none_processed_id(self):
        """Test getting unprocessed messages with None processed_msg_id."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        session_id = "session_none_processed"
        for i in range(3):
            storage.create(MessageData(
                msg_id=f"none_proc_{i}",
                session_id=session_id,
                message=f"Message {i}",
                role="user"
            ))

        result = storage.get_unprocessed_messages(session_id, None)

        assert len(result) == 3


class TestMessageSQLAlchemyGetMessagesSince:
    """Tests for MessageSQLAlchemy get_messages_since operation."""

    def test_get_messages_since(self):
        """Test getting messages created since a time."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        now = datetime.now()

        # Create old message
        storage.create(MessageData(
            msg_id="old_since",
            session_id="session_001",
            message="Old message",
            create_time=now - timedelta(days=7)
        ))

        # Create recent message
        storage.create(MessageData(
            msg_id="recent_since",
            session_id="session_001",
            message="Recent message",
            create_time=now - timedelta(hours=1)
        ))

        result = storage.get_messages_since(now - timedelta(days=1))

        assert len(result) >= 1
        assert any(m.msg_id == "recent_since" for m in result)


class TestMessageSQLAlchemyGetBySessionSorted:
    """Tests for MessageSQLAlchemy get_by_session_sorted operation."""

    def test_get_by_session_sorted_ascending(self):
        """Test getting messages sorted ascending."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        session_id = "session_sorted_asc"
        now = datetime.now()

        for i in range(3):
            storage.create(MessageData(
                msg_id=f"sort_asc_{i}",
                session_id=session_id,
                message=f"Message {i}",
                create_time=now - timedelta(minutes=3-i)
            ))

        result = storage.get_by_session_sorted(
            session_id,
            order_by="asc"
        )

        assert len(result) == 3
        # First message should be the oldest (i=0 -> now-3min, i=1 -> now-2min, i=2 -> now-1min)
        assert result[0].msg_id == "sort_asc_0"

    def test_get_by_session_sorted_with_time_filter(self):
        """Test getting messages with time filter."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        session_id = "session_time_filter"
        now = datetime.now()

        # Create messages at different times
        storage.create(MessageData(
            msg_id="time_old",
            session_id=session_id,
            message="Old message",
            create_time=now - timedelta(days=2)
        ))
        storage.create(MessageData(
            msg_id="time_recent",
            session_id=session_id,
            message="Recent message",
            create_time=now
        ))

        result = storage.get_by_session_sorted(
            session_id,
            start_time=now - timedelta(days=1)
        )

        assert len(result) >= 1
        assert any(m.msg_id == "time_recent" for m in result)

    def test_get_by_session_sorted_pagination(self):
        """Test getting messages with pagination."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        session_id = "session_pagination"
        for i in range(10):
            storage.create(MessageData(
                msg_id=f"page_{i}",
                session_id=session_id,
                message=f"Message {i}"
            ))

        # Get first page
        page1 = storage.get_by_session_sorted(session_id, offset=0, limit=3)
        assert len(page1) == 3

        # Get second page
        page2 = storage.get_by_session_sorted(session_id, offset=3, limit=3)
        assert len(page2) == 3


class TestMessageSQLAlchemyAddMessage:
    """Tests for MessageSQLAlchemy add_message operation."""

    def test_add_new_message(self):
        """Test adding a new message."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        message = MessageData(
            msg_id="add_new_001",
            session_id="session_001",
            message="New message"
        )

        storage.add_message(message)

        result = storage.get("add_new_001", "session_001")
        assert result is not None
        assert result.message == "New message"

    def test_add_duplicate_message(self):
        """Test adding a duplicate message (should not create duplicate)."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        message = MessageData(
            msg_id="dup_msg_001",
            session_id="session_001",
            message="Original message"
        )

        storage.add_message(message)
        storage.add_message(message)  # Try to add again

        # Should still have only one message
        result = storage.get_by_session("session_001")
        assert len(result) == 1


class TestMessageSQLAlchemyCleanMessages:
    """Tests for MessageSQLAlchemy clean_messages operation."""

    def test_clean_old_messages(self):
        """Test cleaning old messages."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        now = datetime.now()

        # Create old message (2 hours old)
        storage.create(MessageData(
            msg_id="old_clean",
            session_id="session_001",
            message="Old message",
            create_time=now - timedelta(hours=2)
        ))

        # Create recent message
        storage.create(MessageData(
            msg_id="recent_clean",
            session_id="session_001",
            message="Recent message",
            create_time=now
        ))

        # Clean messages older than 1 hour
        count = storage.clean_messages(3600, "session_001")

        assert count >= 1
        # Recent message should still exist
        assert storage.get("recent_clean", "session_001") is not None


class TestMessageSQLAlchemyIndexes:
    """Tests for MessageSQLAlchemy index verification."""

    def test_verify_indexes(self):
        """Test index verification."""
        engine = create_engine("sqlite:///:memory:")
        storage = MessageSQLAlchemy(engine)

        result = storage.verify_indexes()

        assert isinstance(result, dict)
        assert "idx_message_session_create" in result
        assert "idx_message_session_role" in result
