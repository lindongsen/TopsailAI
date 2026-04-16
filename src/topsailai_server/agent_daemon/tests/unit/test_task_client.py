#!/usr/bin/env python3
"""
Unit Tests for TaskClient

This module contains unit tests for the TaskClient class,
covering task-related API operations and display formatting.

Test IDs: U-031 to U-037
"""

import unittest
from unittest.mock import MagicMock, patch


class TestTaskClientInit(unittest.TestCase):
    """Test TaskClient initialization (U-031)"""
    
    def test_task_client_init_default(self):
        """Test TaskClient initialization with default base_url"""
        from topsailai_server.agent_daemon.client import TaskClient
        
        client = TaskClient()
        self.assertEqual(client.base_url, "http://127.0.0.1:7373")
        self.assertEqual(client.timeout, 10)
    
    def test_task_client_init_custom(self):
        """Test TaskClient initialization with custom base_url"""
        from topsailai_server.agent_daemon.client import TaskClient
        
        client = TaskClient(base_url="http://custom:8080", timeout=60)
        self.assertEqual(client.base_url, "http://custom:8080")
        self.assertEqual(client.timeout, 60)
    
    def test_task_client_init_from_env(self):
        """Test TaskClient initialization from environment variable"""
        from topsailai_server.agent_daemon.client import TaskClient
        
        with patch.dict('os.environ', {'TOPSAILAI_AGENT_DAEMON_HOST': 'env', 'TOPSAILAI_AGENT_DAEMON_PORT': '9999'}, clear=True):
            client = TaskClient()
            self.assertEqual(client.base_url, "http://env:9999")


class TestSetTaskResult(unittest.TestCase):
    """Test set_task_result method (U-032)"""
    
    def setUp(self):
        """Set up test fixtures"""
        from topsailai_server.agent_daemon.client import TaskClient
        self.client = TaskClient()
        self.client.get = MagicMock()
        self.client.post = MagicMock()
    
    def test_set_task_result_success(self):
        """Test setting task result successfully (U-032)"""
        self.client.post.return_value = {
            "code": 0,
            "data": {"session_id": "test-session", "task_id": "task-123"},
            "message": "Task result set successfully"
        }
        
        result = self.client.set_task_result(
            session_id="test-session",
            processed_msg_id="msg-456",
            task_id="task-123",
            task_result="Task completed successfully"
        )
        
        self.client.post.assert_called_once()
        call_args = self.client.post.call_args
        self.assertEqual(call_args[0][0], "/api/v1/task")
        self.assertEqual(call_args[1]["json_data"]["session_id"], "test-session")
        self.assertEqual(call_args[1]["json_data"]["task_id"], "task-123")
        self.assertEqual(call_args[1]["json_data"]["task_result"], "Task completed successfully")
        self.assertEqual(result["code"], 0)
    
    def test_set_task_result_with_verbose(self):
        """Test set_task_result with verbose output"""
        self.client.post.return_value = {"code": 0, "data": {}, "message": "OK"}
        
        result = self.client.set_task_result(
            session_id="session-1",
            processed_msg_id="msg-1",
            task_id="task-1",
            task_result="result",
            verbose=True
        )
        self.assertEqual(result["code"], 0)
    
    def test_set_task_result_empty_result(self):
        """Test setting empty task result (E-010)"""
        self.client.post.return_value = {"code": 0, "data": {}, "message": "OK"}
        
        result = self.client.set_task_result(
            session_id="session-1",
            processed_msg_id="msg-1",
            task_id="task-1",
            task_result=""
        )
        
        self.assertEqual(result["code"], 0)
        call_args = self.client.post.call_args
        self.assertEqual(call_args[1]["json_data"]["task_result"], "")
    
    def test_set_task_result_api_error(self):
        """Test set_task_result with API error"""
        from topsailai_server.agent_daemon.client.base import APIError
        
        self.client.post.side_effect = APIError(code=404, message="Task not found")
        
        with self.assertRaises(APIError) as context:
            self.client.set_task_result(
                session_id="session-1",
                processed_msg_id="msg-1",
                task_id="task-1",
                task_result="result"
            )
        
        self.assertIn("Task not found", str(context.exception))


