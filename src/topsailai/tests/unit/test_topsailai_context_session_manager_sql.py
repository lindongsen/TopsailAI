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

from topsailai.context.session_manager.sql import SessionSQLAlchemy, SessionData


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
