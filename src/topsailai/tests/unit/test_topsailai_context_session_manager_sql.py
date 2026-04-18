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
from unittest.mock import patch

workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)
    sys.path.insert(0, workspace_root + "/src")
from topsailai.context.session_manager.sql import SessionSQLAlchemy, SessionData

class TestSessionSQLAlchemy:
    @pytest.fixture
    def db_conn(self):
        return "sqlite:///:memory:"

    @pytest.fixture
    def manager(self, db_conn):
        return SessionSQLAlchemy(db_conn)

    def test_create_session_basic(self, manager):
        # Create a session
        session_data = SessionData("session1", "Test task")
        session_data.session_name = "Test Session"
        manager.create_session(session_data)

        # Verify it was created
        sessions = manager.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].session_id == "session1"
        assert sessions[0].task == "Test task"
        assert sessions[0].session_name == "Test Session"
        assert sessions[0].create_time is not None

    def test_create_session_session_limit(self, manager):
        # Create 105 sessions
        for i in range(105):
            session_data = SessionData(f"session{i}", f"Task {i}")
            session_data.session_name = f"Session {i}"
            manager.create_session(session_data)

        # Verify only 100 sessions remain (the most recent ones)
        sessions = manager.list_sessions()
        assert len(sessions) == 100

        # Check that the oldest ones (0-4) are gone and newest ones (5-104) remain
        session_ids = {session.session_id for session in sessions}
        # Sessions 0-4 should not be present
        assert "session0" not in session_ids
        assert "session1" not in session_ids
        assert "session2" not in session_ids
        assert "session3" not in session_ids
        assert "session4" not in session_ids
        # Sessions 5-104 should be present
        assert "session5" in session_ids
        assert "session100" in session_ids
        assert "session104" in session_ids

    def test_list_sessions_empty(self, manager):
        sessions = manager.list_sessions()
        assert sessions == []

    def test_list_sessions_ordering(self, manager):
        # Create sessions with different creation times (simulated by creating them in order)
        import time
        for i in range(5):
            session_data = SessionData(f"session{i}", f"Task {i}")
            manager.create_session(session_data)
            time.sleep(0.01)  # Small delay to ensure different timestamps

        sessions = manager.list_sessions()
        assert len(sessions) == 5
        # Should be ordered by create_time descending (newest first)
        assert sessions[0].session_id == "session4"
        assert sessions[1].session_id == "session3"
        assert sessions[2].session_id == "session2"
        assert sessions[3].session_id == "session1"
        assert sessions[4].session_id == "session0"

    def test_create_session_without_name(self, manager):
        # Create session without session_name
        session_data = SessionData("session1", "Test task")
        manager.create_session(session_data)

        sessions = manager.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].session_name is None

    def test_create_session_duplicate_id(self, manager):
        # Create first session
        session_data1 = SessionData("session1", "Task 1")
        manager.create_session(session_data1)

        # Try to create another with same ID (should raise error due to primary key constraint)
        session_data2 = SessionData("session1", "Task 2")
        with pytest.raises(Exception):  # SQLAlchemy IntegrityError
            manager.create_session(session_data2)

        # Should still have only one session
        sessions = manager.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].task == "Task 1"

    def test_list_sessions_with_limit(self, manager):
        # Create 10 sessions
        for i in range(10):
            session_data = SessionData(f"session{i}", f"Task {i}")
            manager.create_session(session_data)

        # Test with limit=5
        sessions = manager.list_sessions(limit=5)
        assert len(sessions) == 5
        # Should return the 5 most recent sessions (9,8,7,6,5)
        expected_ids = ["session9", "session8", "session7", "session6", "session5"]
        for i, session in enumerate(sessions):
            assert session.session_id == expected_ids[i]

    def test_list_sessions_with_offset(self, manager):
        # Create 10 sessions
        for i in range(10):
            session_data = SessionData(f"session{i}", f"Task {i}")
            manager.create_session(session_data)

        # Test with offset=3
        sessions = manager.list_sessions(offset=3)
        assert len(sessions) == 7  # Should return sessions 6,5,4,3,2,1,0
        # Should skip the 3 most recent sessions (9,8,7)
        expected_ids = ["session6", "session5", "session4", "session3", "session2", "session1", "session0"]
        for i, session in enumerate(sessions):
            assert session.session_id == expected_ids[i]

    def test_list_sessions_with_offset_and_limit(self, manager):
        # Create 10 sessions
        for i in range(10):
            session_data = SessionData(f"session{i}", f"Task {i}")
            manager.create_session(session_data)

        # Test with offset=2, limit=3
        sessions = manager.list_sessions(offset=2, limit=3)
        assert len(sessions) == 3
        # Should skip 2 most recent (9,8) and return next 3 (7,6,5)
        expected_ids = ["session7", "session6", "session5"]
        for i, session in enumerate(sessions):
            assert session.session_id == expected_ids[i]

    def test_list_sessions_backward_compatibility(self, manager):
        # Create 3 sessions
        for i in range(3):
            session_data = SessionData(f"session{i}", f"Task {i}")
            manager.create_session(session_data)

        # Test that calling without parameters still works (backward compatibility)
        sessions = manager.list_sessions()
        assert len(sessions) == 3
        # Should return all sessions in descending order
        expected_ids = ["session2", "session1", "session0"]
        for i, session in enumerate(sessions):
            assert session.session_id == expected_ids[i]

    def test_list_sessions_edge_cases(self, manager):
        # Create 3 sessions
        for i in range(3):
            session_data = SessionData(f"session{i}", f"Task {i}")
            manager.create_session(session_data)

        # Test with offset=0 (should return all)
        sessions = manager.list_sessions(offset=0)
        assert len(sessions) == 3

        # Test with limit=0 (should return empty list)
        sessions = manager.list_sessions(limit=0)
        assert len(sessions) == 0

        # Test with offset beyond available sessions (should return empty list)
        sessions = manager.list_sessions(offset=10)
        assert len(sessions) == 0

        # Test with limit larger than available sessions
        sessions = manager.list_sessions(limit=10)
        assert len(sessions) == 3

    def test_clean_sessions_basic(self, manager):
        # Create 5 sessions
        for i in range(5):
            session_data = SessionData(f"session{i}", f"Task {i}")
            manager.create_session(session_data)

        # Verify all sessions exist
        sessions = manager.list_sessions()
        assert len(sessions) == 5

        # Clean sessions older than 1 second (should delete none since all are recent)
        deleted_count = manager.clean_sessions(before_seconds=1)
        assert deleted_count == 0

        # Verify all sessions still exist
        sessions = manager.list_sessions()
        assert len(sessions) == 5

    def test_clean_sessions_with_old_sessions(self, manager, monkeypatch):
        # Create 3 sessions with different creation times

        current_time = datetime.now()

        # Create first session (old - 1 hour ago)
        with patch('topsailai.context.session_manager.sql.datetime') as mock_datetime:
            mock_datetime.now.return_value = current_time - timedelta(hours=1)
            session_data = SessionData("session_old", "Old task")
            session_data.create_time = mock_datetime.now.return_value
            manager.create_session(session_data)

        # Create second session (medium - 30 minutes ago)
        with patch('topsailai.context.session_manager.sql.datetime') as mock_datetime:
            mock_datetime.now.return_value = current_time - timedelta(minutes=30)
            session_data = SessionData("session_medium", "Medium task")
            session_data.create_time = mock_datetime.now.return_value
            manager.create_session(session_data)

        # Create third session (recent - now)
        session_data = SessionData("session_recent", "Recent task")
        manager.create_session(session_data)

        # Verify all sessions exist
        sessions = manager.list_sessions()
        assert len(sessions) == 3

        # Clean sessions older than 45 minutes (should delete only the old session)
        deleted_count = manager.clean_sessions(before_seconds=45*60)  # 45 minutes in seconds
        assert deleted_count == 1

        # Verify only recent and medium sessions remain
        sessions = manager.list_sessions()
        assert len(sessions) == 2
        session_ids = {session.session_id for session in sessions}
        assert "session_old" not in session_ids
        assert "session_medium" in session_ids
        assert "session_recent" in session_ids

    def test_clean_sessions_all_old(self, manager):
        # Create 3 old sessions using the same approach

        current_time = datetime.now()

        # Create sessions from 2 hours ago
        with patch('topsailai.context.session_manager.sql.datetime') as mock_datetime:
            mock_datetime.now.return_value = current_time - timedelta(hours=2)
            for i in range(3):
                session_data = SessionData(f"session_old_{i}", f"Old task {i}")
                session_data.create_time = mock_datetime.now.return_value
                manager.create_session(session_data)

        # Verify all sessions exist
        sessions = manager.list_sessions()
        assert len(sessions) == 3

        # Clean sessions older than 1 hour (should delete all)
        deleted_count = manager.clean_sessions(before_seconds=60*60)  # 1 hour in seconds
        assert deleted_count == 3

        # Verify no sessions remain
        sessions = manager.list_sessions()
        assert len(sessions) == 0

    def test_clean_sessions_edge_cases(self, manager):
        # Test cleaning when no sessions exist
        deleted_count = manager.clean_sessions(before_seconds=3600)
        assert deleted_count == 0

        # Create one session
        session_data = SessionData("session1", "Task 1")
        manager.create_session(session_data)

        # Test with very large before_seconds (should not delete recent session)
        deleted_count = manager.clean_sessions(before_seconds=999999999)
        assert deleted_count == 0

        # Test with before_seconds=0 (should delete nothing since create_time >= now)
        deleted_count = manager.clean_sessions(before_seconds=0)
        assert deleted_count == 0
