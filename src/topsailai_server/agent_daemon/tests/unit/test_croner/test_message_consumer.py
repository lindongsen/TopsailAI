"""
Unit tests for MessageConsumer cron job.

Tests:
    - MessageConsumer initialization
    - Message consumption logic
    - Session processing
    - Circuit breaker integration
    - Edge cases and error handling
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from datetime import datetime, timedelta

from topsailai_server.agent_daemon.croner.jobs.message_consumer import (
    MessageConsumer,
    _processor_circuit_breaker,
)
from topsailai_server.agent_daemon.croner.jobs.utils import CircuitBreakerOpenError


class MockMessage:
    """Mock message object for testing."""
    def __init__(self, msg_id, session_id, role, message, create_time=None):
        self.msg_id = msg_id
        self.session_id = session_id
        self.role = role
        self.message = message
        self.create_time = create_time or datetime.now()
        self.task_id = None
        self.task_result = None


class MockSession:
    """Mock session object for testing."""
    def __init__(self, session_id, processed_msg_id=None):
        self.session_id = session_id
        self.processed_msg_id = processed_msg_id
        self.session_name = f"Session {session_id}"
        self.task = None
        self.create_time = datetime.now()
        self.update_time = datetime.now()


class TestMessageConsumerInitialization:
    """Tests for MessageConsumer initialization."""

    def test_initialization_with_defaults(self):
        """Test MessageConsumer initialization with default values."""
        consumer = MessageConsumer()
        assert consumer.interval_seconds == 60
        assert consumer.storage is None
        assert consumer.worker_manager is None

    def test_initialization_with_custom_values(self):
        """Test MessageConsumer initialization with custom values."""
        storage = Mock()
        worker_manager = Mock()
        consumer = MessageConsumer(
            interval_seconds=120,
            storage=storage,
            worker_manager=worker_manager
        )
        assert consumer.interval_seconds == 120
        assert consumer.storage is storage
        assert consumer.worker_manager is worker_manager

    def test_inherits_from_cron_job_base(self):
        """Test MessageConsumer inherits from CronJobBase."""
        from topsailai_server.agent_daemon.croner.jobs.__base import CronJobBase
        consumer = MessageConsumer()
        assert isinstance(consumer, CronJobBase)


class TestMessageConsumerRun:
    """Tests for MessageConsumer.run() method."""

    def test_run_with_no_storage(self):
        """Test run exits early when storage is not configured."""
        consumer = MessageConsumer()
        consumer.storage = None
        consumer.run()  # Should not raise

    def test_run_with_no_recent_messages(self):
        """Test run exits early when no recent messages found."""
        storage = Mock()
        storage.message.get_messages_since.return_value = []
        
        consumer = MessageConsumer(storage=storage)
        consumer.run()
        
        storage.message.get_messages_since.assert_called_once()

    @patch("topsailai_server.agent_daemon.configer.env_config.EnvConfig")
    def test_run_with_no_processor_script(self, mock_env_config):
        """Test run exits early when processor script not configured."""
        storage = Mock()
        storage.message.get_messages_since.return_value = [
            MockMessage("msg1", "session1", "user", "test")
        ]
        
        mock_config = Mock()
        mock_config.processor_script = None
        mock_env_config.return_value = mock_config
        
        consumer = MessageConsumer(storage=storage)
        consumer.run()


class TestMessageConsumerProcessSession:
    """Tests for MessageConsumer._process_session_with_metrics() method."""

    def test_process_session_not_found(self):
        """Test processing a session that doesn't exist."""
        storage = Mock()
        storage.session.get.return_value = None
        
        consumer = MessageConsumer(storage=storage)
        consumer._process_session_with_metrics("nonexistent", "script.py", storage)
        
        storage.session.get.assert_called_once_with("nonexistent")

    def test_process_session_no_messages(self):
        """Test processing a session with no messages."""
        storage = Mock()
        storage.session.get.return_value = MockSession("session1")
        storage.message.get_latest_message.return_value = None
        
        consumer = MessageConsumer(storage=storage)
        consumer._process_session_with_metrics("session1", "script.py", storage)

    def test_process_session_up_to_date(self):
        """Test processing a session that's already up to date."""
        session = MockSession("session1", processed_msg_id="msg2")
        latest_msg = MockMessage("msg2", "session1", "user", "test")
        
        storage = Mock()
        storage.session.get.return_value = session
        storage.message.get_latest_message.return_value = latest_msg
        
        consumer = MessageConsumer(storage=storage)
        consumer._process_session_with_metrics("session1", "script.py", storage)
        
        # Should not call get_unprocessed_messages
        storage.message.get_unprocessed_messages.assert_not_called()

    def test_process_session_no_unprocessed(self):
        """Test processing a session with no unprocessed messages."""
        session = MockSession("session1", processed_msg_id="msg1")
        latest_msg = MockMessage("msg2", "session1", "user", "test")
        
        storage = Mock()
        storage.session.get.return_value = session
        storage.message.get_latest_message.return_value = latest_msg
        storage.message.get_unprocessed_messages.return_value = []
        
        consumer = MessageConsumer(storage=storage)
        consumer._process_session_with_metrics("session1", "script.py", storage)

    def test_process_session_all_assistant_messages(self):
        """Test processing a session where all unprocessed are assistant messages."""
        session = MockSession("session1", processed_msg_id="msg1")
        latest_msg = MockMessage("msg3", "session1", "assistant", "response")
        unprocessed = [
            MockMessage("msg2", "session1", "assistant", "response1"),
            MockMessage("msg3", "session1", "assistant", "response2"),
        ]
        
        storage = Mock()
        storage.session.get.return_value = session
        storage.message.get_latest_message.return_value = latest_msg
        storage.message.get_unprocessed_messages.return_value = unprocessed
        
        consumer = MessageConsumer(storage=storage)
        consumer._process_session_with_metrics("session1", "script.py", storage)
        
        # Should not call worker_manager
        assert consumer.worker_manager is None or not consumer.worker_manager.check_session_state.called

    def test_process_session_already_processing(self):
        """Test processing a session that's already being processed."""
        session = MockSession("session1", processed_msg_id="msg1")
        latest_msg = MockMessage("msg2", "session1", "user", "test")
        unprocessed = [MockMessage("msg2", "session1", "user", "test")]
        
        storage = Mock()
        storage.session.get.return_value = session
        storage.message.get_latest_message.return_value = latest_msg
        storage.message.get_unprocessed_messages.return_value = unprocessed
        
        worker_manager = Mock()
        worker_manager.check_session_state.return_value = "processing"
        
        consumer = MessageConsumer(storage=storage, worker_manager=worker_manager)
        consumer._process_session_with_metrics("session1", "script.py", storage)
        
        worker_manager.check_session_state.assert_called_once_with("session1")

    @patch("topsailai_server.agent_daemon.storage.processor_helper.format_pending_messages")
    def test_process_session_success(self, mock_format):
        """Test successful session processing."""
        session = MockSession("session1", processed_msg_id="msg1")
        latest_msg = MockMessage("msg2", "session1", "user", "test")
        unprocessed = [MockMessage("msg2", "session1", "user", "test")]
        
        storage = Mock()
        storage.session.get.return_value = session
        storage.message.get_latest_message.return_value = latest_msg
        storage.message.get_unprocessed_messages.return_value = unprocessed
        
        worker_manager = Mock()
        worker_manager.check_session_state.return_value = "idle"
        worker_manager.start_processor.return_value = True
        mock_format.return_value = "---\nmsg2 content\n---"
        
        consumer = MessageConsumer(storage=storage, worker_manager=worker_manager)
        consumer._process_session_with_metrics("session1", "script.py", storage)
        
        worker_manager.start_processor.assert_called_once()


