"""
Unit Tests for TaskClient Module

This module contains unit tests for the TaskClient class which provides
methods for managing tasks including setting task results and retrieving
task information.

Test Classes:
    - TestTaskClient: Tests for main TaskClient methods
    - TestTaskClientEdgeCases: Tests for edge cases and error handling

Usage:
    Run all tests:
        pytest tests/unit/test_client/test_task.py -v

    Run specific test class:
        pytest tests/unit/test_client/test_task.py::TestTaskClient -v
"""

import pytest
from unittest.mock import MagicMock, patch
from typing import Any, Dict, List

from topsailai_server.agent_daemon.client.task import TaskClient
from topsailai_server.agent_daemon.client.base import APIError


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_logger():
    """
    Mock logger fixture.

    Returns:
        MagicMock: A mock logger object.
    """
    return MagicMock()


@pytest.fixture
def task_client(mock_logger):
    """
    Create a TaskClient instance with mocked logger.

    Args:
        mock_logger: Mock logger fixture.

    Returns:
        TaskClient: A TaskClient instance with mocked logger.
    """
    with patch.object(TaskClient, '__init__', lambda self: None):
        client = TaskClient()
        client.logger = mock_logger
        client.base_url = "http://localhost:7373"
        client.timeout = 30
        client.session = MagicMock()
        return client


# =============================================================================
# Test Classes
# =============================================================================

