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

from sqlalchemy import text

from topsailai.context.session_manager.sql import SessionSQLAlchemy, SessionData, Session


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
        """Test that total_tokens and total_cached_tokens columns exist."""
        with session_mgr.engine.connect() as conn:
            result = conn.execute(
                text("SELECT name FROM pragma_table_info('session')")
            )
            column_names = {row[0] for row in result.fetchall()}

        assert "total_tokens" in column_names
        assert "total_cached_tokens" in column_names

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
