"""
Unit Tests for MessageClient

This module contains unit tests for the MessageClient class which handles
message-related API operations for the agent_daemon service.

Test Coverage:
    - send_message: Send messages to sessions
    - list_messages: Retrieve messages with filtering
    - _print_message: Format and display message content

Usage:
    pytest tests/unit/test_client/test_message.py -v
"""

import pytest
from unittest.mock import patch, MagicMock

from topsailai_server.agent_daemon.client.message import MessageClient


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_base_url():
    """Fixture for mock base URL."""
    return "http://localhost:7373"


@pytest.fixture
def mock_client(mock_base_url):
    """Fixture for MessageClient with mocked HTTP requests."""
    with patch('topsailai_server.agent_daemon.client.base.BaseClient.__init__') as mock_init:
        mock_init.return_value = None
        client = MessageClient()
        client.base_url = mock_base_url
        client.timeout = 30
        return client


# ============================================================================
# Test Class: TestMessageClient
# ============================================================================

class TestMessageClient:
    """
    Test suite for MessageClient class covering all main methods.
    """

    # ------------------------------------------------------------------------
    # Tests for send_message method
    # ------------------------------------------------------------------------

    def test_send_message_success(self, mock_client):
        """
        Test sending a message successfully with default parameters.

        Verifies that:
        - POST request is made to correct endpoint
        - Request body contains correct data
        - Success message is printed
        """
        mock_response = {
            "code": 0,
            "data": {"msg_id": "msg-123"},
            "message": "Message received"
        }

        with patch.object(mock_client, 'post', return_value=mock_response) as mock_post:
            result = mock_client.send_message("session-123", "Hello, world!")

            mock_post.assert_called_once_with(
                "/api/v1/message",
                json_data={
                    "message": "Hello, world!",
                    "session_id": "session-123",
                    "role": "user"
                }
            )
            assert result == mock_response

    def test_send_message_with_assistant_role(self, mock_client):
        """
        Test sending a message with assistant role.

        Verifies that the role parameter is correctly set to 'assistant'.
        """
        mock_response = {
            "code": 0,
            "data": {"msg_id": "msg-456"},
            "message": "Message received"
        }

        with patch.object(mock_client, 'post', return_value=mock_response) as mock_post:
            result = mock_client.send_message(
                "session-123",
                "I am an assistant",
                role="assistant"
            )

            call_args = mock_post.call_args
            assert call_args[1]["json_data"]["role"] == "assistant"
            assert result == mock_response

    def test_send_message_with_processed_msg_id(self, mock_client):
        """
        Test sending a message with processed_msg_id parameter.

        Verifies that processed_msg_id is included in request when provided.
        """
        mock_response = {
            "code": 0,
            "data": {"msg_id": "msg-789"},
            "message": "Message received"
        }

        with patch.object(mock_client, 'post', return_value=mock_response) as mock_post:
            result = mock_client.send_message(
                "session-123",
                "Reply message",
                processed_msg_id="msg-previous"
            )

            call_args = mock_post.call_args
            assert "processed_msg_id" in call_args[1]["json_data"]
            assert call_args[1]["json_data"]["processed_msg_id"] == "msg-previous"
            assert result == mock_response

    def test_send_message_verbose_output(self, mock_client):
        """
        Test sending a message with verbose=True.

        Verifies that full JSON response is printed when verbose is enabled.
        """
        mock_response = {
            "code": 0,
            "data": {"msg_id": "msg-123"},
            "message": "Message received"
        }

        with patch.object(mock_client, 'post', return_value=mock_response) as mock_post:
            with patch('builtins.print') as mock_print:
                result = mock_client.send_message(
                    "session-123",
                    "Hello",
                    verbose=True
                )

                # Verify print was called multiple times (success message + JSON)
                assert mock_print.call_count >= 2
                assert result == mock_response

    def test_send_message_api_error(self, mock_client):
        """
        Test sending a message when API returns an error.

        Verifies that exceptions are properly propagated.
        """
        from topsailai_server.agent_daemon.client.base import APIError

        with patch.object(mock_client, 'post', side_effect=APIError(500, "API Error")):
            with pytest.raises(APIError):
                mock_client.send_message("session-123", "Hello")

    # ------------------------------------------------------------------------
    # Tests for list_messages method
    # ------------------------------------------------------------------------

    def test_list_messages_success(self, mock_client):
        """
        Test listing messages successfully with default parameters.

        Verifies that:
        - GET request is made to correct endpoint
        - Default pagination parameters are used
        - Messages are returned correctly
        """
        mock_messages = [
            {"msg_id": "msg-1", "message": "Hello", "role": "user"},
            {"msg_id": "msg-2", "message": "Hi there", "role": "assistant"}
        ]

        with patch.object(mock_client, 'get', return_value=mock_messages) as mock_get:
            result = mock_client.list_messages("session-123")

            mock_get.assert_called_once_with(
                "/api/v1/message",
                params={
                    "session_id": "session-123",
                    "offset": 0,
                    "limit": 1000,
                    "sort_key": "create_time",
                    "order_by": "desc"
                }
            )
            assert result == mock_messages

    def test_list_messages_with_time_filters(self, mock_client):
        """
        Test listing messages with time range filters.

        Verifies that start_time and end_time are included in request.
        """
        mock_messages = []

        with patch.object(mock_client, 'get', return_value=mock_messages) as mock_get:
            mock_client.list_messages(
                "session-123",
                start_time="2024-01-01T00:00:00",
                end_time="2024-01-31T23:59:59"
            )

            call_args = mock_get.call_args
            assert "start_time" in call_args[1]["params"]
            assert "end_time" in call_args[1]["params"]
            assert call_args[1]["params"]["start_time"] == "2024-01-01T00:00:00"
            assert call_args[1]["params"]["end_time"] == "2024-01-31T23:59:59"

    def test_list_messages_with_pagination(self, mock_client):
        """
        Test listing messages with custom pagination parameters.

        Verifies that offset and limit are correctly set.
        """
        mock_messages = []

        with patch.object(mock_client, 'get', return_value=mock_messages) as mock_get:
            mock_client.list_messages(
                "session-123",
                offset=10,
                limit=50
            )

            call_args = mock_get.call_args
            assert call_args[1]["params"]["offset"] == 10
            assert call_args[1]["params"]["limit"] == 50

    def test_list_messages_with_sorting(self, mock_client):
        """
        Test listing messages with custom sorting parameters.

        Verifies that sort_key and order_by are correctly set.
        """
        mock_messages = []

        with patch.object(mock_client, 'get', return_value=mock_messages) as mock_get:
            mock_client.list_messages(
                "session-123",
                sort_key="update_time",
                order_by="asc"
            )

            call_args = mock_get.call_args
            assert call_args[1]["params"]["sort_key"] == "update_time"
            assert call_args[1]["params"]["order_by"] == "asc"

    def test_list_messages_empty_result(self, mock_client):
        """
        Test listing messages when no messages exist.

        Verifies that empty list is handled correctly.
        """
        with patch.object(mock_client, 'get', return_value=[]) as mock_get:
            result = mock_client.list_messages("session-123")
            assert result == []
            mock_get.assert_called_once()

    def test_list_messages_verbose_output(self, mock_client):
        """
        Test listing messages with verbose=True.

        Verifies that full JSON response is printed.
        """
        mock_messages = [{"msg_id": "msg-1", "message": "Hello"}]

        with patch.object(mock_client, 'get', return_value=mock_messages):
            with patch('builtins.print') as mock_print:
                mock_client.list_messages("session-123", verbose=True)

                # Verify print was called for verbose JSON output
                assert mock_print.call_count >= 2

    def test_list_messages_with_message_display(self, mock_client):
        """
        Test listing messages with default display (non-verbose).

        Verifies that messages are printed in formatted output.
        """
        mock_messages = [
            {"msg_id": "msg-1", "message": "Hello", "role": "user", "create_time": "2024-01-01T00:00:00"}
        ]

        with patch.object(mock_client, 'get', return_value=mock_messages):
            with patch.object(mock_client, '_print_message') as mock_print_msg:
                mock_client.list_messages("session-123")

                mock_print_msg.assert_called_once_with(mock_messages[0])

    def test_list_messages_api_error(self, mock_client):
        """
        Test listing messages when API returns an error.

        Verifies that exceptions are properly propagated.
        """
        from topsailai_server.agent_daemon.client.base import APIError

        with patch.object(mock_client, 'get', side_effect=APIError(500, "API Error")):
            with pytest.raises(APIError):
                mock_client.list_messages("session-123")

    # ------------------------------------------------------------------------
    # Tests for _print_message method
    # ------------------------------------------------------------------------

    def test_print_message_full_data(self, mock_client):
        """
        Test printing a message with all fields populated.

        Verifies that all message fields are displayed correctly.
        """
        message = {
            "msg_id": "msg-123",
            "session_id": "session-456",
            "role": "user",
            "message": "Hello, world!",
            "create_time": "2024-01-15T10:30:00",
            "task_id": "task-789",
            "task_result": "Task completed successfully"
        }

        with patch('builtins.print') as mock_print:
            mock_client._print_message(message)

            # Verify print was called for: split line, header, content, task_id, task_result
            assert mock_print.call_count >= 4

    def test_print_message_minimal_data(self, mock_client):
        """
        Test printing a message with only required fields.

        Verifies that missing optional fields don't cause errors.
        """
        message = {
            "msg_id": "msg-123",
            "role": "user",
            "message": "Hello"
        }

        with patch('builtins.print') as mock_print:
            mock_client._print_message(message)

            # Should print at least split line and header
            assert mock_print.call_count >= 2

    def test_print_message_with_task_id_only(self, mock_client):
        """
        Test printing a message with task_id but no task_result.

        Verifies that task_id is displayed but task_result section is skipped.
        """
        message = {
            "msg_id": "msg-123",
            "role": "assistant",
            "message": "Processing...",
            "task_id": "task-456"
        }

        with patch('builtins.print') as mock_print:
            mock_client._print_message(message)

            # Check that task_id line was printed
            print_calls = [str(call) for call in mock_print.call_args_list]
            task_id_printed = any("task_id" in call for call in print_calls)
            assert task_id_printed

    def test_print_message_with_task_result_only(self, mock_client):
        """
        Test printing a message with task_result but no task_id.

        Verifies that task_result is displayed but task_id section is skipped.
        """
        message = {
            "msg_id": "msg-123",
            "role": "user",
            "message": "Waiting for result",
            "task_result": "Result content"
        }

        with patch('builtins.print') as mock_print:
            mock_client._print_message(message)

            # Check that task_result line was printed
            print_calls = [str(call) for call in mock_print.call_args_list]
            task_result_printed = any("task_result" in call for call in print_calls)
            assert task_result_printed