class TestTaskClient:
    """
    Test suite for TaskClient main methods.

    Tests cover:
        - set_task_result: Setting task results
        - list_tasks: Listing tasks with various filters
        - _print_task: Task formatting output
    """

    # ==================== set_task_result Tests ====================

    @patch('builtins.print')
    def test_set_task_result_success(
        self,
        mock_print: MagicMock,
        task_client: TaskClient
    ) -> None:
        """
        Test successful task result setting.

        Verifies that:
        - API is called with correct parameters
        - Success message is printed
        - Response is returned correctly
        """
        mock_response = {
            "code": 0,
            "data": {"task_id": "task-123", "session_id": "session-456"},
            "message": "success"
        }

        with patch.object(task_client, 'post', return_value=mock_response) as mock_post:
            result = task_client.set_task_result(
                session_id="session-456",
                processed_msg_id="msg-789",
                task_id="task-123",
                task_result="Task completed successfully"
            )

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == "/api/v1/task"
            assert call_args[1]["json_data"]["session_id"] == "session-456"
            assert call_args[1]["json_data"]["task_id"] == "task-123"
            assert call_args[1]["json_data"]["task_result"] == "Task completed successfully"
            assert result["code"] == 0
            mock_print.assert_called_with("Task result set successfully")

    @patch('builtins.print')
    def test_set_task_result_verbose(
        self,
        mock_print: MagicMock,
        task_client: TaskClient
    ) -> None:
        """
        Test task result setting with verbose output.

        Verifies that when verbose=True, the full JSON response is printed.
        """
        mock_response = {
            "code": 0,
            "data": {"task_id": "task-123"},
            "message": "success"
        }

        with patch.object(task_client, 'post', return_value=mock_response) as mock_post:
            result = task_client.set_task_result(
                session_id="session-456",
                processed_msg_id="msg-789",
                task_id="task-123",
                task_result="Result",
                verbose=True
            )

            # Should print success message and JSON
            assert mock_print.call_count >= 2
            # Second print should be the JSON
            json_call = mock_print.call_args_list[1]
            assert "task-123" in str(json_call)

    def test_set_task_result_api_error(self, task_client: TaskClient) -> None:
        """
        Test task result setting with API error.

        Verifies that APIError is raised when the API returns an error.
        """
        mock_response = {
            "code": 400,
            "message": "Invalid task ID"
        }

        with patch.object(task_client, 'post', return_value=mock_response) as mock_post:
            mock_post.side_effect = APIError(400, "Invalid task ID")

            with pytest.raises(APIError) as exc_info:
                task_client.set_task_result(
                    session_id="session-456",
                    processed_msg_id="msg-789",
                    task_id="invalid",
                    task_result="Result"
                )

            assert exc_info.value.code == 400
            assert "Invalid task ID" in str(exc_info.value)

    @patch('builtins.print')
    def test_set_task_result_empty_result(
        self,
        mock_print: MagicMock,
        task_client: TaskClient
    ) -> None:
        """
        Test setting task result with empty result string.

        Verifies that empty result strings are accepted.
        """
        mock_response = {
            "code": 0,
            "data": {"task_id": "task-123"},
            "message": "success"
        }

        with patch.object(task_client, 'post', return_value=mock_response) as mock_post:
            result = task_client.set_task_result(
                session_id="session-456",
                processed_msg_id="msg-789",
                task_id="task-123",
                task_result=""
            )

            assert result["code"] == 0

    # ==================== list_tasks Tests ====================

    @patch('builtins.print')
    def test_list_tasks_success(
        self,
        mock_print: MagicMock,
        task_client: TaskClient
    ) -> None:
        """
        Test successful task listing.

        Verifies that:
        - API is called with correct parameters
        - Tasks are returned correctly
        - Count message is printed
        """
        mock_tasks = [
            {
                "task_id": "task-1",
                "session_id": "session-456",
                "msg_id": "msg-1",
                "message": "Task 1 content",
                "task_result": "Result 1",
                "create_time": "2024-01-01T10:00:00"
            },
            {
                "task_id": "task-2",
                "session_id": "session-456",
                "msg_id": "msg-2",
                "message": "Task 2 content",
                "task_result": None,
                "create_time": "2024-01-01T11:00:00"
            }
        ]

        with patch.object(task_client, 'get', return_value=mock_tasks) as mock_get:
            result = task_client.list_tasks(session_id="session-456")

            mock_get.assert_called_once()
            call_args = mock_get.call_args
            assert call_args[0][0] == "/api/v1/task"
            assert call_args[1]["params"]["session_id"] == "session-456"
            assert len(result) == 2
            assert result[0]["task_id"] == "task-1"

    @patch('builtins.print')
    def test_list_tasks_with_time_filters(
        self,
        mock_print: MagicMock,
        task_client: TaskClient
    ) -> None:
        """
        Test task listing with time range filters.

        Verifies that start_time and end_time are passed to the API.
        """
        with patch.object(task_client, 'get', return_value=[]) as mock_get:
            task_client.list_tasks(
                session_id="session-456",
                start_time="2024-01-01T00:00:00",
                end_time="2024-01-31T23:59:59"
            )

            call_args = mock_get.call_args
            params = call_args[1]["params"]
            assert params["start_time"] == "2024-01-01T00:00:00"
            assert params["end_time"] == "2024-01-31T23:59:59"

    @patch('builtins.print')
    def test_list_tasks_with_task_ids(
        self,
        mock_print: MagicMock,
        task_client: TaskClient
    ) -> None:
        """
        Test task listing with specific task IDs.

        Verifies that task_ids filter is passed to the API.
        """
        with patch.object(task_client, 'get', return_value=[]) as mock_get:
            task_client.list_tasks(
                session_id="session-456",
                task_ids=["task-1", "task-2", "task-3"]
            )

            call_args = mock_get.call_args
            params = call_args[1]["params"]
            assert params["task_ids"] == ["task-1", "task-2", "task-3"]

    @patch('builtins.print')
    def test_list_tasks_pagination(
        self,
        mock_print: MagicMock,
        task_client: TaskClient
    ) -> None:
        """
        Test task listing with pagination parameters.

        Verifies that offset and limit are passed correctly.
        """
        with patch.object(task_client, 'get', return_value=[]) as mock_get:
            task_client.list_tasks(
                session_id="session-456",
                offset=10,
                limit=50
            )

            call_args = mock_get.call_args
            params = call_args[1]["params"]
            assert params["offset"] == 10
            assert params["limit"] == 50

    @patch('builtins.print')
    def test_list_tasks_sorting(
        self,
        mock_print: MagicMock,
        task_client: TaskClient
    ) -> None:
        """
        Test task listing with sorting parameters.

        Verifies that sort_key and order_by are passed correctly.
        """
        with patch.object(task_client, 'get', return_value=[]) as mock_get:
            task_client.list_tasks(
                session_id="session-456",
                sort_key="update_time",
                order_by="asc"
            )

            call_args = mock_get.call_args
            params = call_args[1]["params"]
            assert params["sort_key"] == "update_time"
            assert params["order_by"] == "asc"

    @patch('builtins.print')
    def test_list_tasks_empty(
        self,
        mock_print: MagicMock,
        task_client: TaskClient
    ) -> None:
        """
        Test task listing with no results.

        Verifies that empty list is handled correctly.
        """
        with patch.object(task_client, 'get', return_value=[]) as mock_get:
            result = task_client.list_tasks(session_id="session-456")

            assert result == []
            # Should print "Retrieved Tasks: 0"
            assert any("0" in str(call) for call in mock_print.call_args_list)

    @patch('builtins.print')
    def test_list_tasks_verbose(
        self,
        mock_print: MagicMock,
        task_client: TaskClient
    ) -> None:
        """
        Test task listing with verbose output.

        Verifies that full JSON is printed when verbose=True.
        """
        mock_tasks = [{"task_id": "task-1", "message": "Test"}]

        with patch.object(task_client, 'get', return_value=mock_tasks) as mock_get:
            task_client.list_tasks(session_id="session-456", verbose=True)

            # Should have multiple print calls for verbose output
            assert mock_print.call_count >= 2

    def test_list_tasks_api_error(self, task_client: TaskClient) -> None:
        """
        Test task listing with API error.

        Verifies that APIError is raised on error response.
        """
        with patch.object(task_client, 'get', side_effect=APIError(500, "Internal server error")):
            with pytest.raises(APIError):
                task_client.list_tasks(session_id="session-456")

    # ==================== _print_task Tests ====================

    @patch('builtins.print')
    def test_print_task_full_data(
        self,
        mock_print: MagicMock,
        task_client: TaskClient
    ) -> None:
        """
        Test printing task with all fields populated.

        Verifies that all task information is printed correctly.
        """
        task = {
            "task_id": "task-123",
            "session_id": "session-456",
            "msg_id": "msg-789",
            "message": "Test task content",
            "task_result": "Test result content",
            "create_time": "2024-01-01T10:00:00"
        }

        task_client._print_task(task)

        # Should print split line, task info, message, separator, and result
        assert mock_print.call_count >= 4
        # Check that task_id appears in output
        output = str(mock_print.call_args_list)
        assert "task-123" in output
        assert "session-456" in output
        assert "msg-789" in output

    @patch('builtins.print')
    def test_print_task_minimal(
        self,
        mock_print: MagicMock,
        task_client: TaskClient
    ) -> None:
        """
        Test printing task with minimal fields.

        Verifies that missing fields are handled gracefully.
        """
        task = {
            "task_id": "task-123",
            "session_id": "session-456"
        }

        task_client._print_task(task)

        # Should still print without errors
        assert mock_print.call_count >= 1
        output = str(mock_print.call_args_list)
        assert "task-123" in output

    @patch('builtins.print')
    def test_print_task_no_result(
        self,
        mock_print: MagicMock,
        task_client: TaskClient
    ) -> None:
        """
        Test printing task without task_result.

        Verifies that separator and result are not printed when task_result is None.
        """
        task = {
            "task_id": "task-123",
            "session_id": "session-456",
            "msg_id": "msg-789",
            "message": "Task content",
            "task_result": None,
            "create_time": "2024-01-01T10:00:00"
        }

        task_client._print_task(task)

        # Should print task info but not separator or result
        output = str(mock_print.call_args_list)
        assert "task-123" in output
        # Should not have separator when no result
        assert "---" not in output