class TestMessageConsumerExecuteWithResilience:
    """Tests for MessageConsumer._execute_with_resilience() method."""

    def test_execute_without_worker_manager(self):
        """Test execution fails without worker manager."""
        consumer = MessageConsumer()
        consumer.worker_manager = None
        
        result = consumer._execute_with_resilience("session1", "script.py", [])
        assert result is False

    @patch("topsailai_server.agent_daemon.storage.processor_helper.format_pending_messages")
    def test_execute_success(self, mock_format):
        """Test successful execution with resilience."""
        worker_manager = Mock()
        worker_manager.start_processor.return_value = True
        mock_format.return_value = "formatted task"
        
        consumer = MessageConsumer(worker_manager=worker_manager)
        unprocessed = [MockMessage("msg1", "session1", "user", "test")]
        
        result = consumer._execute_with_resilience("session1", "script.py", unprocessed)
        assert result is True

    @patch("topsailai_server.agent_daemon.storage.processor_helper.format_pending_messages")
    def test_execute_circuit_breaker_open(self, mock_format):
        """Test execution when circuit breaker is open."""
        # Reset circuit breaker
        _processor_circuit_breaker.reset()
        
        # Open the circuit breaker by causing failures
        worker_manager = Mock()
        worker_manager.start_processor.side_effect = Exception("fail")
        
        consumer = MessageConsumer(worker_manager=worker_manager)
        unprocessed = [MockMessage("msg1", "session1", "user", "test")]
        
        # Cause failures to open circuit
        for _ in range(6):
            try:
                consumer._execute_with_resilience("session1", "script.py", unprocessed)
            except Exception:
                pass
        
        # Reset for other tests
        _processor_circuit_breaker.reset()


class TestMessageConsumerLogExecutionDuration:
    """Tests for MessageConsumer._log_execution_duration() method."""

    def test_log_execution_duration_fast(self):
        """Test logging fast execution."""
        consumer = MessageConsumer()
        start_time = time.time()
        # Should not raise
        consumer._log_execution_duration("Test Job", start_time)

    def test_log_execution_duration_slow(self):
        """Test logging slow execution."""
        consumer = MessageConsumer()
        start_time = time.time() - 31  # 31 seconds ago (>30s threshold)
        # Should not raise
        consumer._log_execution_duration("Test Job", start_time)


import time
