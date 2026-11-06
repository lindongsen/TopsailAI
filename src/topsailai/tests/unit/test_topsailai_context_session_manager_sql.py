#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
  Unit tests for session_manager sql
'''

import pytest
import sys
import os
import time
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from sqlalchemy import text, event

from topsailai.context.session_manager.sql import SessionSQLAlchemy, SessionData, Session
from topsailai.context.chat_history_manager.__base import ChatHistoryMessageData
import topsailai.context.session_manager.sql as session_sql


class TestSessionSQLAlchemy:
    """Test suite for SessionSQLAlchemy class."""

    @pytest.fixture
    def session_mgr(self):
        """Create a fresh in-memory session manager for each test."""
        return SessionSQLAlchemy("sqlite:///:memory:")

    def test_create_session(self, session_mgr):
        """Test creating a new session."""
        session_data = SessionData(
            session_id="test_session_001",
            session_name="Test Session",
            task="Test task"
        )
        session_mgr.create_session(session_data)

        assert session_mgr.exists_session("test_session_001") is True

    def test_create_session_duplicate(self, session_mgr):
        """Test creating a session with duplicate ID raises ValueError."""
        session_data = SessionData(
            session_id="test_session_001",
            session_name="Test Session",
            task="Test task"
        )
        session_mgr.create_session(session_data)

        # Creating again should raise ValueError
        with pytest.raises(ValueError, match="Session test_session_001 already exists"):
            session_mgr.create_session(session_data)

        sessions = session_mgr.list_sessions()
        assert len(sessions) == 1

    def test_create_session_duplicate_raises_value_error(self, session_mgr):
        """Test that creating a session with duplicate ID raises ValueError."""
        session_data = SessionData(
            session_id="test_session_001",
            session_name="Test Session",
            task="Test task"
        )
        first_result = session_mgr.create_session(session_data)
        assert first_result is True

        with pytest.raises(ValueError, match="Session test_session_001 already exists"):
            session_mgr.create_session(session_data)

        sessions = session_mgr.list_sessions()
        assert len(sessions) == 1

    def test_get_session(self, session_mgr):
        """Test retrieving a session by ID."""
        session_data = SessionData(
            session_id="test_session_001",
            session_name="Test Session",
            task="Test task"
        )
        session_mgr.create_session(session_data)

        retrieved = session_mgr.get_session("test_session_001")
        assert retrieved is not None
        assert retrieved.session_id == "test_session_001"
        assert retrieved.session_name == "Test Session"
        assert retrieved.task == "Test task"

    def test_get_session_not_found(self, session_mgr):
        """Test retrieving a non-existent session."""
        retrieved = session_mgr.get_session("non_existent")
        assert retrieved is None

    def test_exists_session(self, session_mgr):
        """Test checking if a session exists."""
        assert session_mgr.exists_session("test_session_001") is False

        session_data = SessionData(
            session_id="test_session_001",
            session_name="Test Session",
            task="Test task"
        )
        session_mgr.create_session(session_data)

        assert session_mgr.exists_session("test_session_001") is True

    def test_list_sessions(self, session_mgr):
        """Test listing all sessions."""
        # Initially empty
        sessions = session_mgr.list_sessions()
        assert len(sessions) == 0

        # Create multiple sessions
        for i in range(3):
            session_data = SessionData(
                session_id=f"test_session_{i:03d}",
                session_name=f"Test Session {i}",
                task=f"Test task {i}"
            )
            session_mgr.create_session(session_data)

        sessions = session_mgr.list_sessions()
        assert len(sessions) == 3

    def test_list_sessions_with_filter(self, session_mgr):
        """Test listing sessions filtered by session IDs."""
        # Create multiple sessions
        for i in range(3):
            session_data = SessionData(
                session_id=f"test_session_{i:03d}",
                session_name=f"Test Session {i}",
                task=f"Test task {i}"
            )
            session_mgr.create_session(session_data)

        # Filter by subset of session IDs
        sessions = session_mgr.list_sessions(sessions=["test_session_000", "test_session_002"])
        assert len(sessions) == 2
        assert {s.session_id for s in sessions} == {"test_session_000", "test_session_002"}

    def test_list_sessions_with_empty_filter(self, session_mgr):
        """Test listing sessions with empty filter returns all sessions."""
        # Create multiple sessions
        for i in range(3):
            session_data = SessionData(
                session_id=f"test_session_{i:03d}",
                session_name=f"Test Session {i}",
                task=f"Test task {i}"
            )
            session_mgr.create_session(session_data)

        # Empty list should return all sessions
        sessions = session_mgr.list_sessions(sessions=[])
        assert len(sessions) == 3

        # None should also return all sessions
        sessions = session_mgr.list_sessions(sessions=None)
        assert len(sessions) == 3

    def test_list_sessions_with_nonexistent_filter(self, session_mgr):
        """Test listing sessions filtered by non-existent session IDs."""
        # Create multiple sessions
        for i in range(3):
            session_data = SessionData(
                session_id=f"test_session_{i:03d}",
                session_name=f"Test Session {i}",
                task=f"Test task {i}"
            )
            session_mgr.create_session(session_data)

        # Filter by non-existent session IDs returns empty list
        sessions = session_mgr.list_sessions(sessions=["non_existent_001", "non_existent_002"])
        assert len(sessions) == 0
        assert sessions == []

    def test_update_session_name(self, session_mgr):
        """Test updating session name."""
        session_data = SessionData(
            session_id="test_session_001",
            session_name="Old Name",
            task="Test task"
        )
        session_mgr.create_session(session_data)

        result = session_mgr.update_session_name("test_session_001", "New Name")
        assert result is True

        retrieved = session_mgr.get_session("test_session_001")
        assert retrieved.session_name == "New Name"

    def test_update_session_name_not_found(self, session_mgr):
        """Test updating name for non-existent session."""
        result = session_mgr.update_session_name("non_existent", "New Name")
        assert result is False

    def test_delete_session(self, session_mgr):
        """Test deleting a session."""
        session_data = SessionData(
            session_id="test_session_001",
            session_name="Test Session",
            task="Test task"
        )
        session_mgr.create_session(session_data)

        result = session_mgr.delete_session("test_session_001")
        assert result is True
        assert session_mgr.exists_session("test_session_001") is False

    def test_delete_session_not_found(self, session_mgr):
        """Test deleting non-existent session."""
        result = session_mgr.delete_session("non_existent")
        assert result is False

    def test_get_messages_by_session(self, session_mgr):
        """Test getting messages associated with a session."""
        session_data = SessionData(
            session_id="test_session_001",
            session_name="Test Session",
            task="Test task"
        )
        session_mgr.create_session(session_data)

        messages = session_mgr.get_messages_by_session("test_session_001")
        assert isinstance(messages, list)

    def test_retrieve_messages(self, session_mgr):
        """Test retrieving messages through chat history manager."""
        session_data = SessionData(
            session_id="test_session_001",
            session_name="Test Session",
            task="Test task"
        )
        session_mgr.create_session(session_data)

        messages = session_mgr.retrieve_messages("test_session_001")
        assert isinstance(messages, list)

    def test_session_data_defaults(self):
        """Test SessionData default values."""
        session_data = SessionData(session_id="test")
        assert session_data.session_id == "test"
        assert session_data.session_name is None
        assert session_data.task == ""
        assert session_data.create_time is None
    def test_list_sessions_ordering(self, session_mgr):
        """Test that sessions are listed in reverse chronological order."""
        # Create sessions with small time delays
        for i in range(3):
            session_data = SessionData(
                session_id=f"test_session_{i:03d}",
                session_name=f"Test Session {i}",
                task=f"Test task {i}"
            )
            session_mgr.create_session(session_data)
            time.sleep(0.01)

        sessions = session_mgr.list_sessions()
        assert len(sessions) == 3
        # Should be ordered by create_time descending
        assert sessions[0].session_id == "test_session_002"
        assert sessions[1].session_id == "test_session_001"
        assert sessions[2].session_id == "test_session_000"

    def test_update_session_name_empty_name(self, session_mgr):
        """Test updating session name with empty string."""
        session_data = SessionData(
            session_id="test_session_001",
            session_name="Old Name",
            task="Test task"
        )
        session_mgr.create_session(session_data)

        result = session_mgr.update_session_name("test_session_001", "")
        assert result is True

        retrieved = session_mgr.get_session("test_session_001")
        assert retrieved.session_name == ""

    def test_concurrent_create_session(self, session_mgr):
        """Test concurrent session creation."""
        import threading

        def create_session(i):
            session_data = SessionData(
                session_id=f"test_session_{i:03d}",
                session_name=f"Test Session {i}",
                task=f"Test task {i}"
            )
            session_mgr.create_session(session_data)

        threads = []
        for i in range(10):
            t = threading.Thread(target=create_session, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        sessions = session_mgr.list_sessions()
        assert len(sessions) == 10

    def test_session_persistence(self):
        """Test session persistence across instances using file-based SQLite."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name

        try:
            # Create first instance and add session
            mgr1 = SessionSQLAlchemy(f"sqlite:///{db_path}")
            session_data = SessionData(
                session_id="persistent_session",
                session_name="Persistent Session",
                task="Persistent task"
            )
            mgr1.create_session(session_data)

            # Create second instance pointing to same database
            mgr2 = SessionSQLAlchemy(f"sqlite:///{db_path}")
            assert mgr2.exists_session("persistent_session") is True

            retrieved = mgr2.get_session("persistent_session")
            assert retrieved.session_name == "Persistent Session"
        finally:
            os.unlink(db_path)

    def test_create_session_with_long_session_name(self, session_mgr):
        """Test creating session with very long name."""
        long_name = "A" * 1000
        session_data = SessionData(
            session_id="test_session_001",
            session_name=long_name,
            task="Test task"
        )
        session_mgr.create_session(session_data)

        retrieved = session_mgr.get_session("test_session_001")
        assert retrieved.session_name == long_name

    def test_list_sessions_empty_database(self, session_mgr):
        """Test listing sessions when database is empty."""
        sessions = session_mgr.list_sessions()
        assert sessions == []
        assert len(sessions) == 0

    def test_delete_session_cascade_messages(self, session_mgr):
        """Test that deleting session handles associated messages gracefully."""
        session_data = SessionData(
            session_id="test_session_001",
            session_name="Test Session",
            task="Test task"
        )
        session_mgr.create_session(session_data)

        # Delete session
        result = session_mgr.delete_session("test_session_001")
        assert result is True

        # Verify messages can still be retrieved without error
        messages = session_mgr.get_messages_by_session("test_session_001")
        assert isinstance(messages, list)

    def test_create_session_with_environment_paths(self, session_mgr):
        """Test creating session stores project workspace, pwd and topsailai home."""
        session_data = SessionData(
            session_id="test_session_001",
            session_name="Test Session",
            task="Test task",
            project_workspace="/workspace/project",
            pwd="/workspace/project/src",
            topsailai_home="/home/user/.topsailai"
        )
        session_mgr.create_session(session_data)

        retrieved = session_mgr.get_session("test_session_001")
        assert retrieved.project_workspace == "/workspace/project"
        assert retrieved.pwd == "/workspace/project/src"
        assert retrieved.topsailai_home == "/home/user/.topsailai"

    def test_create_session_environment_paths_optional(self, session_mgr):
        """Test that environment path fields default to None when omitted."""
        session_data = SessionData(
            session_id="test_session_001",
            session_name="Test Session",
            task="Test task"
        )
        session_mgr.create_session(session_data)

        retrieved = session_mgr.get_session("test_session_001")
        assert retrieved.project_workspace is None
        assert retrieved.pwd is None
        assert retrieved.topsailai_home is None

    def test_list_sessions_includes_environment_paths(self, session_mgr):
        """Test that list_sessions returns environment path fields."""
        session_data = SessionData(
            session_id="test_session_001",
            session_name="Test Session",
            task="Test task",
            project_workspace="/workspace/project",
            pwd="/workspace/project/src",
            topsailai_home="/home/user/.topsailai"
        )
        session_mgr.create_session(session_data)

        sessions = session_mgr.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].project_workspace == "/workspace/project"
        assert sessions[0].pwd == "/workspace/project/src"
        assert sessions[0].topsailai_home == "/home/user/.topsailai"

    def test_list_sessions_order_by_create_time_asc(self, session_mgr):
        """Test listing sessions sorted by create_time ascending."""
        for i in range(3):
            session_data = SessionData(
                session_id=f"test_session_{i:03d}",
                session_name=f"Test Session {i}",
                task=f"Test task {i}"
            )
            session_mgr.create_session(session_data)
            time.sleep(0.01)

        sessions = session_mgr.list_sessions(order_by="create_time")
        assert len(sessions) == 3
        assert sessions[0].session_id == "test_session_000"
        assert sessions[1].session_id == "test_session_001"
        assert sessions[2].session_id == "test_session_002"

    def test_list_sessions_order_by_create_time_desc(self, session_mgr):
        """Test listing sessions sorted by create_time descending."""
        for i in range(3):
            session_data = SessionData(
                session_id=f"test_session_{i:03d}",
                session_name=f"Test Session {i}",
                task=f"Test task {i}"
            )
            session_mgr.create_session(session_data)
            time.sleep(0.01)

        sessions = session_mgr.list_sessions(order_by="-create_time")
        assert len(sessions) == 3
        assert sessions[0].session_id == "test_session_002"
        assert sessions[1].session_id == "test_session_001"
        assert sessions[2].session_id == "test_session_000"

    def test_list_sessions_order_by_session_id(self, session_mgr):
        """Test listing sessions sorted by session_id."""
        for i in range(3):
            session_data = SessionData(
                session_id=f"test_session_{i:03d}",
                session_name=f"Test Session {i}",
                task=f"Test task {i}"
            )
            session_mgr.create_session(session_data)

        sessions = session_mgr.list_sessions(order_by="session_id")
        assert len(sessions) == 3
        assert sessions[0].session_id == "test_session_000"
        assert sessions[1].session_id == "test_session_001"
        assert sessions[2].session_id == "test_session_002"

    def test_list_sessions_order_by_session_id_desc(self, session_mgr):
        """Test listing sessions sorted by session_id descending."""
        for i in range(3):
            session_data = SessionData(
                session_id=f"test_session_{i:03d}",
                session_name=f"Test Session {i}",
                task=f"Test task {i}"
            )
            session_mgr.create_session(session_data)

        sessions = session_mgr.list_sessions(order_by="-session_id")
        assert len(sessions) == 3
        assert sessions[0].session_id == "test_session_002"
        assert sessions[1].session_id == "test_session_001"
        assert sessions[2].session_id == "test_session_000"

    def test_list_sessions_order_by_unsupported_field(self, session_mgr):
        """Test that ordering by an unsupported field raises ValueError."""
        session_data = SessionData(
            session_id="test_session_001",
            session_name="Test Session",
            task="Test task"
        )
        session_mgr.create_session(session_data)

        with pytest.raises(ValueError, match="Unsupported order_by field"):
            session_mgr.list_sessions(order_by="unsupported_field")

    def test_list_sessions_with_offset(self, session_mgr):
        """Test listing sessions with offset."""
        for i in range(3):
            session_data = SessionData(
                session_id=f"test_session_{i:03d}",
                session_name=f"Test Session {i}",
                task=f"Test task {i}"
            )
            session_mgr.create_session(session_data)
            time.sleep(0.01)

        sessions = session_mgr.list_sessions(order_by="create_time", offset=1)
        assert len(sessions) == 2
        assert sessions[0].session_id == "test_session_001"
        assert sessions[1].session_id == "test_session_002"

    def test_list_sessions_with_limit(self, session_mgr):
        """Test listing sessions with limit."""
        for i in range(3):
            session_data = SessionData(
                session_id=f"test_session_{i:03d}",
                session_name=f"Test Session {i}",
                task=f"Test task {i}"
            )
            session_mgr.create_session(session_data)
            time.sleep(0.01)

        sessions = session_mgr.list_sessions(order_by="create_time", limit=2)
        assert len(sessions) == 2
        assert sessions[0].session_id == "test_session_000"
        assert sessions[1].session_id == "test_session_001"

    def test_list_sessions_with_offset_and_limit(self, session_mgr):
        """Test listing sessions with offset and limit combined."""
        for i in range(5):
            session_data = SessionData(
                session_id=f"test_session_{i:03d}",
                session_name=f"Test Session {i}",
                task=f"Test task {i}"
            )
            session_mgr.create_session(session_data)
            time.sleep(0.01)

        sessions = session_mgr.list_sessions(order_by="create_time", offset=1, limit=2)
        assert len(sessions) == 2
        assert sessions[0].session_id == "test_session_001"
        assert sessions[1].session_id == "test_session_002"

    def test_list_sessions_combined_filter_order_offset_limit(self, session_mgr):
        """Test combined sessions filter, ordering, offset, and limit."""
        for i in range(5):
            session_data = SessionData(
                session_id=f"test_session_{i:03d}",
                session_name=f"Test Session {i}",
                task=f"Test task {i}"
            )
            session_mgr.create_session(session_data)
            time.sleep(0.01)

        sessions = session_mgr.list_sessions(
            sessions=["test_session_001", "test_session_002", "test_session_003", "test_session_004"],
            order_by="-session_id",
            offset=1,
            limit=2,
        )
        assert len(sessions) == 2
        assert sessions[0].session_id == "test_session_003"
        assert sessions[1].session_id == "test_session_002"

    def test_list_sessions_default_order_is_create_time_desc(self, session_mgr):
        """Test that default ordering is create_time descending."""
        for i in range(3):
            session_data = SessionData(
                session_id=f"test_session_{i:03d}",
                session_name=f"Test Session {i}",
                task=f"Test task {i}"
            )
            session_mgr.create_session(session_data)
            time.sleep(0.01)

        sessions = session_mgr.list_sessions()
        assert len(sessions) == 3
        assert sessions[0].session_id == "test_session_002"
        assert sessions[1].session_id == "test_session_001"
        assert sessions[2].session_id == "test_session_000"

    def test_list_sessions_offset_zero_returns_all(self, session_mgr):
        """Test that offset=0 returns all sessions."""
        for i in range(3):
            session_data = SessionData(
                session_id=f"test_session_{i:03d}",
                session_name=f"Test Session {i}",
                task=f"Test task {i}"
            )
            session_mgr.create_session(session_data)

        sessions = session_mgr.list_sessions(offset=0)
        assert len(sessions) == 3

    def test_list_sessions_limit_zero_returns_empty(self, session_mgr):
        """Test that limit=0 returns an empty list."""
        for i in range(3):
            session_data = SessionData(
                session_id=f"test_session_{i:03d}",
                session_name=f"Test Session {i}",
                task=f"Test task {i}"
            )
            session_mgr.create_session(session_data)

        sessions = session_mgr.list_sessions(limit=0)
        assert sessions == []

    def test_list_sessions_order_by_session_name(self, session_mgr):
        """Test listing sessions sorted by session_name."""
        session_data_1 = SessionData(
            session_id="s1",
            session_name="Charlie",
            task="task1"
        )
        session_data_2 = SessionData(
            session_id="s2",
            session_name="Alpha",
            task="task2"
        )
        session_data_3 = SessionData(
            session_id="s3",
            session_name="Bravo",
            task="task3"
        )
        session_mgr.create_session(session_data_1)
        session_mgr.create_session(session_data_2)
        session_mgr.create_session(session_data_3)

        sessions = session_mgr.list_sessions(order_by="session_name")
        assert len(sessions) == 3
        assert sessions[0].session_name == "Alpha"
        assert sessions[1].session_name == "Bravo"
        assert sessions[2].session_name == "Charlie"

    def test_list_sessions_order_by_task(self, session_mgr):
        """Test listing sessions sorted by task."""
        session_data_1 = SessionData(
            session_id="s1",
            session_name="Session 1",
            task="task_c"
        )
        session_data_2 = SessionData(
            session_id="s2",
            session_name="Session 2",
            task="task_a"
        )
        session_data_3 = SessionData(
            session_id="s3",
            session_name="Session 3",
            task="task_b"
        )
        session_mgr.create_session(session_data_1)
        session_mgr.create_session(session_data_2)
        session_mgr.create_session(session_data_3)

        sessions = session_mgr.list_sessions(order_by="task")
        assert len(sessions) == 3
        assert sessions[0].task == "task_a"
        assert sessions[1].task == "task_b"
        assert sessions[2].task == "task_c"


    def test_get_session_returns_token_totals(self, session_mgr):
        """Test that get_session returns accumulated token totals."""
        session_data = SessionData(
            session_id="token_session",
            session_name="Token Session",
            task="Token task",
        )
        session_mgr.create_session(session_data)
        session_mgr.accumulate_session_tokens(
            session_id="token_session",
            current_tokens=150,
            current_cached_tokens=75,
        )

        retrieved = session_mgr.get_session("token_session")
        assert retrieved.total_tokens == 150
        assert retrieved.total_cached_tokens == 75

    def test_list_sessions_returns_token_totals(self, session_mgr):
        """Test that list_sessions returns accumulated token totals."""
        session_data = SessionData(
            session_id="token_session",
            session_name="Token Session",
            task="Token task",
        )
        session_mgr.create_session(session_data)
        session_mgr.accumulate_session_tokens(
            session_id="token_session",
            current_tokens=200,
            current_cached_tokens=100,
        )

        sessions = session_mgr.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].total_tokens == 200
        assert sessions[0].total_cached_tokens == 100

    def test_token_totals_persist_across_instances(self):
        """Test that token totals persist when reopening the database."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name

        try:
            mgr1 = SessionSQLAlchemy(f"sqlite:///{db_path}")
            session_data = SessionData(
                session_id="persistent_token_session",
                session_name="Persistent Token Session",
                task="Persistent token task",
            )
            mgr1.create_session(session_data)
            mgr1.accumulate_session_tokens(
                session_id="persistent_token_session",
                current_tokens=300,
                current_cached_tokens=150,
            )

            mgr2 = SessionSQLAlchemy(f"sqlite:///{db_path}")
            retrieved = mgr2.get_session("persistent_token_session")
            assert retrieved.total_tokens == 300
            assert retrieved.total_cached_tokens == 150

            sessions = mgr2.list_sessions()
            assert len(sessions) == 1
            assert sessions[0].total_tokens == 300
            assert sessions[0].total_cached_tokens == 150
        finally:
            os.unlink(db_path)


class TestSessionTokenAccumulation:
    """Test suite for session token accumulation via accumulate_session_tokens."""

    @pytest.fixture
    def session_mgr(self):
        """Create a fresh in-memory session manager for each test."""
        return SessionSQLAlchemy("sqlite:///:memory:")

    def _create_session(self, session_mgr, session_id="token_session"):
        """Helper to create a session for token tests."""
        session_data = SessionData(
            session_id=session_id,
            session_name="Token Session",
            task="Token task",
        )
        session_mgr.create_session(session_data)

    def test_token_columns_exist_after_ensure_columns(self, session_mgr):
        """Test that prompt, cached-prompt, and completion columns exist."""
        with session_mgr.engine.connect() as conn:
            result = conn.execute(
                text("SELECT name FROM pragma_table_info('session')")
            )
            column_names = {row[0] for row in result.fetchall()}

        assert "total_tokens" in column_names
        assert "total_cached_tokens" in column_names
        assert "total_completion_tokens" in column_names

    def test_accumulate_session_tokens_increments_totals(self, session_mgr):
        """Test accumulate_session_tokens increments totals correctly."""
        self._create_session(session_mgr)

        result = session_mgr.accumulate_session_tokens(
            session_id="token_session",
            current_tokens=100,
            current_cached_tokens=50,
        )
        assert result is True

        # SessionData does not expose token fields; query the ORM model directly.
        with session_mgr.SessionLocal() as db_session:
            row = db_session.query(Session).filter(Session.session_id == "token_session").first()
            assert row.total_tokens == 100
            assert row.total_cached_tokens == 50

    def test_accumulate_session_tokens_multiple_times(self, session_mgr):
        """Test multiple accumulations sum as expected."""
        self._create_session(session_mgr)

        deltas = [
            (10, 5),
            (20, 8),
            (30, 12),
        ]
        for tokens, cached in deltas:
            result = session_mgr.accumulate_session_tokens(
                session_id="token_session",
                current_tokens=tokens,
                current_cached_tokens=cached,
            )
            assert result is True

        with session_mgr.SessionLocal() as db_session:
            row = db_session.query(Session).filter(Session.session_id == "token_session").first()
            assert row.total_tokens == 60
            assert row.total_cached_tokens == 25

    def test_accumulate_session_tokens_missing_session(self, session_mgr):
        """Test accumulate_session_tokens returns False for missing session."""
        result = session_mgr.accumulate_session_tokens(
            session_id="missing_session",
            current_tokens=10,
            current_cached_tokens=5,
        )
        assert result is False

    def test_accumulate_session_tokens_negative_deltas_normalized(self, session_mgr):
        """Test negative deltas are normalized to zero."""
        self._create_session(session_mgr)

        result = session_mgr.accumulate_session_tokens(
            session_id="token_session",
            current_tokens=-100,
            current_cached_tokens=-50,
        )
        assert result is True

        with session_mgr.SessionLocal() as db_session:
            row = db_session.query(Session).filter(Session.session_id == "token_session").first()
            assert row.total_tokens == 0
            assert row.total_cached_tokens == 0

    def test_accumulate_session_tokens_zero_deltas(self, session_mgr):
        """Test zero deltas leave totals unchanged."""
        self._create_session(session_mgr)

        session_mgr.accumulate_session_tokens(
            session_id="token_session",
            current_tokens=50,
            current_cached_tokens=20,
        )
        result = session_mgr.accumulate_session_tokens(
            session_id="token_session",
            current_tokens=0,
            current_cached_tokens=0,
        )
        assert result is True

        with session_mgr.SessionLocal() as db_session:
            row = db_session.query(Session).filter(Session.session_id == "token_session").first()
            assert row.total_tokens == 50
            assert row.total_cached_tokens == 20

    def test_accumulate_session_tokens_empty_session_id(self, session_mgr):
        """Test accumulate_session_tokens returns False for empty session_id."""
        self._create_session(session_mgr)

        result = session_mgr.accumulate_session_tokens(
            session_id="",
            current_tokens=10,
            current_cached_tokens=5,
        )
        assert result is False

    def test_accumulate_session_tokens_multiple_agents(self, session_mgr):
        """Test that multiple agents' deltas accumulate rather than overwrite."""
        self._create_session(session_mgr)

        # Simulate two agents contributing token deltas independently.
        session_mgr.accumulate_session_tokens(
            session_id="token_session",
            current_tokens=100,
            current_cached_tokens=40,
        )
        session_mgr.accumulate_session_tokens(
            session_id="token_session",
            current_tokens=60,
            current_cached_tokens=20,
        )

        with session_mgr.SessionLocal() as db_session:
            row = db_session.query(Session).filter(Session.session_id == "token_session").first()
            assert row.total_tokens == 160
            assert row.total_cached_tokens == 60

    def test_get_session_token_totals_returns_values(self, session_mgr):
        """Test get_session_token_totals reads accumulated totals."""
        self._create_session(session_mgr)
        session_mgr.accumulate_session_tokens(
            session_id="token_session",
            current_tokens=100,
            current_cached_tokens=50,
        )

        totals = session_mgr.get_session_token_totals("token_session")

        assert totals == (100, 50)

    def test_get_session_token_totals_multiple_accumulations(self, session_mgr):
        """Test get_session_token_totals reflects multiple accumulations."""
        self._create_session(session_mgr)
        session_mgr.accumulate_session_tokens(
            session_id="token_session",
            current_tokens=80,
            current_cached_tokens=30,
        )
        session_mgr.accumulate_session_tokens(
            session_id="token_session",
            current_tokens=20,
            current_cached_tokens=10,
        )

        totals = session_mgr.get_session_token_totals("token_session")

        assert totals == (100, 40)

    def test_get_session_token_totals_missing_session(self, session_mgr):
        """Test get_session_token_totals returns None for missing session."""
        totals = session_mgr.get_session_token_totals("missing_session")

        assert totals is None

    def test_get_session_token_totals_empty_session_id(self, session_mgr):
        """Test get_session_token_totals returns None for empty session_id."""
        self._create_session(session_mgr)

        totals = session_mgr.get_session_token_totals("")

        assert totals is None


    def test_explicit_session_usage_preserves_legacy_prompt_total(self, session_mgr):
        """Accumulate completion separately while preserving the legacy tuple API."""
        self._create_session(session_mgr)

        session_mgr.accumulate_session_tokens(
            session_id="token_session",
            current_tokens=100,
            current_cached_tokens=40,
            current_completion_tokens=25,
        )

        assert session_mgr.get_session_token_totals("token_session") == (100, 40)
        assert session_mgr.get_session_token_usage("token_session") == {
            "total_prompt_tokens": 100,
            "total_completion_tokens": 25,
            "total_usage_tokens": 125,
            "total_cached_tokens": 40,
        }
        session_data = session_mgr.get_session("token_session")
        assert session_data.total_tokens == 100
        assert session_data.total_completion_tokens == 25
        assert session_data.total_usage_tokens == 125

    def test_completion_tokens_accumulate_across_requests(self, session_mgr):
        """Accumulate completion deltas from multiple requests atomically."""
        self._create_session(session_mgr)

        session_mgr.accumulate_session_tokens(
            "token_session", 80, 20, current_completion_tokens=12
        )
        session_mgr.accumulate_session_tokens(
            "token_session", 20, 5, current_completion_tokens=8
        )

        usage = session_mgr.get_session_token_usage("token_session")
        assert usage["total_prompt_tokens"] == 100
        assert usage["total_completion_tokens"] == 20
        assert usage["total_usage_tokens"] == 120
        assert usage["total_cached_tokens"] == 25

    def test_existing_sqlite_schema_gains_completion_column(self, tmp_path):
        """Add the completion column without reinterpreting historical totals."""
        db_path = tmp_path / "legacy-session.db"
        from sqlalchemy import create_engine

        engine = create_engine(f"sqlite:///{db_path}")
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE session ("
                "id INTEGER PRIMARY KEY, session_id TEXT UNIQUE, task TEXT, "
                "session_name TEXT, total_tokens INTEGER DEFAULT 0, "
                "total_cached_tokens INTEGER DEFAULT 0, create_time DATETIME)"
            ))
            conn.execute(text(
                "INSERT INTO session (session_id, task, total_tokens, "
                "total_cached_tokens, create_time) "
                "VALUES ('legacy', 'legacy task', 90, 30, CURRENT_TIMESTAMP)"
            ))
        engine.dispose()

        migrated = SessionSQLAlchemy(f"sqlite:///{db_path}")
        try:
            usage = migrated.get_session_token_usage("legacy")
            assert usage == {
                "total_prompt_tokens": 90,
                "total_completion_tokens": 0,
                "total_usage_tokens": 90,
                "total_cached_tokens": 30,
            }
        finally:
            migrated.engine.dispose()


class TestSessionUpdateTime:
    """Test session-row update_time semantics."""

    @pytest.fixture
    def session_mgr(self):
        """Create an in-memory manager for update_time tests."""
        return SessionSQLAlchemy("sqlite:///:memory:")

    def test_create_and_read_exposes_update_time(self, session_mgr):
        """Creation initializes update_time and read mappings expose it."""
        session_mgr.create_session(SessionData(session_id="update_time", task="task"))
        session = session_mgr.get_session("update_time")
        listed = session_mgr.list_sessions()[0]

        assert session.update_time == session.create_time
        assert listed.update_time == session.update_time
        assert Session.update_time.type.__class__ is Session.create_time.type.__class__
        assert Session.update_time.nullable is False
        assert str(Session.update_time.server_default.arg).upper() == "CURRENT_TIMESTAMP"

    def test_changed_name_updates_timestamp_but_identical_name_does_not(self, session_mgr):
        """Only an actual session-name change advances update_time."""
        data = SessionData(session_id="update_name", session_name="old", task="task")
        data.create_time = datetime(2020, 1, 1, 0, 0, 0)
        session_mgr.create_session(data)
        original = session_mgr.get_session("update_name").update_time

        assert session_mgr.update_session_name("update_name", "old") is True
        assert session_mgr.get_session("update_name").update_time == original

        new_time = datetime(2030, 1, 1, 0, 0, 1)
        with patch.object(session_sql, "datetime") as mocked_datetime:
            mocked_datetime.now.return_value = new_time
            assert session_mgr.update_session_name("update_name", "new") is True
        assert session_mgr.get_session("update_name").update_time == new_time

    def test_token_update_changes_timestamp_but_zero_delta_does_not(self, session_mgr):
        """Raw token updates advance time only for non-zero normalized deltas."""
        data = SessionData(session_id="token_time", task="task")
        data.create_time = datetime(2020, 1, 1, 0, 0, 0)
        session_mgr.create_session(data)
        original = session_mgr.get_session("token_time").update_time

        assert session_mgr.accumulate_session_tokens("token_time", 0, -1, -2) is True
        assert session_mgr.get_session("token_time").update_time == original

        new_time = datetime(2030, 1, 1, 0, 0, 1)
        with patch.object(session_sql, "datetime") as mocked_datetime:
            mocked_datetime.now.return_value = new_time
            assert session_mgr.accumulate_session_tokens("token_time", 1, 0, 0) is True
        updated = session_mgr.get_session("token_time").update_time
        assert updated == new_time
        assert session_mgr.get_session("token_time").total_tokens == 1


    def test_transaction_rollback_preserves_update_time(self, session_mgr):
        """A failed session-row update leaves the fixed old timestamp unchanged."""
        old_time = datetime(2020, 1, 1, 0, 0, 0)
        data = SessionData(session_id="rollback_time", task="task")
        data.create_time = old_time
        session_mgr.create_session(data)
        with patch.object(session_sql, "datetime", side_effect=RuntimeError("clock")):
            assert session_mgr.update_session_name("rollback_time", "new") is False
        session = session_mgr.get_session("rollback_time")
        assert session.session_name is None
        assert session.update_time == old_time

    def _sqlite_snapshot(self, connection, expected_columns=None, include_update_time=True):
        """Capture the selected session schema, indexes, triggers, and rows for comparison."""
        all_columns = tuple(connection.execute(text(
            "PRAGMA table_info(\"session\")"
        )).fetchall())
        selected_names = expected_columns or tuple(row[1] for row in all_columns)
        allowed_names = set(selected_names)
        if include_update_time:
            allowed_names.add("update_time")
        columns = tuple(row for row in all_columns if row[1] in allowed_names)
        foreign_keys = tuple(connection.execute(text(
            "PRAGMA foreign_key_list(\"session\")"
        )).fetchall())
        indexes = []
        for row in connection.execute(text("PRAGMA index_list(\"session\")")).fetchall():
            index_name, unique, origin, partial = row[1], row[2], row[3], row[4]
            index_columns = tuple(item[2] for item in connection.execute(text(
                f"PRAGMA index_info(\"{index_name.replace(chr(34), chr(34) * 2)}\")"
            )).fetchall())
            index_sql = connection.execute(text(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = :name"
            ), {"name": index_name}).scalar_one_or_none()
            indexes.append((index_name, index_sql, unique, origin, partial, index_columns))
        triggers = tuple(connection.execute(text(
            "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' "
            "AND tbl_name = 'session' ORDER BY name"
        )).fetchall())
        projection = ", ".join(f'"{column}"' for column in selected_names)
        ordering = ", ".join(f'"{column}"' for column in selected_names)
        rows = tuple(connection.execute(text(
            f"SELECT {projection} FROM session ORDER BY {ordering}"
        )).fetchall())
        return columns, foreign_keys, tuple(sorted(indexes)), triggers, rows

    def _without_update_time(self, snapshot):
        """Remove the migration-added column from a schema snapshot."""
        columns, foreign_keys, indexes, triggers, rows = snapshot
        return tuple(row for row in columns if row[1] != "update_time"), foreign_keys, indexes, triggers, rows


    def test_sqlite_migration_backfills_and_is_idempotent(self, tmp_path):
        """Legacy rows use create_time as the backfill and repeat unchanged."""
        from sqlalchemy import create_engine
        path = tmp_path / "backfill.db"
        engine = create_engine(f"sqlite:///{path}")
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE session (session_id TEXT PRIMARY KEY, task TEXT NOT NULL, "
                "create_time DATETIME NOT NULL)"
            ))
            connection.execute(text(
                "INSERT INTO session VALUES ('legacy', 'task', '2020-01-01 00:00:00')"
            ))
        engine.dispose()
        manager = SessionSQLAlchemy(f"sqlite:///{path}")
        with manager.engine.connect() as connection:
            first = self._sqlite_snapshot(connection)
            row = connection.execute(text(
                "SELECT create_time, update_time FROM session WHERE session_id='legacy'"
            )).one()
            assert row[0] == row[1]
        manager.engine.dispose()
        manager = SessionSQLAlchemy(f"sqlite:///{path}")
        with manager.engine.connect() as connection:
            second = self._sqlite_snapshot(connection)
            assert second == first
            assert connection.execute(text(
                "SELECT count(*) FROM sqlite_master WHERE name='session__update_time_new'"
            )).scalar() == 0
        manager.engine.dispose()

    def test_sqlite_migration_preserves_constraints_indexes_and_data(self, tmp_path):
        """A rebuild preserves complete schema, index, trigger, and row inventories."""
        from sqlalchemy import create_engine
        path = tmp_path / "preserve.db"
        engine = create_engine(f"sqlite:///{path}")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE owner (id INTEGER PRIMARY KEY)"))
            connection.execute(text(
                "CREATE TABLE session (session_id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL, "
                "task TEXT NOT NULL, create_time DATETIME NOT NULL, "
                "UNIQUE(task), CHECK(length(task) > 0), "
                "FOREIGN KEY(owner_id) REFERENCES owner(id))"
            ))
            connection.execute(text("CREATE INDEX session_task_explicit ON session(task)"))
            connection.execute(text("CREATE TABLE session_audit (session_id TEXT)"))
            connection.execute(text(
                "CREATE TRIGGER session_audit_trigger AFTER UPDATE OF task ON session "
                "BEGIN INSERT INTO session_audit VALUES (NEW.session_id); END"
            ))
            connection.execute(text("INSERT INTO owner VALUES (1)"))
            connection.execute(text(
                "INSERT INTO session VALUES ('legacy', 1, 'task', '2020-01-01 00:00:00')"
            ))
        with engine.connect() as connection:
            before_columns = tuple(row[1] for row in connection.execute(text(
                "PRAGMA table_info(\"session\")"
            )).fetchall())
            before = self._sqlite_snapshot(connection, before_columns, include_update_time=False)
        engine.dispose()
        manager = SessionSQLAlchemy(f"sqlite:///{path}")
        with manager.engine.connect() as connection:
            after = self._sqlite_snapshot(connection, before_columns)
            assert tuple(row for row in after[0] if row[1] != "update_time") == before[0]
            assert after[1:] == before[1:]
            assert any(item[3] == "u" and item[5] == ("task",) for item in after[2])
            assert any(item[1] is not None and item[0] == "session_task_explicit" for item in after[2])
            assert after[3]
            assert after[4] == (("legacy", 1, "task", "2020-01-01 00:00:00"),)
            assert connection.execute(text(
                "SELECT update_time = create_time FROM session"
            )).scalar() == 1
        manager.engine.dispose()

    def test_sqlite_migration_failure_then_retry_is_safe(self, tmp_path):
        """An interrupted copy preserves exception, FK mode, schema, and retry data."""
        from sqlalchemy import create_engine
        path = tmp_path / "retry.db"
        engine = create_engine(f"sqlite:///{path}")
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE session (session_id TEXT PRIMARY KEY, task TEXT, create_time DATETIME)"
            ))
            connection.execute(text(
                "INSERT INTO session VALUES ('legacy', 'task', '2020-01-01 00:00:00')"
            ))
        manager = SessionSQLAlchemy.__new__(SessionSQLAlchemy)
        manager.engine = engine
        injected = KeyboardInterrupt("copy interrupted")
        original_ddl = None
        with engine.connect() as connection:
            original_ddl = connection.execute(text(
                "SELECT sql FROM sqlite_master WHERE name='session'"
            )).scalar_one()
            original_fk = connection.execute(text("PRAGMA foreign_keys")).scalar()
            def fail_copy(_connection, cursor, statement, parameters, context, executemany):
                """Interrupt the replacement row copy once."""
                if "INSERT INTO \"session__update_time_new\"" in statement:
                    raise injected
            event.listen(engine, "before_cursor_execute", fail_copy)
            with pytest.raises(KeyboardInterrupt) as caught:
                manager._rebuild_sqlite_session_table(connection)
            event.remove(engine, "before_cursor_execute", fail_copy)
            assert caught.value is injected
            assert connection.execute(text("PRAGMA foreign_keys")).scalar() == original_fk
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT sql FROM sqlite_master WHERE name='session'"
            )).scalar_one() == original_ddl
            assert connection.execute(text(
                "SELECT count(*) FROM sqlite_master WHERE name='session__update_time_new'"
            )).scalar() == 0
            assert connection.execute(text("SELECT task FROM session")).scalar() == "task"
            manager._rebuild_sqlite_session_table(connection)
            row = connection.execute(text(
                "SELECT create_time, update_time FROM session"
            )).one()
            assert row[0] == row[1]
        engine.dispose()

    def test_sqlite_migration_quoted_and_constrained_tables(self, tmp_path):
        """Quoted names and a table-level UNIQUE constraint preserve data and indexes."""
        from sqlalchemy import create_engine
        for name, ddl in (
            ("quoted", 'CREATE TABLE "session" (session_id TEXT PRIMARY KEY, task TEXT, create_time DATETIME)'),
            ("unique", 'CREATE TABLE session (session_id TEXT PRIMARY KEY, task TEXT, create_time DATETIME, UNIQUE(task))'),
        ):
            path = tmp_path / f"{name}.db"
            engine = create_engine(f"sqlite:///{path}")
            with engine.begin() as connection:
                connection.execute(text(ddl))
                connection.execute(text(
                    "INSERT INTO session VALUES ('legacy', 'task', '2020-01-01 00:00:00')"
                ))
            engine.dispose()
            manager = SessionSQLAlchemy(f"sqlite:///{path}")
            with manager.engine.connect() as connection:
                assert connection.execute(text(
                    "SELECT update_time = create_time FROM session"
                )).scalar() == 1
                assert connection.execute(text("SELECT task FROM session")).scalar() == "task"
                if name == "unique":
                    indexes = connection.execute(text("PRAGMA index_list(\"session\")")).fetchall()
                    assert any(row[2] == 1 and row[3] == "u" for row in indexes)
                    unique_name = next(row[1] for row in indexes if row[2] == 1 and row[3] == "u")
                    assert tuple(row[2] for row in connection.execute(
                        text(f"PRAGMA index_info(\"{unique_name}\")")
                    ).fetchall()) == ("task",)
            manager.engine.dispose()

    def test_sqlite_unsupported_ddl_fails_closed(self, tmp_path):
        """The real initializer rejects unsupported DDL without mutation."""
        from sqlalchemy import create_engine
        ddls = (
            ("without", "CREATE TABLE session (session_id TEXT PRIMARY KEY, task TEXT, create_time TEXT) WITHOUT ROWID"),
            ("strict", "CREATE TABLE session (session_id TEXT PRIMARY KEY, task TEXT, create_time TEXT) STRICT"),
            ("generated", "CREATE TABLE session (session_id TEXT PRIMARY KEY, task TEXT, create_time DATETIME, derived TEXT AS (task))"),
        )
        for name, ddl in ddls:
            path = tmp_path / f"{name}.db"
            engine = create_engine(f"sqlite:///{path}")
            with engine.begin() as connection:
                connection.execute(text(ddl))
                connection.execute(text(
                    "INSERT INTO session(session_id, task, create_time) VALUES ('legacy', 'task', '2020-01-01 00:00:00')"
                ))
            with engine.connect() as connection:
                before = self._sqlite_snapshot(connection)
                before_schema = tuple(connection.execute(text(
                    "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
                )).fetchall())
            engine.dispose()
            with pytest.raises(RuntimeError, match="Unsupported") as raised:
                SessionSQLAlchemy(f"sqlite:///{path}")
            assert "Unsupported" in str(raised.value)
            check_engine = create_engine(f"sqlite:///{path}")
            with check_engine.connect() as connection:
                after_schema = tuple(connection.execute(text(
                    "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
                )).fetchall())
                assert after_schema == before_schema
                assert self._sqlite_snapshot(connection) == before
            check_engine.dispose()

    def test_sqlite_migration_restores_foreign_keys_after_failure(self, tmp_path):
        """Failure after FK disabling restores the original connection setting."""
        from sqlalchemy import create_engine
        for enabled in (0, 1):
            path = tmp_path / f"foreign-keys-{enabled}.db"
            engine = create_engine(f"sqlite:///{path}")
            with engine.begin() as connection:
                connection.execute(text(
                    "CREATE TABLE session (session_id TEXT PRIMARY KEY, task TEXT, create_time DATETIME)"
                ))
            manager = SessionSQLAlchemy.__new__(SessionSQLAlchemy)
            manager.engine = engine
            with engine.connect() as connection:
                connection.execute(text(f"PRAGMA foreign_keys = {enabled}"))
                connection.commit()
                original = connection.execute(text("PRAGMA foreign_keys")).scalar()
                def fail_rebuild(_connection, cursor, statement, parameters, context, executemany):
                    """Fail after the migration has disabled foreign keys."""
                    if "CREATE TABLE \"session__update_time_new\"" in statement:
                        raise RuntimeError("rebuild")
                event.listen(engine, "before_cursor_execute", fail_rebuild)
                with pytest.raises(RuntimeError, match="rebuild"):
                    manager._rebuild_sqlite_session_table(connection)
                event.remove(engine, "before_cursor_execute", fail_rebuild)
                assert connection.execute(text("PRAGMA foreign_keys")).scalar() == original
            engine.dispose()

    def test_message_only_changes_leave_update_time_unchanged(self, session_mgr):
        """Message-store writes do not change the session-row timestamp."""
        old_time = datetime(2020, 1, 1, 0, 0, 0)
        data = SessionData(session_id="message_time", task="task")
        data.create_time = old_time
        session_mgr.create_session(data)
        before = session_mgr.get_session("message_time").update_time
        session_mgr.chat_history.add_message(ChatHistoryMessageData("message", "message-id", "message_time"))
        assert session_mgr.get_session("message_time").update_time == before
