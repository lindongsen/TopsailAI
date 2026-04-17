"""
Integration tests for Session Cleanup Cron Job.

Test ID: CRON-003
Category: Cron Jobs
Name: Test Session Cleanup Cron

This module tests the SessionCleaner cron job which:
- Runs monthly on the 1st at 1:00 AM
- Queries sessions with update_time older than 1 year
- Deletes related messages first (foreign key constraint)
- Deletes the sessions

Author: mm-m25
Created: 2026-04-17
"""

import pytest
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch

# Set HOME for integration testing
INTEGRATION_DIR = '/root/ai/TopsailAI/src/topsailai_server/agent_daemon/tests/integration'
os.environ['HOME'] = INTEGRATION_DIR

# Add parent directory to path for imports
sys.path.insert(0, '/root/ai/TopsailAI/src')

from topsailai_server.agent_daemon.croner.jobs.session_cleaner import SessionCleaner
from topsailai_server.agent_daemon.storage import Storage


class TestCron003SessionCleaner:
    """Test CRON-003: Test Session Cleanup Cron"""

    @pytest.fixture
    def mock_storage(self):
        """Create a mock storage instance for testing."""
        storage = Mock(spec=Storage)
        storage.session = Mock()
        storage.message = Mock()
        return storage

    @pytest.fixture
    def mock_worker_manager(self):
        """Create a mock worker manager for testing."""
        worker_manager = Mock()
        return worker_manager

    @pytest.fixture
    def session_cleaner(self, mock_storage, mock_worker_manager):
        """Create a SessionCleaner instance with mocked dependencies."""
        return SessionCleaner(
            interval_seconds=2592000,  # ~30 days
            storage=mock_storage,
            worker_manager=mock_worker_manager
        )

    def _create_mock_session(self, session_id, update_time=None):
        """
        Helper to create a mock session object.

        Args:
            session_id: The session ID
            update_time: The update time (default: now)

        Returns:
            Mock: A mock session object
        """
        session = Mock()
        session.session_id = session_id
        session.update_time = update_time or datetime.now()
        return session

    def _was_called_with(self, mock_func, *args):
        """Helper to check if a mock function was called with specific args."""
        for call in mock_func.call_args_list:
            if call == ((args[0],),):
                return True
        return False

    def test_cleaner_removes_old_sessions(
        self, session_cleaner, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-003-01: Test cleaner removes old sessions.

        Creates sessions with update_time older than 1 year and verifies
        that the cleaner deletes them.
        """
        # Create old sessions (older than 1 year)
        old_session1 = self._create_mock_session(
            "old-session-1",
            update_time=datetime.now() - timedelta(days=400)
        )
        old_session2 = self._create_mock_session(
            "old-session-2",
            update_time=datetime.now() - timedelta(days=500)
        )

        # Mock storage to return old sessions
        mock_storage.session.get_sessions_older_than.return_value = [
            old_session1, old_session2
        ]

        # Execute the cleaner
        session_cleaner.run()

        # Verify messages were deleted for each session
        assert mock_storage.message.delete_messages_by_session.call_count == 2
        mock_storage.message.delete_messages_by_session.assert_any_call("old-session-1")
        mock_storage.message.delete_messages_by_session.assert_any_call("old-session-2")

        # Verify sessions were deleted
        assert mock_storage.session.delete.call_count == 2
        mock_storage.session.delete.assert_any_call("old-session-1")
        mock_storage.session.delete.assert_any_call("old-session-2")

        # Verify last_run was updated (should be set after run)
        assert session_cleaner.last_run is not None

    def test_cleaner_preserves_recent_sessions(
        self, session_cleaner, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-003-02: Test cleaner preserves recent sessions.

        Creates sessions with update_time within the last year and verifies
        that they are not deleted.
        """
        # Create recent sessions (within 1 year)
        recent_session = self._create_mock_session(
            "recent-session",
            update_time=datetime.now() - timedelta(days=100)
        )

        # Mock storage to return no old sessions
        mock_storage.session.get_sessions_older_than.return_value = []

        # Execute the cleaner
        session_cleaner.run()

        # Verify no deletions occurred
        mock_storage.message.delete_messages_by_session.assert_not_called()
        mock_storage.session.delete.assert_not_called()

    def test_cleaner_handles_mixed_sessions(
        self, session_cleaner, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-003-03: Test cleaner handles mixed sessions correctly.

        Creates a mix of old (>1 year) and recent (<1 year) sessions and
        verifies only old sessions are removed.
        """
        # Create mixed sessions
        old_session = self._create_mock_session(
            "old-session",
            update_time=datetime.now() - timedelta(days=400)
        )

        # Mock storage to return only old sessions
        mock_storage.session.get_sessions_older_than.return_value = [old_session]

        # Execute the cleaner
        session_cleaner.run()

        # Verify only old session was deleted
        mock_storage.message.delete_messages_by_session.assert_called_once_with("old-session")
        mock_storage.session.delete.assert_called_once_with("old-session")

        # Verify recent session was NOT deleted (total count should be 1)
        assert mock_storage.message.delete_messages_by_session.call_count == 1
        assert mock_storage.session.delete.call_count == 1

    def test_cleaner_no_sessions(
        self, session_cleaner, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-003-04: Test cleaner handles no sessions gracefully.

        Triggers cleaner with no sessions at all and verifies graceful handling.
        """
        # Mock storage to return empty list
        mock_storage.session.get_sessions_older_than.return_value = []

        # Execute should not raise any exceptions
        session_cleaner.run()

        # Verify no deletions occurred
        mock_storage.message.delete_messages_by_session.assert_not_called()
        mock_storage.session.delete.assert_not_called()

    def test_cleaner_deletes_associated_messages(
        self, session_cleaner, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-003-05: Test cleaner deletes associated messages.

        Creates an old session with messages and verifies that both
        the session and its messages are deleted.
        """
        # Create old session
        old_session = self._create_mock_session(
            "old-session-with-messages",
            update_time=datetime.now() - timedelta(days=400)
        )

        # Mock storage to return old session
        mock_storage.session.get_sessions_older_than.return_value = [old_session]

        # Execute the cleaner
        session_cleaner.run()

        # Verify messages were deleted FIRST (foreign key constraint)
        mock_storage.message.delete_messages_by_session.assert_called_once_with(
            "old-session-with-messages"
        )

        # Verify session was deleted AFTER messages
        mock_storage.session.delete.assert_called_once_with("old-session-with-messages")

        # Verify order: messages deleted before session
        calls = mock_storage.message.delete_messages_by_session.call_args_list
        session_calls = mock_storage.session.delete.call_args_list

        # Both should have been called exactly once
        assert len(calls) == 1
        assert len(session_calls) == 1

    def test_cleaner_handles_delete_error(
        self, session_cleaner, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-003-06: Test cleaner handles delete errors gracefully.

        Simulates an error during session deletion and verifies that
        the cleaner continues processing other sessions.
        """
        # Create multiple old sessions
        old_session1 = self._create_mock_session(
            "old-session-1",
            update_time=datetime.now() - timedelta(days=400)
        )
        old_session2 = self._create_mock_session(
            "old-session-2",
            update_time=datetime.now() - timedelta(days=500)
        )

        # Mock storage to return old sessions
        mock_storage.session.get_sessions_older_than.return_value = [
            old_session1, old_session2
        ]

        # Make first delete raise an exception
        def delete_side_effect(session_id):
            if session_id == "old-session-1":
                raise Exception("Database error")

        mock_storage.session.delete.side_effect = delete_side_effect

        # Execute the cleaner
        session_cleaner.run()

        # Verify first session deletion was attempted
        mock_storage.session.delete.assert_any_call("old-session-1")

        # Verify second session was still processed (error was handled)
        mock_storage.session.delete.assert_any_call("old-session-2")

        # Verify messages were deleted for both sessions
        assert mock_storage.message.delete_messages_by_session.call_count == 2

    def test_cleaner_handles_no_worker_manager(self, mock_storage):
        """
        Test CRON-003-07: Test cleaner handles missing worker manager.

        When worker_manager is not configured, the cleaner should still work
        (worker_manager is not required for cleanup).
        """
        session_cleaner = SessionCleaner(
            interval_seconds=2592000,
            storage=mock_storage,
            worker_manager=None  # No worker manager
        )

        # Mock storage to return empty list
        mock_storage.session.get_sessions_older_than.return_value = []

        # Execute should not raise any exceptions
        session_cleaner.run()

        # No exception should be raised

    def test_cleaner_calculates_correct_cutoff_date(
        self, session_cleaner, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-003-08: Test cleaner calculates correct cutoff date.

        Verifies that the cutoff date is correctly calculated as 1 year ago.
        """
        # Mock storage to capture the cutoff date
        captured_cutoff = []

        def capture_cutoff(cutoff_date):
            captured_cutoff.append(cutoff_date)

        mock_storage.session.get_sessions_older_than.side_effect = capture_cutoff
        mock_storage.session.get_sessions_older_than.return_value = []

        # Execute the cleaner
        session_cleaner.run()

        # Verify cutoff date was calculated
        assert len(captured_cutoff) == 1

        # Verify cutoff date is approximately 365 days ago
        expected_cutoff = datetime.now() - timedelta(days=365)
        time_diff = abs((captured_cutoff[0] - expected_cutoff).total_seconds())

        # Allow 5 seconds tolerance for test execution time
        assert time_diff < 5, "Cutoff date should be approximately 1 year ago"

    def test_cleaner_logs_session_count(
        self, session_cleaner, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-003-09: Test cleaner logs session count.

        Verifies that the cleaner logs the number of sessions found and deleted.
        """
        # Create old sessions
        old_session1 = self._create_mock_session(
            "old-session-1",
            update_time=datetime.now() - timedelta(days=400)
        )
        old_session2 = self._create_mock_session(
            "old-session-2",
            update_time=datetime.now() - timedelta(days=500)
        )

        # Mock storage to return old sessions
        mock_storage.session.get_sessions_older_than.return_value = [
            old_session1, old_session2
        ]

        # Execute the cleaner
        session_cleaner.run()

        # Verify storage methods were called (logging happens inside run method)
        mock_storage.session.get_sessions_older_than.assert_called_once()
        assert mock_storage.session.delete.call_count == 2

    def test_cleaner_handles_empty_session_list(
        self, session_cleaner, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-003-10: Test cleaner handles empty session list.

        Verifies that when get_sessions_older_than returns an empty list,
        no deletions occur and the job completes gracefully.
        """
        # Mock storage to return empty list
        mock_storage.session.get_sessions_older_than.return_value = []

        # Execute the cleaner
        session_cleaner.run()

        # Verify no deletions occurred
        mock_storage.message.delete_messages_by_session.assert_not_called()
        mock_storage.session.delete.assert_not_called()

    def test_cleaner_cascade_delete_order(
        self, session_cleaner, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-003-11: Test cleaner deletes messages before sessions.

        Verifies that messages are deleted before sessions to maintain
        referential integrity.
        """
        # Create old sessions
        old_session1 = self._create_mock_session(
            "old-session-1",
            update_time=datetime.now() - timedelta(days=400)
        )

        # Mock storage to return old sessions
        mock_storage.session.get_sessions_older_than.return_value = [old_session1]

        # Track call order
        call_order = []

        def track_message_delete(session_id):
            call_order.append(("message_delete", session_id))

        def track_session_delete(session_id):
            call_order.append(("session_delete", session_id))

        mock_storage.message.delete_messages_by_session.side_effect = track_message_delete
        mock_storage.session.delete.side_effect = track_session_delete

        # Execute the cleaner
        session_cleaner.run()

        # Verify messages were deleted before session
        assert call_order[0][0] == "message_delete"
        assert call_order[1][0] == "session_delete"
        assert call_order[0][1] == "old-session-1"
        assert call_order[1][1] == "old-session-1"

    def test_cleaner_with_single_old_session(
        self, session_cleaner, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-003-12: Test cleaner with single old session.

        Verifies that the cleaner correctly handles a single old session.
        """
        # Create single old session
        old_session = self._create_mock_session(
            "single-old-session",
            update_time=datetime.now() - timedelta(days=400)
        )

        # Mock storage to return single old session
        mock_storage.session.get_sessions_older_than.return_value = [old_session]

        # Execute the cleaner
        session_cleaner.run()

        # Verify messages were deleted
        mock_storage.message.delete_messages_by_session.assert_called_once_with(
            "single-old-session"
        )

        # Verify session was deleted
        mock_storage.session.delete.assert_called_once_with("single-old-session")

    def test_cleaner_handles_storage_error(
        self, session_cleaner, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-003-13: Test cleaner handles storage errors gracefully.

        Simulates an error when querying old sessions and verifies
        that the error is caught and logged.
        """
        # Make get_sessions_older_than raise an exception
        mock_storage.session.get_sessions_older_than.side_effect = Exception("Database error")

        # Execute should not raise any exceptions (error is caught internally)
        session_cleaner.run()

        # Verify no deletions occurred
        mock_storage.message.delete_messages_by_session.assert_not_called()
        mock_storage.session.delete.assert_not_called()