class TestTaskClientEdgeCases:
    """
    Test suite for TaskClient edge cases and error handling.

    Tests cover:
        - Empty inputs
        - Large values
        - Special characters
        - None values
        - Network errors
    """

    @pytest.fixture
    def mock_logger(self):
        """
        Mock logger fixture.

        Returns:
            MagicMock: A mock logger object.
        """
        return MagicMock()

    @pytest.fixture
    def task_client(self, mock_logger):
        """
        Create a TaskClient instance with mocked logger.

        Args:
            mock_logger: Mock logger fixture.

        Returns:
            TaskClient: A TaskClient instance with mocked logger.
        """
        with patch.object(TaskClient, '__init__', lambda self: None):
            client = TaskClient()
            client.logger = mock_logger
            client.base_url = "http://localhost:7373"
            client.timeout = 30
            client.session = MagicMock()
            return client

    @patch('builtins.print')
    def test_set_task_result_special_characters(
        self,
        mock_print: MagicMock,
        task_client: TaskClient
    ) -> None:
        """
        Test setting task result with special characters.

        Verifies that special characters in task_result are handled correctly.
        """
        mock_response = {"code": 0, "data": {}}

        with patch.object(task_client, 'post', return_value=mock_response) as mock_post:
            special_result = "Result with 'quotes' and \"double quotes\" and <special> chars"
            result = task_client.set_task_result(
                session_id="session-456",
                processed_msg_id="msg-789",
                task_id="task-123",
                task_result=special_result
            )

            assert result["code"] == 0
            call_args = mock_post.call_args
            assert call_args[1]["json_data"]["task_result"] == special_result

    @patch('builtins.print')
    def test_list_tasks_large_offset_limit(
        self,
        mock_print: MagicMock,
        task_client: TaskClient
    ) -> None:
        """
        Test task listing with large offset and limit values.

        Verifies that large pagination values are handled correctly.
        """
        with patch.object(task_client, 'get', return_value=[]) as mock_get:
            task_client.list_tasks(
                session_id="session-456",
                offset=10000,
                limit=5000
            )

            call_args = mock_get.call_args
            params = call_args[1]["params"]
            assert params["offset"] == 10000
            assert params["limit"] == 5000

    @patch('builtins.print')
    def test_list_tasks_many_results(
        self,
        mock_print: MagicMock,
        task_client: TaskClient
    ) -> None:
        """
        Test task listing with many results.

        Verifies that large result sets are handled correctly.
        """
        # Create 100 tasks
        mock_tasks = [
            {
                "task_id": f"task-{i}",
                "session_id": "session-456",
                "msg_id": f"msg-{i}",
                "message": f"Task {i} content",
                "create_time": f"2024-01-01T{i%24:02d}:00:00"
            }
            for i in range(100)
        ]

        with patch.object(task_client, 'get', return_value=mock_tasks) as mock_get:
            result = task_client.list_tasks(session_id="session-456")

            assert len(result) == 100

    @patch('builtins.print')
    def test_list_tasks_none_values_in_params(
        self,
        mock_print: MagicMock,
        task_client: TaskClient
    ) -> None:
        """
        Test task listing with None values in optional parameters.

        Verifies that None values are not included in API request.
        """
        with patch.object(task_client, 'get', return_value=[]) as mock_get:
            task_client.list_tasks(
                session_id="session-456",
                task_ids=None,
                start_time=None,
                end_time=None
            )

            call_args = mock_get.call_args
            params = call_args[1]["params"]
            # None values should not be in params
            assert "task_ids" not in params
            assert "start_time" not in params
            assert "end_time" not in params

    def test_set_task_result_network_error(self, task_client: TaskClient) -> None:
        """
        Test setting task result with network error.

        Verifies that network errors are handled correctly.
        """
        import requests
        with patch.object(task_client, 'post', side_effect=requests.ConnectionError("Network error")):
            with pytest.raises(requests.ConnectionError):
                task_client.set_task_result(
                    session_id="session-456",
                    processed_msg_id="msg-789",
                    task_id="task-123",
                    task_result="Result"
                )

    def test_list_tasks_network_error(self, task_client: TaskClient) -> None:
        """
        Test task listing with network error.

        Verifies that network errors are handled correctly.
        """
        import requests
        with patch.object(task_client, 'get', side_effect=requests.Timeout("Request timeout")):
            with pytest.raises(requests.Timeout):
                task_client.list_tasks(session_id="session-456")

    @patch('builtins.print')
    def test_print_task_multiline_content(
        self,
        mock_print: MagicMock,
        task_client: TaskClient
    ) -> None:
        """
        Test printing task with multiline content.

        Verifies that multiline task content is handled correctly.
        """
        task = {
            "task_id": "task-123",
            "session_id": "session-456",
            "msg_id": "msg-789",
            "message": "Line 1\nLine 2\nLine 3",
            "task_result": "Result Line 1\nResult Line 2",
            "create_time": "2024-01-01T10:00:00"
        }

        task_client._print_task(task)

        # Should print without errors
        assert mock_print.call_count >= 4
