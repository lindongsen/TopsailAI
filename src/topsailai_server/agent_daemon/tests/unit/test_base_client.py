#!/usr/bin/env python3
"""
Unit Tests for BaseClient

This module contains unit tests for the BaseClient class in the
agent_daemon client package.

Test IDs: U-001 to U-009
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from topsailai_server.agent_daemon.client.base import BaseClient, APIError


class TestBaseClientInit(unittest.TestCase):
    """Test cases for BaseClient initialization (U-001, U-002)."""

    def test_base_client_init_default_url(self):
        """U-001: Test BaseClient initialization with default URL."""
        client = BaseClient()
        self.assertEqual(client.base_url, "http://127.0.0.1:7373")
        self.assertEqual(client.timeout, 10)

    def test_base_client_init_custom_url(self):
        """U-001: Test BaseClient initialization with custom URL."""
        client = BaseClient(base_url="http://localhost:8080", timeout=30)
        self.assertEqual(client.base_url, "http://localhost:8080")
        self.assertEqual(client.timeout, 30)

    def test_base_client_init_url_strips_trailing_slash(self):
        """U-001: Test that trailing slashes are stripped from URL."""
        client = BaseClient(base_url="http://localhost:8080/")
        self.assertEqual(client.base_url, "http://localhost:8080")

    @patch.dict(os.environ, {"TOPSAILAI_AGENT_DAEMON_HOST": "192.168.1.100", "TOPSAILAI_AGENT_DAEMON_PORT": "9000"})
    def test_base_client_init_from_env(self):
        """U-001: Test BaseClient initialization from environment variables."""
        client = BaseClient()
        self.assertEqual(client.base_url, "http://192.168.1.100:9000")


class TestBaseClientGet(unittest.TestCase):
    """Test cases for BaseClient GET requests (U-003, U-004)."""

    @patch("topsailai_server.agent_daemon.client.base.requests.request")
    def test_base_client_get_success(self, mock_request):
        """U-003: Test GET request success."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": {"session_id": "test123"}, "message": "success"}
        mock_request.return_value = mock_response

        client = BaseClient()
        result = client.get("/api/v1/session/test123")

        self.assertEqual(result, {"session_id": "test123"})
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        self.assertEqual(call_args.kwargs["method"], "GET")
        self.assertIn("/api/v1/session/test123", call_args.kwargs["url"])

    @patch("topsailai_server.agent_daemon.client.base.requests.request")
    def test_base_client_get_with_params(self, mock_request):
        """U-004: Test GET request with query parameters."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": [], "message": "success"}
        mock_request.return_value = mock_response

        client = BaseClient()
        result = client.get("/api/v1/session", params={"limit": 10, "offset": 0})

        self.assertEqual(result, [])
        call_args = mock_request.call_args
        self.assertEqual(call_args.kwargs["params"], {"limit": 10, "offset": 0})


class TestBaseClientPost(unittest.TestCase):
    """Test cases for BaseClient POST requests (U-005, U-006)."""

    @patch("topsailai_server.agent_daemon.client.base.requests.request")
    def test_base_client_post_success(self, mock_request):
        """U-005: Test POST request with JSON data."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": {"msg_id": "msg123"}, "message": "success"}
        mock_request.return_value = mock_response

        client = BaseClient()
        result = client.post("/api/v1/message", json_data={"message": "hello", "session_id": "sess123"})

        self.assertEqual(result, {"msg_id": "msg123"})
        call_args = mock_request.call_args
        self.assertEqual(call_args.kwargs["method"], "POST")
        self.assertEqual(call_args.kwargs["json"], {"message": "hello", "session_id": "sess123"})

    @patch("topsailai_server.agent_daemon.client.base.requests.request")
    def test_base_client_post_json_str(self, mock_request):
        """U-006: Test POST with JSON string."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": {"task_id": "task456"}, "message": "success"}
        mock_request.return_value = mock_response

        client = BaseClient()
        result = client.post("/api/v1/task", json_data={"task_id": "task456", "task_result": "done"})

        self.assertEqual(result, {"task_id": "task456"})
        call_args = mock_request.call_args
        self.assertEqual(call_args.kwargs["json"], {"task_id": "task456", "task_result": "done"})


class TestBaseClientErrorHandling(unittest.TestCase):
    """Test cases for BaseClient error handling (U-007, U-008)."""

    @patch("topsailai_server.agent_daemon.client.base.requests.request")
    def test_base_client_api_error(self, mock_request):
        """U-007: Test API error response (code != 0)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 1001, "data": None, "message": "Session not found"}
        mock_request.return_value = mock_response

        client = BaseClient()
        with self.assertRaises(APIError) as context:
            client.get("/api/v1/session/invalid")

        self.assertEqual(context.exception.code, 1001)
        self.assertEqual(context.exception.message, "Session not found")

    @patch("topsailai_server.agent_daemon.client.base.requests.request")
    def test_base_client_http_error(self, mock_request):
        """U-008: Test HTTP error (404, 500)."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_request.return_value = mock_response

        client = BaseClient()
        with self.assertRaises(APIError) as context:
            client.get("/api/v1/session/invalid")

        self.assertEqual(context.exception.code, 404)
        self.assertIn("Not Found", str(context.exception))

    @patch("topsailai_server.agent_daemon.client.base.requests.request")
    def test_base_client_connection_error(self, mock_request):
        """U-007: Test connection failure."""
        import requests
        mock_request.side_effect = requests.exceptions.ConnectionError("Connection refused")

        client = BaseClient()
        with self.assertRaises(requests.exceptions.ConnectionError):
            client.get("/api/v1/session")

    @patch("topsailai_server.agent_daemon.client.base.requests.request")
    def test_base_client_timeout_error(self, mock_request):
        """U-007: Test request timeout."""
        import requests
        mock_request.side_effect = requests.exceptions.Timeout("Request timed out")

        client = BaseClient()
        with self.assertRaises(requests.exceptions.Timeout):
            client.get("/api/v1/session")


class TestFormatTime(unittest.TestCase):
    """Test cases for format_time utility function (U-008, U-009)."""

    def test_format_time_iso_format(self):
        """U-008: Test time formatting with ISO format."""
        result = BaseClient.format_time("2026-04-13T23:27:53.123456")
        self.assertEqual(result, "2026-04-13 23:27:53")

    def test_format_time_iso_format_no_microseconds(self):
        """U-008: Test time formatting without microseconds."""
        result = BaseClient.format_time("2026-04-13T23:27:53")
        self.assertEqual(result, "2026-04-13 23:27:53")

    def test_format_time_none(self):
        """U-009: Test format_time with None input."""
        result = BaseClient.format_time(None)
        self.assertEqual(result, "N/A")

    def test_format_time_empty_string(self):
        """U-009: Test format_time with empty string."""
        result = BaseClient.format_time("")
        self.assertEqual(result, "N/A")

    def test_format_time_already_formatted(self):
        """U-008: Test format_time with already formatted string."""
        result = BaseClient.format_time("2026-04-13 23:27:53")
        self.assertEqual(result, "2026-04-13 23:27:53")


if __name__ == "__main__":
    unittest.main()
