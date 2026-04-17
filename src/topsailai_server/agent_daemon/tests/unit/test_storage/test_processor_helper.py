"""
Unit tests for processor_helper module.

Tests message formatting and processing logic functions.

Author: mm-m25
Created: 2026-04-17
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from topsailai_server.agent_daemon.storage.message_manager.base import MessageData


class TestFormatPendingMessages:
    """Tests for format_pending_messages function."""

    def test_format_user_messages(self):
        """Test formatting user messages only."""
        from topsailai_server.agent_daemon.storage.processor_helper import format_pending_messages

        messages = [
            MessageData(msg_id="msg_1", session_id="s1", message="Hello", role="user"),
            MessageData(msg_id="msg_2", session_id="s1", message="How are you?", role="user"),
        ]

        result = format_pending_messages(messages)

        assert "---" in result
        assert "Hello" in result
        assert "How are you?" in result
        assert result.startswith("---")
        assert result.endswith("---")

    def test_format_assistant_messages_with_task_id(self):
        """Test formatting assistant messages with task_id."""
        from topsailai_server.agent_daemon.storage.processor_helper import format_pending_messages

        messages = [
            MessageData(
                msg_id="msg_1",
                session_id="s1",
                message="I'll help you",
                role="assistant",
                task_id="task_001",
                task_result="Result data"
            ),
        ]

        result = format_pending_messages(messages)

        assert "I'll help you" in result
        assert ">>> task_id: task_001" in result
        assert ">>> task_result: Result data" in result

    def test_filter_out_assistant_messages_without_task_id(self):
        """Test that assistant messages without task_id are filtered out."""
        from topsailai_server.agent_daemon.storage.processor_helper import format_pending_messages

        messages = [
            MessageData(msg_id="msg_1", session_id="s1", message="Hello", role="user"),
            MessageData(msg_id="msg_2", session_id="s1", message="I'm thinking...", role="assistant"),
            MessageData(msg_id="msg_3", session_id="s1", message="Done!", role="user"),
        ]

        result = format_pending_messages(messages)

        assert "Hello" in result
        assert "Done!" in result
        assert "I'm thinking..." not in result  # Filtered out

    def test_include_assistant_messages_with_task_id(self):
        """Test that assistant messages with task_id are included."""
        from topsailai_server.agent_daemon.storage.processor_helper import format_pending_messages

        messages = [
            MessageData(msg_id="msg_1", session_id="s1", message="Hello", role="user"),
            MessageData(
                msg_id="msg_2",
                session_id="s1",
                message="Task result here",
                role="assistant",
                task_id="task_001"
            ),
        ]

        result = format_pending_messages(messages)

        assert "Hello" in result
        assert "Task result here" in result
        assert ">>> task_id: task_001" in result

    def test_empty_message_list(self):
        """Test formatting empty message list."""
        from topsailai_server.agent_daemon.storage.processor_helper import format_pending_messages

        result = format_pending_messages([])

        assert result == ""

    def test_all_messages_filtered_out(self):
        """Test when all messages are filtered out."""
        from topsailai_server.agent_daemon.storage.processor_helper import format_pending_messages

        messages = [
            MessageData(msg_id="msg_1", session_id="s1", message="Thinking...", role="assistant"),
            MessageData(msg_id="msg_2", session_id="s1", message="Still thinking...", role="assistant"),
        ]

        result = format_pending_messages(messages)

        assert result == ""

    def test_task_id_only_when_present(self):
        """Test that task_id is only included when present."""
        from topsailai_server.agent_daemon.storage.processor_helper import format_pending_messages

        messages = [
            MessageData(
                msg_id="msg_1",
                session_id="s1",
                message="Simple message",
                role="user",
                task_id=None,
                task_result=None
            ),
        ]

        result = format_pending_messages(messages)

        assert "Simple message" in result
        assert ">>> task_id" not in result
        assert ">>> task_result" not in result

    def test_task_result_only_when_present(self):
        """Test that task_result is only included when present."""
        from topsailai_server.agent_daemon.storage.processor_helper import format_pending_messages

        messages = [
            MessageData(
                msg_id="msg_1",
                session_id="s1",
                message="Task message",
                role="assistant",
                task_id="task_001",
                task_result=None
            ),
        ]

        result = format_pending_messages(messages)

        assert ">>> task_id: task_001" in result
        assert ">>> task_result" not in result

    def test_multiple_messages_format(self):
        """Test formatting multiple messages with correct separators."""
        from topsailai_server.agent_daemon.storage.processor_helper import format_pending_messages

        messages = [
            MessageData(msg_id="msg_1", session_id="s1", message="First", role="user"),
            MessageData(msg_id="msg_2", session_id="s1", message="Second", role="user"),
            MessageData(msg_id="msg_3", session_id="s1", message="Third", role="user"),
        ]

        result = format_pending_messages(messages)

        # Should have 3 message blocks separated by ---
        assert result.count("---") >= 4  # Start, between each, end
        assert "First" in result
        assert "Second" in result
        assert "Third" in result


class TestCheckAndProcessMessages:
    """Tests for check_and_process_messages function."""

    def test_session_not_found(self):
        """Test when session is not found."""
        from topsailai_server.agent_daemon.storage.processor_helper import check_and_process_messages

        mock_storage = MagicMock()
        mock_storage.session.get.return_value = None
        mock_worker_manager = MagicMock()

        with patch('topsailai_server.agent_daemon.storage.processor_helper.logger') as mock_logger:
            result = check_and_process_messages(
                session_id="nonexistent",
                storage=mock_storage,
                worker_manager=mock_worker_manager
            )

        assert result is None
        mock_logger.warning.assert_called()

    def test_no_messages_in_session(self):
        """Test when no messages exist in session."""
        from topsailai_server.agent_daemon.storage.processor_helper import check_and_process_messages

        mock_storage = MagicMock()
        mock_storage.session.get.return_value = MagicMock(session_id="test_session")
        mock_storage.message.get_latest_message.return_value = None
        mock_worker_manager = MagicMock()

        with patch('topsailai_server.agent_daemon.storage.processor_helper.logger') as mock_logger:
            result = check_and_process_messages(
                session_id="test_session",
                storage=mock_storage,
                worker_manager=mock_worker_manager
            )

        assert result is None
        mock_logger.warning.assert_called()

    def test_already_up_to_date(self):
        """Test when session is already up to date."""
        from topsailai_server.agent_daemon.storage.processor_helper import check_and_process_messages

        mock_session = MagicMock()
        mock_session.processed_msg_id = "msg_latest"

        mock_latest_msg = MagicMock()
        mock_latest_msg.msg_id = "msg_latest"

        mock_storage = MagicMock()
        mock_storage.session.get.return_value = mock_session
        mock_storage.message.get_latest_message.return_value = mock_latest_msg
        mock_worker_manager = MagicMock()

        with patch('topsailai_server.agent_daemon.storage.processor_helper.logger') as mock_logger:
            result = check_and_process_messages(
                session_id="test_session",
                storage=mock_storage,
                worker_manager=mock_worker_manager
            )

        assert result is None
        mock_logger.debug.assert_called()

    def test_no_unprocessed_messages(self):
        """Test when no unprocessed messages exist."""
        from topsailai_server.agent_daemon.storage.processor_helper import check_and_process_messages

        mock_session = MagicMock()
        mock_session.processed_msg_id = "msg_processed"

        mock_latest_msg = MagicMock()
        mock_latest_msg.msg_id = "msg_latest"

        mock_storage = MagicMock()
        mock_storage.session.get.return_value = mock_session
        mock_storage.message.get_latest_message.return_value = mock_latest_msg
        mock_storage.message.get_unprocessed_messages.return_value = []
        mock_worker_manager = MagicMock()

        result = check_and_process_messages(
            session_id="test_session",
            storage=mock_storage,
            worker_manager=mock_worker_manager
        )

        assert result is None

    def test_all_messages_filtered_out(self):
        """Test when all unprocessed messages are filtered out."""
        from topsailai_server.agent_daemon.storage.processor_helper import check_and_process_messages

        mock_session = MagicMock()
        mock_session.processed_msg_id = "msg_processed"

        mock_latest_msg = MagicMock()
        mock_latest_msg.msg_id = "msg_latest"

        # All messages are assistant without task_id
        mock_unprocessed = [
            MagicMock(role="assistant", task_id=None),
            MagicMock(role="assistant", task_id=None),
        ]

        mock_storage = MagicMock()
        mock_storage.session.get.return_value = mock_session
        mock_storage.message.get_latest_message.return_value = mock_latest_msg
        mock_storage.message.get_unprocessed_messages.return_value = mock_unprocessed
        mock_worker_manager = MagicMock()

        with patch('topsailai_server.agent_daemon.storage.processor_helper.logger') as mock_logger:
            result = check_and_process_messages(
                session_id="test_session",
                storage=mock_storage,
                worker_manager=mock_worker_manager
            )

        assert result is None
        mock_logger.info.assert_called()

    def test_session_processing(self):
        """Test when session is already processing."""
        from topsailai_server.agent_daemon.storage.processor_helper import check_and_process_messages

        mock_session = MagicMock()
        mock_session.processed_msg_id = "msg_processed"

        mock_latest_msg = MagicMock()
        mock_latest_msg.msg_id = "msg_latest"

        mock_unprocessed = [
            MagicMock(role="user", task_id=None),
        ]

        mock_storage = MagicMock()
        mock_storage.session.get.return_value = mock_session
        mock_storage.message.get_latest_message.return_value = mock_latest_msg
        mock_storage.message.get_unprocessed_messages.return_value = mock_unprocessed
        mock_worker_manager = MagicMock()
        mock_worker_manager.is_session_idle.return_value = False

        with patch('topsailai_server.agent_daemon.storage.processor_helper.logger') as mock_logger:
            result = check_and_process_messages(
                session_id="test_session",
                storage=mock_storage,
                worker_manager=mock_worker_manager
            )

        assert result is None
        mock_logger.info.assert_called()

    def test_successful_processing(self):
        """Test successful message processing."""
        from topsailai_server.agent_daemon.storage.processor_helper import check_and_process_messages

        mock_session = MagicMock()
        mock_session.processed_msg_id = "msg_processed"

        mock_latest_msg = MagicMock()
        mock_latest_msg.msg_id = "msg_latest"
        mock_latest_msg.create_time = datetime.now()

        mock_unprocessed = [
            MagicMock(
                msg_id="msg_1",
                session_id="test_session",
                message="Test",
                role="user",
                create_time=datetime.now(),
                update_time=None,
                task_id=None,
                task_result=None
            ),
        ]

        mock_storage = MagicMock()
        mock_storage.session.get.return_value = mock_session
        mock_storage.message.get_latest_message.return_value = mock_latest_msg
        mock_storage.message.get_unprocessed_messages.return_value = mock_unprocessed
        mock_worker_manager = MagicMock()
        mock_worker_manager.is_session_idle.return_value = True

        with patch('topsailai_server.agent_daemon.storage.processor_helper.format_pending_messages') as mock_format:
            mock_format.return_value = "---\nTest\n---"

            result = check_and_process_messages(
                session_id="test_session",
                storage=mock_storage,
                worker_manager=mock_worker_manager,
                async_mode=False
            )

        assert result is not None
        assert "processed_msg_id" in result
        assert "processing_msg_id" in result
        assert "messages" in result

    def test_empty_formatted_messages(self):
        """Test when formatted messages are empty."""
        from topsailai_server.agent_daemon.storage.processor_helper import check_and_process_messages

        mock_session = MagicMock()
        mock_session.processed_msg_id = "msg_processed"

        mock_latest_msg = MagicMock()
        mock_latest_msg.msg_id = "msg_latest"

        mock_unprocessed = [
            MagicMock(role="user"),
        ]

        mock_storage = MagicMock()
        mock_storage.session.get.return_value = mock_session
        mock_storage.message.get_latest_message.return_value = mock_latest_msg
        mock_storage.message.get_unprocessed_messages.return_value = mock_unprocessed
        mock_worker_manager = MagicMock()
        mock_worker_manager.is_session_idle.return_value = True

        with patch('topsailai_server.agent_daemon.storage.processor_helper.format_pending_messages') as mock_format:
            mock_format.return_value = ""  # Empty formatted messages

            with patch('topsailai_server.agent_daemon.storage.processor_helper.logger') as mock_logger:
                result = check_and_process_messages(
                    session_id="test_session",
                    storage=mock_storage,
                    worker_manager=mock_worker_manager
                )

        assert result is None
        mock_logger.info.assert_called()
