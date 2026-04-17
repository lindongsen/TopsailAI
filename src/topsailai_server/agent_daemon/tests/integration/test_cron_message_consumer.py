"""
Integration tests for Message Consumer Cron Job.

Test ID: CRON-001
Category: Cron Jobs
Name: Test Message Consumer Cron

This module tests the MessageConsumer cron job which:
- Runs every minute
- Queries messages from the last 10 minutes
- Triggers the processor for sessions with unprocessed messages
"""

import pytest
import time
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch

# Set HOME for integration testing
INTEGRATION_DIR = '/root/ai/TopsailAI/src/topsailai_server/agent_daemon/tests/integration'
os.environ['HOME'] = INTEGRATION_DIR

# Add parent directory to path for imports
sys.path.insert(0, '/root/ai/TopsailAI/src')

from topsailai_server.agent_daemon.croner.jobs.message_consumer import MessageConsumer
from topsailai_server.agent_daemon.storage import Storage


class TestCron001MessageConsumer:
    """Test CRON-001: Test Message Consumer Cron"""

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
        worker_manager.check_session_state = Mock(return_value='idle')
        worker_manager.start_processor = Mock(return_value=True)
        return worker_manager

    @pytest.fixture
    def message_consumer(self, mock_storage, mock_worker_manager):
        """Create a MessageConsumer instance with mocked dependencies."""
        return MessageConsumer(
            interval_seconds=60,
            storage=mock_storage,
            worker_manager=mock_worker_manager
        )

    def _create_mock_message(self, msg_id, session_id, role, create_time=None):
        """Helper to create a mock message object."""
        msg = Mock()
        msg.msg_id = msg_id
        msg.session_id = session_id
        msg.role = role
        msg.message = f"Test message {msg_id}"
        msg.create_time = create_time or datetime.now()
        msg.task_id = None
        msg.task_result = None
        return msg

    def _create_mock_session(self, session_id, processed_msg_id=None):
        """Helper to create a mock session object."""
        session = Mock()
        session.session_id = session_id
        session.processed_msg_id = processed_msg_id
        return session

    def test_message_consumer_processes_unprocessed_messages(
        self, message_consumer, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-001-01: Test message consumer processes unprocessed messages.

        Creates a session with unprocessed messages and verifies that
        the processor is triggered.
        """
        session_id = "test-session-unprocessed"
        msg1 = self._create_mock_message("msg-1", session_id, "user")
        msg2 = self._create_mock_message("msg-2", session_id, "user")
        msg3 = self._create_mock_message("msg-3", session_id, "user")

        # Mock session with processed_msg_id pointing to msg-1
        mock_session = self._create_mock_session(session_id, processed_msg_id="msg-1")
        mock_storage.session.get.return_value = mock_session
        mock_storage.message.get_latest_message.return_value = msg3
        mock_storage.message.get_unprocessed_messages.return_value = [msg2, msg3]
        mock_storage.message.get_messages_since.return_value = [msg1, msg2, msg3]

        # Patch EnvConfig at the correct location (inside the method)
        with patch('topsailai_server.agent_daemon.configer.env_config.EnvConfig') as mock_env_config_class:
            mock_env_config = Mock()
            mock_env_config.processor_script = '/mock/processor.sh'
            mock_env_config_class.return_value = mock_env_config

            # Execute the consumer
            message_consumer._consume_messages()

        # Verify processor was triggered
        mock_worker_manager.check_session_state.assert_called_with(session_id)
        mock_worker_manager.start_processor.assert_called_once()

        # Verify the call arguments
        call_args = mock_worker_manager.start_processor.call_args
        assert call_args.kwargs['session_id'] == session_id
        assert call_args.kwargs['msg_id'] == "msg-3"

    def test_message_consumer_skips_processed_sessions(
        self, message_consumer, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-001-02: Test message consumer skips already processed sessions.

        Creates a session where processed_msg_id equals the latest message,
        verifying no processing occurs.
        """
        session_id = "test-session-processed"
        msg1 = self._create_mock_message("msg-1", session_id, "user")

        # Session is already up to date
        mock_session = self._create_mock_session(session_id, processed_msg_id="msg-1")
        mock_storage.session.get.return_value = mock_session
        mock_storage.message.get_latest_message.return_value = msg1
        mock_storage.message.get_messages_since.return_value = [msg1]

        # Execute the consumer
        message_consumer._consume_messages()

        # Verify no processing occurred
        mock_worker_manager.check_session_state.assert_not_called()
        mock_worker_manager.start_processor.assert_not_called()

    def test_message_consumer_handles_multiple_sessions(
        self, message_consumer, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-001-03: Test message consumer handles multiple sessions.

        Creates multiple sessions with unprocessed messages and verifies
        all sessions are processed.
        """
        session1_id = "test-session-1"
        session2_id = "test-session-2"

        msg1_s1 = self._create_mock_message("msg-1-s1", session1_id, "user")
        msg2_s1 = self._create_mock_message("msg-2-s1", session1_id, "user")
        msg1_s2 = self._create_mock_message("msg-1-s2", session2_id, "user")
        msg2_s2 = self._create_mock_message("msg-2-s2", session2_id, "user")

        mock_session1 = self._create_mock_session(session1_id, processed_msg_id="msg-1-s1")
        mock_session2 = self._create_mock_session(session2_id, processed_msg_id="msg-1-s2")

        def get_session(sid):
            if sid == session1_id:
                return mock_session1
            return mock_session2

        def get_latest_message(sid):
            if sid == session1_id:
                return msg2_s1
            return msg2_s2

        def get_unprocessed(sid, processed_id):
            if sid == session1_id:
                return [msg2_s1]
            return [msg2_s2]

        mock_storage.session.get.side_effect = get_session
        mock_storage.message.get_latest_message.side_effect = get_latest_message
        mock_storage.message.get_unprocessed_messages.side_effect = get_unprocessed
        mock_storage.message.get_messages_since.return_value = [msg1_s1, msg2_s1, msg1_s2, msg2_s2]

        # Patch EnvConfig at the correct location
        with patch('topsailai_server.agent_daemon.configer.env_config.EnvConfig') as mock_env_config_class:
            mock_env_config = Mock()
            mock_env_config.processor_script = '/mock/processor.sh'
            mock_env_config_class.return_value = mock_env_config

            # Execute the consumer
            message_consumer._consume_messages()

        # Verify both sessions were processed
        assert mock_worker_manager.start_processor.call_count == 2

    def test_message_consumer_respects_time_window(
        self, message_consumer, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-001-04: Test message consumer respects 10-minute time window.

        Creates messages outside the 10-minute window and verifies only
        recent messages are considered.
        """
        session_id = "test-session-timewindow"

        # Recent message (within 10 minutes)
        recent_msg = self._create_mock_message(
            "msg-recent", session_id, "user",
            create_time=datetime.now() - timedelta(minutes=5)
        )

        # Old message (outside 10-minute window)
        old_msg = self._create_mock_message(
            "msg-old", session_id, "user",
            create_time=datetime.now() - timedelta(minutes=15)
        )

        mock_storage.message.get_messages_since.return_value = [recent_msg]

        # Execute the consumer
        message_consumer._consume_messages()

        # Verify only recent messages were queried
        mock_storage.message.get_messages_since.assert_called_once()
        call_args = mock_storage.message.get_messages_since.call_args
        cutoff_time = call_args[0][0]

        # Verify cutoff time is approximately 10 minutes ago
        expected_cutoff = datetime.now() - timedelta(minutes=10)
        time_diff = abs((cutoff_time - expected_cutoff).total_seconds())
        assert time_diff < 5, "Cutoff time should be approximately 10 minutes ago"

    def test_message_consumer_no_sessions(
        self, message_consumer, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-001-05: Test message consumer handles no sessions gracefully.

        Triggers cron job with no recent messages and verifies graceful handling.
        """
        mock_storage.message.get_messages_since.return_value = []

        # Execute should not raise any exceptions
        message_consumer._consume_messages()

        # Verify no processing occurred
        mock_worker_manager.check_session_state.assert_not_called()
        mock_worker_manager.start_processor.assert_not_called()

    def test_message_consumer_skips_all_assistant_messages(
        self, message_consumer, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-001-06: Test message consumer skips sessions with only assistant messages.

        When all unprocessed messages are from assistant, the consumer should
        skip processing to avoid infinite loops.
        """
        session_id = "test-session-assistant-only"
        msg1 = self._create_mock_message("msg-1", session_id, "user")
        msg2 = self._create_mock_message("msg-2", session_id, "assistant")
        msg3 = self._create_mock_message("msg-3", session_id, "assistant")

        mock_session = self._create_mock_session(session_id, processed_msg_id="msg-1")
        mock_storage.session.get.return_value = mock_session
        mock_storage.message.get_latest_message.return_value = msg3
        mock_storage.message.get_unprocessed_messages.return_value = [msg2, msg3]
        mock_storage.message.get_messages_since.return_value = [msg1, msg2, msg3]

        # Patch EnvConfig at the correct location
        with patch('topsailai_server.agent_daemon.configer.env_config.EnvConfig') as mock_env_config_class:
            mock_env_config = Mock()
            mock_env_config.processor_script = '/mock/processor.sh'
            mock_env_config_class.return_value = mock_env_config

            # Execute the consumer
            message_consumer._consume_messages()

        # Verify no processing occurred (all unprocessed are assistant)
        mock_worker_manager.check_session_state.assert_not_called()
        mock_worker_manager.start_processor.assert_not_called()

    def test_message_consumer_skips_processing_session(
        self, message_consumer, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-001-07: Test message consumer skips sessions that are already processing.

        When session state is 'processing', the consumer should skip that session.
        """
        session_id = "test-session-processing"
        msg1 = self._create_mock_message("msg-1", session_id, "user")
        msg2 = self._create_mock_message("msg-2", session_id, "user")

        mock_session = self._create_mock_session(session_id, processed_msg_id="msg-1")
        mock_storage.session.get.return_value = mock_session
        mock_storage.message.get_latest_message.return_value = msg2
        mock_storage.message.get_unprocessed_messages.return_value = [msg2]
        mock_storage.message.get_messages_since.return_value = [msg1, msg2]

        # Session is already processing
        mock_worker_manager.check_session_state.return_value = 'processing'

        # Patch EnvConfig at the correct location
        with patch('topsailai_server.agent_daemon.configer.env_config.EnvConfig') as mock_env_config_class:
            mock_env_config = Mock()
            mock_env_config.processor_script = '/mock/processor.sh'
            mock_env_config_class.return_value = mock_env_config

            # Execute the consumer
            message_consumer._consume_messages()

        # Verify state was checked but processor was not started
        mock_worker_manager.check_session_state.assert_called_with(session_id)
        mock_worker_manager.start_processor.assert_not_called()

    def test_message_consumer_handles_missing_session(
        self, message_consumer, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-001-08: Test message consumer handles missing session gracefully.

        When a session is referenced in messages but doesn't exist in database,
        the consumer should handle it gracefully.
        """
        session_id = "test-session-missing"

        msg1 = self._create_mock_message("msg-1", session_id, "user")
        mock_storage.message.get_messages_since.return_value = [msg1]
        mock_storage.session.get.return_value = None  # Session not found

        # Execute should not raise any exceptions
        message_consumer._consume_messages()

        # Verify no processing occurred
        mock_worker_manager.start_processor.assert_not_called()

    def test_message_consumer_handles_no_worker_manager(
        self, mock_storage
    ):
        """
        Test CRON-001-09: Test message consumer handles missing worker manager.

        When worker_manager is not configured, the consumer should handle it gracefully.
        """
        message_consumer = MessageConsumer(
            interval_seconds=60,
            storage=mock_storage,
            worker_manager=None  # No worker manager
        )

        session_id = "test-session-no-worker"
        msg1 = self._create_mock_message("msg-1", session_id, "user")
        msg2 = self._create_mock_message("msg-2", session_id, "user")

        mock_session = self._create_mock_session(session_id, processed_msg_id="msg-1")
        mock_storage.session.get.return_value = mock_session
        mock_storage.message.get_latest_message.return_value = msg2
        mock_storage.message.get_unprocessed_messages.return_value = [msg2]
        mock_storage.message.get_messages_since.return_value = [msg1, msg2]

        # Execute should not raise any exceptions
        message_consumer._consume_messages()

        # No exception should be raised, but processor should not be started
        # since worker_manager is None

    def test_message_consumer_handles_no_storage(
        self, mock_worker_manager
    ):
        """
        Test CRON-001-10: Test message consumer handles missing storage.

        When storage is not configured, the consumer should handle it gracefully.
        """
        message_consumer = MessageConsumer(
            interval_seconds=60,
            storage=None,  # No storage
            worker_manager=mock_worker_manager
        )

        # Execute should not raise any exceptions
        message_consumer._consume_messages()

        # No exception should be raised

    def test_message_consumer_with_task_id_and_result(
        self, message_consumer, mock_storage, mock_worker_manager
    ):
        """
        Test CRON-001-11: Test message consumer includes task_id and task_result in pending messages.

        When messages have task_id and task_result, they should be included
        in the pending messages sent to the processor.
        """
        session_id = "test-session-task"
        msg1 = self._create_mock_message("msg-1", session_id, "user")
        msg2 = self._create_mock_message("msg-2", session_id, "user")
        msg2.task_id = "task-123"
        msg2.task_result = "Task completed successfully"

        mock_session = self._create_mock_session(session_id, processed_msg_id="msg-1")
        mock_storage.session.get.return_value = mock_session
        mock_storage.message.get_latest_message.return_value = msg2
        mock_storage.message.get_unprocessed_messages.return_value = [msg2]
        mock_storage.message.get_messages_since.return_value = [msg1, msg2]

        # Patch EnvConfig at the correct location
        with patch('topsailai_server.agent_daemon.configer.env_config.EnvConfig') as mock_env_config_class:
            mock_env_config = Mock()
            mock_env_config.processor_script = '/mock/processor.sh'
            mock_env_config_class.return_value = mock_env_config

            # Execute the consumer
            message_consumer._consume_messages()

        # Verify processor was triggered with task info
        mock_worker_manager.start_processor.assert_called_once()
        call_args = mock_worker_manager.start_processor.call_args
        task_content = call_args.kwargs['task']

        # Verify task_id and task_result are included in the task content
        assert "task_id" in task_content or "task-123" in task_content
