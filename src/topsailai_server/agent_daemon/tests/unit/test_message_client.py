#!/usr/bin/env python3
"""
Unit Tests for MessageClient

Test IDs: U-018 to U-023
- U-018: MessageClient initialization
- U-019: send_message() success
- U-020: list_messages() success
- U-021: list_messages() with filters
- U-022: list_messages() with task info
- U-023: MessageClient error handling
"""

import unittest
from unittest.mock import patch, MagicMock

from topsailai_server.agent_daemon.client.message import MessageClient


class TestMessageClientInit(unittest.TestCase):
    """Test MessageClient initialization (U-018)"""

    def test_init_default_values(self):
        """U-018: MessageClient initialization with default values"""
        with patch('topsailai_server.agent_daemon.client.base.requests.Session') as mock_session:
            client = MessageClient()
            self.assertEqual(client.base_url, "http://127.0.0.1:7373")

    def test_init_custom_url(self):
        """U-018: MessageClient initialization with custom URL"""
        with patch('topsailai_server.agent_daemon.client.base.requests.Session') as mock_session:
            client = MessageClient(base_url="http://custom:8080")
            self.assertEqual(client.base_url, "http://custom:8080")

    def test_init_env_override(self):
        """U-018: MessageClient initialization with environment variable override"""
        with patch.dict('os.environ', {
            'TOPSAILAI_AGENT_DAEMON_HOST': 'env-host',
            'TOPSAILAI_AGENT_DAEMON_PORT': '9999'
        }):
            with patch('topsailai_server.agent_daemon.client.base.requests.Session') as mock_session:
                client = MessageClient()
                self.assertEqual(client.base_url, "http://env-host:9999")


class TestSendMessage(unittest.TestCase):
    """Test send_message() method (U-019)"""

    def setUp(self):
        """Set up test fixtures"""
        self.mock_session = MagicMock()
        self.mock_session.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"code": 0, "data": {"msg_id": "msg-123"}, "message": "success"}
        )

    @patch('topsailai_server.agent_daemon.client.base.BaseClient.get')
    @patch('topsailai_server.agent_daemon.client.base.BaseClient.post')
    def test_send_message_success(self, mock_post, mock_get):
        """U-019: send_message() success"""
        mock_post.return_value = {"code": 0, "data": {"msg_id": "msg-123"}, "message": "success"}

        client = MessageClient()
        result = client.send_message("session-123", "Hello, world!")

        # Verify POST was called with correct endpoint
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertEqual(call_args[0][0], "/api/v1/message")

        # Verify request data
        json_data = call_args[1]['json_data']
        self.assertEqual(json_data['message'], "Hello, world!")
        self.assertEqual(json_data['session_id'], "session-123")
        self.assertEqual(json_data['role'], "user")

        # Verify result
        self.assertEqual(result['code'], 0)
        self.assertEqual(result['data']['msg_id'], "msg-123")

    @patch('topsailai_server.agent_daemon.client.base.BaseClient.get')
    @patch('topsailai_server.agent_daemon.client.base.BaseClient.post')
    def test_send_message_with_role(self, mock_post, mock_get):
        """U-019: send_message() with custom role"""
        mock_post.return_value = {"code": 0, "data": {}, "message": "success"}

        client = MessageClient()
        client.send_message("session-123", "Assistant response", role="assistant")

        call_args = mock_post.call_args
        json_data = call_args[1]['json_data']
        self.assertEqual(json_data['role'], "assistant")

    @patch('topsailai_server.agent_daemon.client.base.BaseClient.get')
    @patch('topsailai_server.agent_daemon.client.base.BaseClient.post')
    def test_send_message_with_processed_msg_id(self, mock_post, mock_get):
        """U-019: send_message() with processed_msg_id"""
        mock_post.return_value = {"code": 0, "data": {}, "message": "success"}

        client = MessageClient()
        client.send_message("session-123", "Callback message", processed_msg_id="msg-100")

        call_args = mock_post.call_args
        json_data = call_args[1]['json_data']
        self.assertEqual(json_data['processed_msg_id'], "msg-100")

    @patch('topsailai_server.agent_daemon.client.base.BaseClient.get')
    @patch('topsailai_server.agent_daemon.client.base.BaseClient.post')
    def test_send_message_verbose(self, mock_post, mock_get):
        """U-019: send_message() with verbose output"""
        mock_post.return_value = {"code": 0, "data": {}, "message": "success"}

        client = MessageClient()
        # Should not raise any exceptions
        result = client.send_message("session-123", "Hello", verbose=True)
        self.assertIsNotNone(result)