class TestListTasks(unittest.TestCase):
    """Test list_tasks method (U-033, U-034)"""
    
    def setUp(self):
        """Set up test fixtures"""
        from topsailai_server.agent_daemon.client import TaskClient
        self.client = TaskClient()
        self.client.get = MagicMock()
        self.client.post = MagicMock()
    
    def test_list_tasks_success(self):
        """Test listing tasks successfully (U-033)"""
        mock_tasks = [
            {
                "task_id": "task-1",
                "session_id": "session-1",
                "msg_id": "msg-1",
                "message": "First task",
                "create_time": "2026-04-14T13:31:36",
                "task_result": "Result 1"
            },
            {
                "task_id": "task-2",
                "session_id": "session-1",
                "msg_id": "msg-2",
                "message": "Second task",
                "create_time": "2026-04-14T14:00:00",
                "task_result": None
            }
        ]
        self.client.get.return_value = mock_tasks
        
        result = self.client.list_tasks("session-1")
        
        self.client.get.assert_called_once()
        call_args = self.client.get.call_args
        self.assertEqual(call_args[0][0], "/api/v1/task")
        self.assertEqual(call_args[1]["params"]["session_id"], "session-1")
        self.assertEqual(len(result), 2)
    
    def test_list_tasks_with_filters(self):
        """Test listing tasks with filters (U-033)"""
        self.client.get.return_value = [
            {"task_id": "task-1", "session_id": "session-1", "msg_id": "msg-1", "message": "Task 1", "create_time": "2026-04-14T13:31:36"}
        ]
        
        result = self.client.list_tasks(
            session_id="session-1",
            task_ids=["task-1", "task-2"],
            start_time="2026-04-14T00:00:00",
            end_time="2026-04-15T00:00:00",
            offset=10,
            limit=50,
            sort_key="update_time",
            order_by="asc"
        )
        
        call_args = self.client.get.call_args
        params = call_args[1]["params"]
        self.assertEqual(params["task_ids"], ["task-1", "task-2"])
        self.assertEqual(params["start_time"], "2026-04-14T00:00:00")
        self.assertEqual(params["end_time"], "2026-04-15T00:00:00")
        self.assertEqual(params["offset"], 10)
        self.assertEqual(params["limit"], 50)
        self.assertEqual(params["sort_key"], "update_time")
        self.assertEqual(params["order_by"], "asc")
    
    def test_list_tasks_empty(self):
        """Test listing tasks when empty (U-034)"""
        self.client.get.return_value = []
        
        result = self.client.list_tasks("session-1")
        
        self.assertEqual(result, [])
    
    def test_list_tasks_verbose(self):
        """Test list_tasks with verbose output"""
        self.client.get.return_value = [
            {"task_id": "task-1", "session_id": "session-1", "msg_id": "msg-1", "message": "Task 1", "create_time": "2026-04-14T13:31:36"}
        ]
        
        result = self.client.list_tasks("session-1", verbose=True)
        self.assertEqual(len(result), 1)
    
    def test_list_tasks_api_error(self):
        """Test list_tasks with API error"""
        from topsailai_server.agent_daemon.client.base import APIError
        
        self.client.get.side_effect = APIError(code=404, message="Session not found")
        
        with self.assertRaises(APIError) as context:
            self.client.list_tasks("session-1")
        
        self.assertIn("Session not found", str(context.exception))


