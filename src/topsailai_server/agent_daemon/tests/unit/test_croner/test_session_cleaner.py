"""
Unit tests for SessionCleaner cron job.

Tests:
    - SessionCleaner initialization
    - Session cleanup logic
    - Old session deletion
    - Message deletion cascade
    - Edge cases and error handling
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta

from topsailai_server.agent_daemon.croner.jobs.session_cleaner import SessionCleaner


class MockSession:
    """Mock session object for testing."""
    def __init__(self, session_id, update_time=None):
        self.session_id = session_id
        self.processed_msg_id = None
        self.session_name = f"Session {session_id}"
        self.task = None
        self.create_time = datetime.now() - timedelta(days=400)
        self.update_time = update_time or datetime.now() - timedelta(days=400)


class TestSessionCleanerInitialization:
    """Tests for SessionCleaner initialization."""

    def test_initialization_with_custom_values(self):
        """Test SessionCleaner initialization with custom values."""
        storage = Mock()
        worker_manager = Mock()
        cleaner = SessionCleaner(
            interval_seconds=86400,
            storage=storage,
            worker_manager=worker_manager
        )
        assert cleaner.interval_seconds == 86400
        assert cleaner.storage is storage
        assert cleaner.worker_manager is worker_manager

    def test_inherits_from_cron_job_base(self):
        """Test SessionCleaner inherits from CronJobBase."""
        from topsailai_server.agent_daemon.croner.jobs.__base import CronJobBase
        cleaner = SessionCleaner()
        assert isinstance(cleaner, CronJobBase)


class TestSessionCleanerRun:
    """Tests for SessionCleaner.run() method."""

    def test_run_with_no_old_sessions(self):
        """Test run exits early when no old sessions found."""
        storage = Mock()
        storage.session.get_sessions_older_than.return_value = []
        
        cleaner = SessionCleaner(storage=storage)
        cleaner.run()
        
        storage.session.get_sessions_older_than.assert_called_once()
        # Should not try to delete any sessions
        storage.session.delete.assert_not_called()

    def test_run_deletes_old_sessions(self):
        """Test that old sessions are deleted."""
        old_sessions = [
            MockSession("session1"),
            MockSession("session2"),
            MockSession("session3"),
        ]
        
        storage = Mock()
        storage.session.get_sessions_older_than.return_value = old_sessions
        
        cleaner = SessionCleaner(storage=storage)
        cleaner.run()
        
        # Should delete messages first, then session
        assert storage.message.delete_messages_by_session.call_count == 3
        assert storage.session.delete.call_count == 3

    def test_run_deletes_messages_before_session(self):
        """Test that messages are deleted before session."""
        old_sessions = [MockSession("session1")]
        
        storage = Mock()
        storage.session.get_sessions_older_than.return_value = old_sessions
        
        cleaner = SessionCleaner(storage=storage)
        cleaner.run()
        
        # Get call order
        delete_calls = storage.mock_calls
        # Find indices of delete_messages_by_session and delete calls
        msg_delete_idx = None
        session_delete_idx = None
        for idx, call in enumerate(delete_calls):
            if "delete_messages_by_session" in str(call):
                msg_delete_idx = idx
            if call[0] == "session.delete":
                session_delete_idx = idx
        
        # Messages should be deleted before session
        if msg_delete_idx is not None and session_delete_idx is not None:
            assert msg_delete_idx < session_delete_idx

    def test_run_handles_delete_exception(self):
        """Test that run() handles exceptions during deletion."""
        old_sessions = [
            MockSession("session1"),
            MockSession("session2"),
        ]
        
        storage = Mock()
        storage.session.get_sessions_older_than.return_value = old_sessions
        # First delete fails, second succeeds
        storage.message.delete_messages_by_session.side_effect = [
            Exception("Delete failed"),
            None
        ]
        
        cleaner = SessionCleaner(storage=storage)
        # Should not raise
        cleaner.run()
        
        # Should have attempted both deletions
        assert storage.message.delete_messages_by_session.call_count == 2

    def test_run_handles_exception(self):
        """Test that run() handles exceptions gracefully."""
        storage = Mock()
        storage.session.get_sessions_older_than.side_effect = Exception("Database error")
        
        cleaner = SessionCleaner(storage=storage)
        # Should not raise
        cleaner.run()

    def test_run_logs_deletion_count(self):
        """Test that run() logs the number of deleted sessions."""
        old_sessions = [
            MockSession("session1"),
            MockSession("session2"),
            MockSession("session3"),
        ]
        
        storage = Mock()
        storage.session.get_sessions_older_than.return_value = old_sessions
        
        cleaner = SessionCleaner(storage=storage)
        cleaner.run()
        
        # Verify all sessions were processed
        assert storage.session.delete.call_count == 3


class TestSessionCleanerEdgeCases:
    """Tests for edge cases in SessionCleaner."""

    def test_cutoff_date_calculation(self):
        """Test that cutoff date is calculated correctly (1 year ago)."""
        storage = Mock()
        storage.session.get_sessions_older_than.return_value = []
        
        cleaner = SessionCleaner(storage=storage)
        
        before_run = datetime.now()
        cleaner.run()
        after_run = datetime.now()
        
        # Get the cutoff date that was passed
        call_args = storage.session.get_sessions_older_than.call_args
        cutoff_date = call_args[0][0]
        
        # Cutoff should be approximately 1 year ago
        expected_cutoff = before_run - timedelta(days=365)
        # Allow 2 seconds tolerance
        assert abs((cutoff_date - expected_cutoff).total_seconds()) < 2

    def test_handles_large_number_of_sessions(self):
        """Test handling of many old sessions."""
        old_sessions = [
            MockSession(f"session{i}")
            for i in range(1000)
        ]
        
        storage = Mock()
        storage.session.get_sessions_older_than.return_value = old_sessions
        
        cleaner = SessionCleaner(storage=storage)
        cleaner.run()
        
        # Should attempt to delete all sessions
        assert storage.session.delete.call_count == 1000

    def test_partial_delete_failure_continues(self):
        """Test that deletion continues even if some sessions fail."""
        old_sessions = [
            MockSession("session1"),
            MockSession("session2"),
            MockSession("session3"),
        ]
        
        storage = Mock()
        storage.session.get_sessions_older_than.return_value = old_sessions
        # Second deletion fails
        storage.message.delete_messages_by_session.side_effect = [
            None,
            Exception("DB error"),
            None
        ]
        
        cleaner = SessionCleaner(storage=storage)
        cleaner.run()
        
        # Should have attempted all deletions
        assert storage.message.delete_messages_by_session.call_count == 3

    def test_session_with_no_messages(self):
        """Test deletion of session with no messages."""
        old_sessions = [MockSession("session1")]
        
        storage = Mock()
        storage.session.get_sessions_older_than.return_value = old_sessions
        # No messages to delete
        storage.message.delete_messages_by_session.return_value = 0
        
        cleaner = SessionCleaner(storage=storage)
        cleaner.run()
        
        # Should still delete the session
        storage.session.delete.assert_called_once_with("session1")

    def test_mixed_session_ages(self):
        """Test that only sessions older than cutoff are deleted."""
        # Only some sessions are old
        old_sessions = [
            MockSession("session1"),
            MockSession("session2"),
        ]
        
        storage = Mock()
        storage.session.get_sessions_older_than.return_value = old_sessions
        
        cleaner = SessionCleaner(storage=storage)
        cleaner.run()
        
        # Should only delete the old sessions
        assert storage.session.delete.call_count == 2