class TestListMessages(unittest.TestCase):
    """Test list_messages() method (U-020, U-021, U-022)"""

    def setUp(self):
        """Set up test fixtures"""
        self.mock_messages = [
            {
                "msg_id": "msg-001",
                "session_id": "session-123",
                "role": "user",
                "message": "First message",
                "create_time": "2026-04-14T09:32:51",
                "update_time": "2026-04-14T09:32:51",
                "task_id": None,
                "task_result": None
            },
            {
                "msg_id": "msg-002",
                "session_id": "session-123",
                "role": "assistant",
                "message": "Second message",
                "create_time": "2026-04-14T09:35:51",
                "update_time": "2026-04-14T09:35:51",
                "task_id": "task-001",
                "task_result": "Task completed successfully"
            }
        ]

    @patch('topsailai_server.agent_daemon.client.base.BaseClient.get')
    def test_list_messages_success(self, mock_get):
        """U-020: list_messages() success"""
        mock_get.return_value = self.mock_messages

        client = MessageClient()
        result = client.list_messages("session-123")

        # Verify GET was called with correct endpoint
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        self.assertEqual(call_args[0][0], "/api/v1/message")

        # Verify query parameters
        params = call_args[1]['params']
        self.assertEqual(params['session_id'], "session-123")
        self.assertEqual(params['offset'], 0)
        self.assertEqual(params['limit'], 1000)

        # Verify result
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['msg_id'], "msg-001")

    @patch('topsailai_server.agent_daemon.client.base.BaseClient.get')
    def test_list_messages_with_filters(self, mock_get):
        """U-021: list_messages() with filters"""
        mock_get.return_value = self.mock_messages

        client = MessageClient()
        result = client.list_messages(
            "session-123",
            start_time="2026-04-14T00:00:00",
            end_time="2026-04-14T23:59:59",
            offset=10,
            limit=50,
            sort_key="update_time",
            order_by="asc"
        )

        # Verify query parameters
        params = mock_get.call_args[1]['params']
        self.assertEqual(params['start_time'], "2026-04-14T00:00:00")
        self.assertEqual(params['end_time'], "2026-04-14T23:59:59")
        self.assertEqual(params['offset'], 10)
        self.assertEqual(params['limit'], 50)
        self.assertEqual(params['sort_key'], "update_time")
        self.assertEqual(params['order_by'], "asc")

    @patch('topsailai_server.agent_daemon.client.base.BaseClient.get')
    def test_list_messages_with_task_info(self, mock_get):
        """U-022: list_messages() with task_id and task_result"""
        mock_get.return_value = self.mock_messages

        client = MessageClient()
        result = client.list_messages("session-123")

        # Verify message with task info is included
        msg_with_task = result[1]
        self.assertEqual(msg_with_task['task_id'], "task-001")
        self.assertEqual(msg_with_task['task_result'], "Task completed successfully")

    @patch('topsailai_server.agent_daemon.client.base.BaseClient.get')
    def test_list_messages_empty(self, mock_get):
        """U-020: list_messages() with empty result"""
        mock_get.return_value = []

        client = MessageClient()
        result = client.list_messages("session-123")

        self.assertEqual(len(result), 0)

    @patch('topsailai_server.agent_daemon.client.base.BaseClient.get')
    def test_list_messages_verbose(self, mock_get):
        """U-020: list_messages() with verbose output"""
        mock_get.return_value = self.mock_messages

        client = MessageClient()
        # Should not raise any exceptions
        result = client.list_messages("session-123", verbose=True)
        self.assertEqual(len(result), 2)


class TestMessageClientErrorHandling(unittest.TestCase):
    """Test error handling (U-023)"""

    @patch('topsailai_server.agent_daemon.client.base.BaseClient.get')
    @patch('topsailai_server.agent_daemon.client.base.BaseClient.post')
    def test_send_message_api_error(self, mock_post, mock_get):
        """U-023: send_message() API error handling"""
        mock_post.side_effect = Exception("API error: Invalid session")

        client = MessageClient()
        with self.assertRaises(Exception) as context:
            client.send_message("invalid-session", "test")

        self.assertIn("API error", str(context.exception))

    @patch('topsailai_server.agent_daemon.client.base.BaseClient.get')
    def test_list_messages_api_error(self, mock_get):
        """U-023: list_messages() API error handling"""
        mock_get.side_effect = Exception("API error: Session not found")

        client = MessageClient()
        with self.assertRaises(Exception) as context:
            client.list_messages("invalid-session")

        self.assertIn("API error", str(context.exception))

    @patch('topsailai_server.agent_daemon.client.base.BaseClient.get')
    @patch('topsailai_server.agent_daemon.client.base.BaseClient.post')
    def test_send_message_http_error(self, mock_post, mock_get):
        """U-023: send_message() HTTP error handling"""
        mock_post.side_effect = Exception("Connection refused")

        client = MessageClient()
        with self.assertRaises(Exception) as context:
            client.send_message("session-123", "test")

        self.assertIn("Connection refused", str(context.exception))

    @patch('topsailai_server.agent_daemon.client.base.BaseClient.get')
    def test_list_messages_http_error(self, mock_get):
        """U-023: list_messages() HTTP error handling"""
        mock_get.side_effect = Exception("Connection timeout")

        client = MessageClient()
        with self.assertRaises(Exception) as context:
            client.list_messages("session-123")

        self.assertIn("Connection timeout", str(context.exception))


class TestPrintMessage(unittest.TestCase):
    """Test _print_message() display formatting"""

    def test_print_message_with_task_info(self):
        """Display formatting: message with task_id and task_result"""
        client = MessageClient()
        message = {
            "msg_id": "msg-123",
            "session_id": "session-456",
            "role": "user",
            "message": "Test message content",
            "create_time": "2026-04-14T09:32:51",
            "task_id": "task-789",
            "task_result": "Result content"
        }

        # Should not raise any exceptions
        client._print_message(message)

    def test_print_message_without_task_info(self):
        """Display formatting: message without task_id and task_result"""
        client = MessageClient()
        message = {
            "msg_id": "msg-123",
            "session_id": "session-456",
            "role": "assistant",
            "message": "Response content",
            "create_time": "2026-04-14T09:35:51",
            "task_id": None,
            "task_result": None
        }

        # Should not raise any exceptions
        client._print_message(message)


if __name__ == '__main__':
    unittest.main()