class TestPrintTask(unittest.TestCase):
    """Test task display formatting (U-035, U-036, U-037)"""
    
    def setUp(self):
        """Set up test fixtures"""
        from topsailai_server.agent_daemon.client import TaskClient
        self.client = TaskClient()
        self.client.get = MagicMock()
        self.client.post = MagicMock()
    
    def test_print_task_format(self):
        """Test task display format (U-035, D-004)"""
        task = {
            "task_id": "task-abc",
            "session_id": "session-xyz",
            "msg_id": "msg-123",
            "message": "Build a feature",
            "create_time": "2026-04-14T13:31:36",
            "task_result": None
        }
        
        import io
        import sys
        
        captured_output = io.StringIO()
        sys.stdout = captured_output
        self.client._print_task(task)
        sys.stdout = sys.__stdout__
        
        output = captured_output.getvalue()
        
        self.assertIn("[2026-04-14 13:31:36] task=[task-abc] session=[session-xyz] msg=[msg-123]", output)
        self.assertNotIn("T13:31:36", output)
        self.assertIn("Task: Build a feature", output)
    
    def test_print_task_with_result(self):
        """Test task display with result (U-036, D-005)"""
        task = {
            "task_id": "task-abc",
            "session_id": "session-xyz",
            "msg_id": "msg-123",
            "message": "Build a feature",
            "create_time": "2026-04-14T13:31:36",
            "task_result": "Feature completed successfully"
        }
        
        import io
        import sys
        
        captured_output = io.StringIO()
        sys.stdout = captured_output
        self.client._print_task(task)
        sys.stdout = sys.__stdout__
        
        output = captured_output.getvalue()
        
        self.assertIn("---", output)
        self.assertIn("Feature completed successfully", output)
    
    def test_print_task_full_message(self):
        """Test that full message content is displayed (U-037, D-007)"""
        long_message = "A" * 500
        task = {
            "task_id": "task-abc",
            "session_id": "session-xyz",
            "msg_id": "msg-123",
            "message": long_message,
            "create_time": "2026-04-14T13:31:36",
            "task_result": None
        }
        
        import io
        import sys
        
        captured_output = io.StringIO()
        sys.stdout = captured_output
        self.client._print_task(task)
        sys.stdout = sys.__stdout__
        
        output = captured_output.getvalue()
        
        self.assertIn(long_message, output)
        self.assertNotIn("...", output)
    
    def test_print_task_missing_fields(self):
        """Test task display with missing optional fields"""
        task = {
            "task_id": "task-abc",
            "session_id": "session-xyz",
            "create_time": "2026-04-14T13:31:36"
        }
        
        import io
        import sys
        
        captured_output = io.StringIO()
        sys.stdout = captured_output
        self.client._print_task(task)
        sys.stdout = sys.__stdout__
        
        output = captured_output.getvalue()
        
        self.assertIn("msg=[N/A]", output)
        self.assertIn("Task: ", output)


class TestTaskClientErrorHandling(unittest.TestCase):
    """Test error handling (U-028 equivalent for TaskClient)"""
    
    def setUp(self):
        """Set up test fixtures"""
        from topsailai_server.agent_daemon.client import TaskClient
        self.client = TaskClient()
        self.client.get = MagicMock()
        self.client.post = MagicMock()
    
    def test_connection_error(self):
        """Test handling connection error"""
        import requests
        
        self.client.get.side_effect = requests.exceptions.ConnectionError("Connection refused")
        
        with self.assertRaises(requests.exceptions.ConnectionError) as context:
            self.client.list_tasks("session-1")
        
        self.assertIn("Connection refused", str(context.exception))
    
    def test_timeout_error(self):
        """Test handling timeout error"""
        import requests
        
        self.client.post.side_effect = requests.exceptions.Timeout("Request timed out")
        
        with self.assertRaises(requests.exceptions.Timeout) as context:
            self.client.set_task_result(
                session_id="session-1",
                processed_msg_id="msg-1",
                task_id="task-1",
                task_result="result"
            )
        
        self.assertIn("timed out", str(context.exception))


if __name__ == "__main__":
    unittest.main()
