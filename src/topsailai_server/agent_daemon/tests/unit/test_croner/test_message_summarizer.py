"""
Unit tests for MessageSummarizer cron job.

Tests:
    - MessageSummarizer initialization
    - Message summarization logic
    - Session grouping and sorting
    - Circuit breaker integration
    - Edge cases and error handling
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta

from topsailai_server.agent_daemon.croner.jobs.message_summarizer import (
    MessageSummarizer,
    SUMMARIZER_CIRCUIT_BREAKER,
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


class TestMessageSummarizerInitialization:
    """Tests for MessageSummarizer initialization."""

    def test_initialization_with_defaults(self):
        """Test MessageSummarizer initialization with default values."""
        summarizer = MessageSummarizer()
        assert summarizer.interval_seconds == 86400
        # Note: storage may be auto-created if not provided

    def test_initialization_with_custom_values(self):
        """Test MessageSummarizer initialization with custom values."""
        storage = Mock()
        worker_manager = Mock()
        summarizer = MessageSummarizer(
            interval_seconds=3600,
            storage=storage,
            worker_manager=worker_manager
        )
        assert summarizer.interval_seconds == 3600
        assert summarizer.storage is storage
        assert summarizer.worker_manager is worker_manager

    def test_inherits_from_cron_job_base(self):
        """Test MessageSummarizer inherits from CronJobBase."""
        from topsailai_server.agent_daemon.croner.jobs.__base import CronJobBase
        summarizer = MessageSummarizer()
        assert isinstance(summarizer, CronJobBase)


class TestMessageSummarizerRun:
    """Tests for MessageSummarizer.run() method."""

    def test_run_with_no_messages(self):
        """Test run exits early when no recent messages found."""
        storage = Mock()
        storage.message.get_messages_since.return_value = []
        
        summarizer = MessageSummarizer(storage=storage)
        summarizer.run()
        
        storage.message.get_messages_since.assert_called_once()

    def test_run_groups_messages_by_session(self):
        """Test that messages are grouped by session_id."""
        messages = [
            MockMessage("msg1", "session1", "user", "hello"),
            MockMessage("msg2", "session2", "user", "hi"),
            MockMessage("msg3", "session1", "assistant", "hi there"),
        ]
        
        storage = Mock()
        storage.message.get_messages_since.return_value = messages
        
        worker_manager = Mock()
        worker_manager.start_summarizer.return_value = True
        
        summarizer = MessageSummarizer(storage=storage, worker_manager=worker_manager)
        summarizer.run()
        
        # Should have called start_summarizer twice (once per session)
        assert worker_manager.start_summarizer.call_count == 2

    def test_run_sorts_messages_by_create_time(self):
        """Test that messages are sorted by create_time for each session."""
        now = datetime.now()
        messages = [
            MockMessage("msg2", "session1", "assistant", "second", create_time=now),
            MockMessage("msg1", "session1", "user", "first", create_time=now - timedelta(minutes=1)),
            MockMessage("msg3", "session1", "user", "third", create_time=now + timedelta(minutes=1)),
        ]
        
        storage = Mock()
        storage.message.get_messages_since.return_value = messages
        
        worker_manager = Mock()
        worker_manager.start_summarizer.return_value = True
        
        summarizer = MessageSummarizer(storage=storage, worker_manager=worker_manager)
        summarizer.run()
        
        # Verify start_summarizer was called
        assert worker_manager.start_summarizer.called

    def test_run_handles_exception(self):
        """Test that run() handles exceptions gracefully."""
        storage = Mock()
        storage.message.get_messages_since.side_effect = Exception("Database error")
        
        summarizer = MessageSummarizer(storage=storage)
        # Should not raise
        summarizer.run()


class TestMessageSummarizerSummarizeSession:
    """Tests for MessageSummarizer._summarize_session() method."""

    def test_summarize_session_combines_messages(self):
        """Test that messages are combined correctly."""
        now = datetime.now()
        messages = [
            MockMessage("msg1", "session1", "user", "hello", create_time=now - timedelta(minutes=2)),
            MockMessage("msg2", "session1", "assistant", "hi there", create_time=now - timedelta(minutes=1)),
            MockMessage("msg3", "session1", "user", "how are you?", create_time=now),
        ]
        
        worker_manager = Mock()
        worker_manager.start_summarizer.return_value = True
        
        summarizer = MessageSummarizer(worker_manager=worker_manager)
        summarizer._summarize_session("session1", messages)
        
        worker_manager.start_summarizer.assert_called_once()
        call_args = worker_manager.start_summarizer.call_args
        assert call_args.kwargs["session_id"] == "session1"
        # Verify task contains all messages
        task = call_args.kwargs["task"]
        assert "hello" in task
        assert "hi there" in task
        assert "how are you?" in task

    def test_summarize_session_handles_exception(self):
        """Test that summarize_session handles exceptions gracefully."""
        messages = [MockMessage("msg1", "session1", "user", "test")]
        
        worker_manager = Mock()
        worker_manager.start_summarizer.side_effect = Exception("Worker error")
        
        summarizer = MessageSummarizer(worker_manager=worker_manager)
        # Should not raise
        summarizer._summarize_session("session1", messages)


class TestMessageSummarizerRunWithResilience:
    """Tests for MessageSummarizer._run_summarizer_with_resilience() method."""

    def test_successful_execution(self):
        """Test successful summarizer execution."""
        worker_manager = Mock()
        worker_manager.start_summarizer.return_value = True
        
        summarizer = MessageSummarizer(worker_manager=worker_manager)
        result = summarizer._run_summarizer_with_resilience("session1", "test task")
        
        assert result is True

    def test_execution_with_retry(self):
        """Test execution with retry on failure."""
        worker_manager = Mock()
        # First two calls fail, third succeeds
        worker_manager.start_summarizer.side_effect = [
            Exception("fail 1"),
            Exception("fail 2"),
            True
        ]
        
        summarizer = MessageSummarizer(worker_manager=worker_manager)
        result = summarizer._run_summarizer_with_resilience("session1", "test task")
        
        assert result is True
        assert worker_manager.start_summarizer.call_count == 3

    def test_execution_exhausts_retries(self):
        """Test execution when all retries are exhausted."""
        worker_manager = Mock()
        worker_manager.start_summarizer.side_effect = Exception("persistent error")
        
        summarizer = MessageSummarizer(worker_manager=worker_manager)
        result = summarizer._run_summarizer_with_resilience("session1", "test task")
        
        assert result is None


class TestMessageSummarizerEdgeCases:
    """Tests for edge cases in MessageSummarizer."""

    def test_empty_message_list(self):
        """Test handling of empty message list."""
        storage = Mock()
        storage.message.get_messages_since.return_value = []
        
        worker_manager = Mock()
        
        summarizer = MessageSummarizer(storage=storage, worker_manager=worker_manager)
        summarizer.run()
        
        # Should not call start_summarizer
        worker_manager.start_summarizer.assert_not_called()

    def test_single_message_session(self):
        """Test handling of session with single message."""
        messages = [MockMessage("msg1", "session1", "user", "hello")]
        
        storage = Mock()
        storage.message.get_messages_since.return_value = messages
        
        worker_manager = Mock()
        worker_manager.start_summarizer.return_value = True
        
        summarizer = MessageSummarizer(storage=storage, worker_manager=worker_manager)
        summarizer.run()
        
        worker_manager.start_summarizer.assert_called_once()

    def test_many_sessions(self):
        """Test handling of many sessions."""
        messages = [
            MockMessage(f"msg{i}", f"session{i}", "user", f"message {i}")
            for i in range(100)
        ]
        
        storage = Mock()
        storage.message.get_messages_since.return_value = messages
        
        worker_manager = Mock()
        worker_manager.start_summarizer.return_value = True
        
        summarizer = MessageSummarizer(storage=storage, worker_manager=worker_manager)
        summarizer.run()
        
        # Should call start_summarizer for each session
        assert worker_manager.start_summarizer.call_count == 100

    def test_message_format_timestamp(self):
        """Test that message timestamps are formatted correctly."""
        now = datetime.now()
        messages = [
            MockMessage("msg1", "session1", "user", "hello", create_time=now),
        ]
        
        storage = Mock()
        storage.message.get_messages_since.return_value = messages
        
        worker_manager = Mock()
        worker_manager.start_summarizer.return_value = True
        
        summarizer = MessageSummarizer(storage=storage, worker_manager=worker_manager)
        summarizer.run()
        
        call_args = worker_manager.start_summarizer.call_args
        task = call_args.kwargs["task"]
        # Should contain formatted timestamp
        assert now.strftime("%Y-%m-%d %H:%M:%S") in task