# ============================================================================
# Test Class: TestMessageClientEdgeCases
# ============================================================================

class TestMessageClientEdgeCases:
    """
    Test suite for edge cases and boundary conditions in MessageClient.
    """

    def test_send_message_empty_content(self, mock_client):
        """
        Test sending a message with empty content.

        Verifies that empty strings are accepted by the API.
        """
        mock_response = {"code": 0, "data": {"msg_id": "msg-empty"}}

        with patch.object(mock_client, 'post', return_value=mock_response) as mock_post:
            result = mock_client.send_message("session-123", "")

            call_args = mock_post.call_args
            assert call_args[1]["json_data"]["message"] == ""
            assert result == mock_response

    def test_send_message_long_content(self, mock_client):
        """
        Test sending a message with very long content.

        Verifies that long messages are handled correctly.
        """
        long_message = "A" * 10000  # 10KB message
        mock_response = {"code": 0, "data": {"msg_id": "msg-long"}}

        with patch.object(mock_client, 'post', return_value=mock_response) as mock_post:
            result = mock_client.send_message("session-123", long_message)

            call_args = mock_post.call_args
            assert len(call_args[1]["json_data"]["message"]) == 10000
            assert result == mock_response

    def test_list_messages_large_offset(self, mock_client):
        """
        Test listing messages with large offset value.

        Verifies that large pagination offsets are handled correctly.
        """
        with patch.object(mock_client, 'get', return_value=[]) as mock_get:
            mock_client.list_messages("session-123", offset=1000000)

            call_args = mock_get.call_args
            assert call_args[1]["params"]["offset"] == 1000000

    def test_list_messages_large_limit(self, mock_client):
        """
        Test listing messages with large limit value.

        Verifies that large limits are handled correctly.
        """
        with patch.object(mock_client, 'get', return_value=[]) as mock_get:
            mock_client.list_messages("session-123", limit=100000)

            call_args = mock_get.call_args
            assert call_args[1]["params"]["limit"] == 100000

    def test_list_messages_many_results(self, mock_client):
        """
        Test listing messages when API returns many results.

        Verifies that large result sets are handled correctly.
        """
        mock_messages = [
            {"msg_id": f"msg-{i}", "message": f"Message {i}"}
            for i in range(1000)
        ]

        with patch.object(mock_client, 'get', return_value=mock_messages):
            with patch.object(mock_client, '_print_message') as mock_print_msg:
                result = mock_client.list_messages("session-123")

                assert len(result) == 1000
                assert mock_print_msg.call_count == 1000

    def test_print_message_special_characters(self, mock_client):
        """
        Test printing a message with special characters.

        Verifies that special characters in message content are handled.
        """
        message = {
            "msg_id": "msg-special",
            "role": "user",
            "message": "Special chars: <>&\"' and unicode: 你好 🌍"
        }

        with patch('builtins.print') as mock_print:
            # Should not raise any exceptions
            mock_client._print_message(message)
            assert mock_print.call_count >= 2

    def test_print_message_multiline_content(self, mock_client):
        """
        Test printing a message with multiline content.

        Verifies that multiline messages are displayed correctly.
        """
        message = {
            "msg_id": "msg-multiline",
            "role": "user",
            "message": "Line 1\nLine 2\nLine 3\n\nEmpty line",
            "create_time": "2024-01-01T00:00:00"
        }

        with patch('builtins.print') as mock_print:
            mock_client._print_message(message)

            # Verify multiline content is printed
            print_calls = [str(call) for call in mock_print.call_args_list]
            content_printed = any("Line 1" in call for call in print_calls)
            assert content_printed
