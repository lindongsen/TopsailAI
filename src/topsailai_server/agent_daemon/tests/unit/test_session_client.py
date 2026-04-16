#!/usr/bin/env python3
"""
Unit Tests for SessionClient

This module contains unit tests for the SessionClient class,
covering all session-related API operations.

Test IDs: U-010 to U-017
"""

import unittest
from unittest.mock import MagicMock, patch

from topsailai_server.agent_daemon.client.session import SessionClient
from topsailai_server.agent_daemon.client.base import APIError


class TestSessionClientInit(unittest.TestCase):
    """Test SessionClient initialization (U-010)."""

    def test_init_default(self):
        """Test SessionClient initialization with default values."""
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__') as mock_init:
            mock_init.return_value = None
            client = SessionClient()
            mock_init.assert_called_once()

    def test_init_with_base_url(self):
        """Test SessionClient initialization with custom base URL."""
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__') as mock_init:
            mock_init.return_value = None
            client = SessionClient(base_url="http://localhost:8080")
            mock_init.assert_called_once_with(base_url="http://localhost:8080")

    def test_init_with_timeout(self):
        """Test SessionClient initialization with custom timeout."""
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__') as mock_init:
            mock_init.return_value = None
            client = SessionClient(timeout=30)
            mock_init.assert_called_once_with(timeout=30)


class TestHealthCheck(unittest.TestCase):
    """Test health_check() method (U-011)."""

    def test_health_check_success(self):
        """Test health_check returns True on success."""
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__', return_value=None):
            client = SessionClient()
            client.get = MagicMock(return_value={"status": "ok"})
            
            result = client.health_check()
            self.assertTrue(result)
            client.get.assert_called_once_with("/health", timeout=5)

    def test_health_check_failure(self):
        """Test health_check returns False on failure."""
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__', return_value=None):
            client = SessionClient()
            client.get = MagicMock(side_effect=Exception("Connection refused"))
            
            result = client.health_check()
            self.assertFalse(result)


class TestListSessions(unittest.TestCase):
    """Test list_sessions() method (U-012, U-013)."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_sessions = [
            {
                "session_id": "session-123",
                "session_name": "session-123",
                "task": "Test task",
                "create_time": "2026-04-13T23:27:53.123456",
                "update_time": "2026-04-13T23:30:00.000000",
                "processed_msg_id": "msg-001"
            },
            {
                "session_id": "session-456",
                "session_name": "My Session",
                "task": "Another task",
                "create_time": "2026-04-14T10:00:00.000000",
                "update_time": "2026-04-14T10:05:00.000000",
                "processed_msg_id": "msg-002"
            }
        ]

    def test_list_sessions_success(self):
        """Test list_sessions returns sessions on success (U-012)."""
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__', return_value=None):
            client = SessionClient()
            client.get = MagicMock(return_value=self.mock_sessions)
            client._print_session = MagicMock()
            
            result = client.list_sessions()
            
            self.assertEqual(len(result), 2)
            client.get.assert_called_once()
            call_args = client.get.call_args
            self.assertEqual(call_args[0][0], "/api/v1/session")

    def test_list_sessions_with_filters(self):
        """Test list_sessions with filters (U-013)."""
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__', return_value=None):
            client = SessionClient()
            client.get = MagicMock(return_value=[self.mock_sessions[0]])
            client._print_session = MagicMock()
            
            result = client.list_sessions(
                session_ids=["session-123"],
                start_time="2026-04-13T00:00:00",
                end_time="2026-04-14T00:00:00",
                offset=0,
                limit=100,
                sort_key="create_time",
                order_by="desc"
            )
            
            self.assertEqual(len(result), 1)
            call_args = client.get.call_args
            params = call_args[1]["params"]
            self.assertEqual(params["session_ids"], ["session-123"])
            self.assertEqual(params["start_time"], "2026-04-13T00:00:00")
            self.assertEqual(params["end_time"], "2026-04-14T00:00:00")
            self.assertEqual(params["offset"], 0)
            self.assertEqual(params["limit"], 100)

    def test_list_sessions_empty(self):
        """Test list_sessions with no results."""
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__', return_value=None):
            client = SessionClient()
            client.get = MagicMock(return_value=[])
            
            result = client.list_sessions()
            
            self.assertEqual(result, [])

    def test_list_sessions_verbose(self):
        """Test list_sessions with verbose output."""
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__', return_value=None):
            client = SessionClient()
            client.get = MagicMock(return_value=self.mock_sessions)
            
            result = client.list_sessions(verbose=True)
            
            self.assertEqual(len(result), 2)


class TestGetSession(unittest.TestCase):
    """Test get_session() method (U-014)."""

    def test_get_session_success(self):
        """Test get_session returns session details on success (U-014)."""
        mock_session = {
            "session_id": "session-123",
            "session_name": "Test Session",
            "task": "Test task content",
            "create_time": "2026-04-13T23:27:53.123456",
            "update_time": "2026-04-13T23:30:00.000000",
            "processed_msg_id": "msg-001",
            "status": "idle"
        }
        
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__', return_value=None):
            client = SessionClient()
            client.get = MagicMock(return_value=mock_session)
            
            result = client.get_session("session-123")
            
            self.assertEqual(result["session_id"], "session-123")
            self.assertEqual(result["session_name"], "Test Session")
            self.assertEqual(result["status"], "idle")
            client.get.assert_called_once_with("/api/v1/session/session-123")

    def test_get_session_verbose(self):
        """Test get_session with verbose output."""
        mock_session = {
            "session_id": "session-123",
            "session_name": "Test Session",
            "task": "Test task",
            "create_time": "2026-04-13T23:27:53.123456",
            "update_time": "2026-04-13T23:30:00.000000",
            "processed_msg_id": "msg-001",
            "status": "idle"
        }
        
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__', return_value=None):
            client = SessionClient()
            client.get = MagicMock(return_value=mock_session)
            
            result = client.get_session("session-123", verbose=True)
            
            self.assertEqual(result["session_id"], "session-123")


class TestProcessSession(unittest.TestCase):
    """Test process_session() method (U-015)."""

    def test_process_session_success(self):
        """Test process_session returns processing result (U-015)."""
        mock_result = {
            "processed": True,
            "message": "Processing started",
            "processing_msg_id": "msg-003",
            "messages": [{"msg_id": "msg-003", "content": "test"}],
            "processor_pid": 12345
        }
        
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__', return_value=None):
            client = SessionClient()
            client.post = MagicMock(return_value=mock_result)
            
            result = client.process_session("session-123")
            
            self.assertTrue(result["processed"])
            self.assertEqual(result["processor_pid"], 12345)
            client.post.assert_called_once()
            call_args = client.post.call_args
            self.assertEqual(call_args[0][0], "/api/v1/session/process")
            self.assertEqual(call_args[1]["json_data"]["session_id"], "session-123")

    def test_process_session_no_pending(self):
        """Test process_session when no pending messages."""
        mock_result = {
            "processed": False,
            "message": "No pending messages"
        }
        
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__', return_value=None):
            client = SessionClient()
            client.post = MagicMock(return_value=mock_result)
            
            result = client.process_session("session-123")
            
            self.assertFalse(result["processed"])


class TestDeleteSessions(unittest.TestCase):
    """Test delete_sessions() method (U-016)."""

    def test_delete_sessions_success(self):
        """Test delete_sessions returns deletion result (U-016)."""
        mock_result = {
            "deleted_count": 2,
            "session_ids": ["session-123", "session-456"]
        }
        
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__', return_value=None):
            client = SessionClient()
            client.delete = MagicMock(return_value=mock_result)
            
            result = client.delete_sessions(["session-123", "session-456"])
            
            self.assertEqual(result["deleted_count"], 2)
            client.delete.assert_called_once()
            call_args = client.delete.call_args
            self.assertEqual(call_args[0][0], "/api/v1/session")
            self.assertEqual(call_args[1]["params"]["session_ids"], "session-123,session-456")

    def test_delete_sessions_empty_list(self):
        """Test delete_sessions raises error for empty list."""
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__', return_value=None):
            client = SessionClient()
            
            with self.assertRaises(ValueError) as context:
                client.delete_sessions([])
            
            self.assertIn("At least one session ID is required", str(context.exception))


class TestSessionClientErrorHandling(unittest.TestCase):
    """Test SessionClient error handling (U-017)."""

    def test_list_sessions_api_error(self):
        """Test list_sessions raises APIError on API error (U-017)."""
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__', return_value=None):
            client = SessionClient()
            client.get = MagicMock(side_effect=APIError(500, "Internal server error"))
            
            with self.assertRaises(APIError) as context:
                client.list_sessions()
            
            self.assertEqual(context.exception.code, 500)

    def test_get_session_api_error(self):
        """Test get_session raises APIError on API error (U-017)."""
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__', return_value=None):
            client = SessionClient()
            client.get = MagicMock(side_effect=APIError(404, "Session not found"))
            
            with self.assertRaises(APIError) as context:
                client.get_session("nonexistent")
            
            self.assertEqual(context.exception.code, 404)

    def test_process_session_api_error(self):
        """Test process_session raises APIError on API error (U-017)."""
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__', return_value=None):
            client = SessionClient()
            client.post = MagicMock(side_effect=APIError(500, "Processing failed"))
            
            with self.assertRaises(APIError) as context:
                client.process_session("session-123")
            
            self.assertEqual(context.exception.code, 500)

    def test_delete_sessions_api_error(self):
        """Test delete_sessions raises APIError on API error (U-017)."""
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__', return_value=None):
            client = SessionClient()
            client.delete = MagicMock(side_effect=APIError(500, "Deletion failed"))
            
            with self.assertRaises(APIError) as context:
                client.delete_sessions(["session-123"])
            
            self.assertEqual(context.exception.code, 500)


class TestPrintSession(unittest.TestCase):
    """Test _print_session() method formatting."""

    def test_print_session_same_id_name(self):
        """Test _print_session when session_id equals session_name."""
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__', return_value=None):
            client = SessionClient()
            session = {
                "session_id": "session-123",
                "session_name": "session-123",
                "task": "Test task",
                "create_time": "2026-04-13T23:27:53.123456",
                "processed_msg_id": "msg-001"
            }
            
            # Should not raise any exceptions
            client._print_session(session)

    def test_print_session_different_id_name(self):
        """Test _print_session when session_id differs from session_name."""
        with patch('topsailai_server.agent_daemon.client.session.BaseClient.__init__', return_value=None):
            client = SessionClient()
            session = {
                "session_id": "session-456",
                "session_name": "My Custom Session",
                "task": "Test task",
                "create_time": "2026-04-13T23:27:53.123456",
                "processed_msg_id": "msg-001"
            }
            
            # Should not raise any exceptions
            client._print_session(session)


if __name__ == "__main__":
    unittest.main()
