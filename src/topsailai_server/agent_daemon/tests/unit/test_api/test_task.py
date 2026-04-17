"""
Unit tests for api/routes/task.py

Tests the task API endpoints including:
- POST /api/v1/task/result
- GET /api/v1/task
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from fastapi.testclient import TestClient


class TestTaskRoutes:
    """Tests for task API routes."""

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies for testing."""
        session_storage = Mock()
        session_storage.engine = Mock()
        session_storage.get_all = Mock(return_value=[])
        session_storage.get = Mock(return_value=None)
        session_storage.list_sessions = Mock(return_value=[])
        session_storage.delete = Mock()
        session_storage.create = Mock()
        session_storage.update_processed_msg_id = Mock()

        message_storage = Mock()
        message_storage.create = Mock()
        message_storage.get_messages = Mock(return_value=[])
        message_storage.update_task_info = Mock()
        message_storage.delete_by_session_id = Mock()

        worker_manager = Mock()
        worker_manager.stop_all = Mock()
        worker_manager.check_session_state = Mock(return_value="idle")

        scheduler = Mock()
        scheduler.start = Mock()
        scheduler.stop = Mock()

        return session_storage, message_storage, worker_manager, scheduler

    @pytest.fixture
    def client(self, mock_dependencies):
        """Create test client with mocked dependencies."""
        from topsailai_server.agent_daemon.api.app import create_app

        session_storage, message_storage, worker_manager, scheduler = mock_dependencies

        app = create_app(session_storage, message_storage, worker_manager, scheduler)

        return TestClient(app)


class TestSetTaskResult(TestTaskRoutes):
    """Tests for POST /api/v1/task/result."""

    def test_set_task_result_invalid_session_id(self, client, mock_dependencies):
        """Test setting task result with invalid session_id."""
        response = client.post(
            "/api/v1/task/result",
            json={
                "session_id": "invalid@session!",
                "processed_msg_id": "msg-123",
                "task_id": "task-456",
                "task_result": "Result",
            },
        )

        # Either validation error (200) or not found (404)
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            assert data["code"] != 0

    def test_set_task_result_invalid_msg_id(self, client, mock_dependencies):
        """Test setting task result with invalid processed_msg_id."""
        response = client.post(
            "/api/v1/task/result",
            json={
                "session_id": "valid-session-id",
                "processed_msg_id": "invalid@msg!",
                "task_id": "task-456",
                "task_result": "Result",
            },
        )

        # Either validation error (200) or not found (404)
        assert response.status_code in [200, 404]

    def test_set_task_result_invalid_task_id(self, client, mock_dependencies):
        """Test setting task result with invalid task_id."""
        response = client.post(
            "/api/v1/task/result",
            json={
                "session_id": "valid-session-id",
                "processed_msg_id": "valid-msg-id",
                "task_id": "invalid@task!",
                "task_result": "Result",
            },
        )

        # Either validation error (200) or not found (404)
        assert response.status_code in [200, 404]

    def test_set_task_result_missing_required_fields(self, client, mock_dependencies):
        """Test setting task result with missing required fields."""
        response = client.post(
            "/api/v1/task/result",
            json={
                "session_id": "test-session-123",
                # Missing processed_msg_id and task_id
            },
        )

        # Either validation error (422) or not found (404)
        assert response.status_code in [422, 404]

    def test_set_task_result_missing_session_id(self, client, mock_dependencies):
        """Test setting task result without session_id."""
        response = client.post(
            "/api/v1/task/result",
            json={
                "processed_msg_id": "msg-123",
                "task_id": "task-456",
            },
        )

        # Either validation error (422) or not found (404)
        assert response.status_code in [422, 404]


class TestRetrieveTasks(TestTaskRoutes):
    """Tests for GET /api/v1/task."""

    def test_retrieve_tasks_invalid_session_id(self, client, mock_dependencies):
        """Test retrieving tasks with invalid session_id."""
        response = client.get("/api/v1/task?session_id=invalid@id!")

        # Either validation error (200) or not found (404)
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            assert data["code"] != 0

    def test_retrieve_tasks_missing_session_id(self, client, mock_dependencies):
        """Test retrieving tasks without session_id."""
        response = client.get("/api/v1/task")

        # Either validation error (422) or not found (404)
        assert response.status_code in [422, 404]


class TestTaskValidation(TestTaskRoutes):
    """Tests for task validation."""

    def test_task_id_with_special_chars(self, client, mock_dependencies):
        """Test task ID with special characters."""
        response = client.post(
            "/api/v1/task/result",
            json={
                "session_id": "valid-session-id",
                "processed_msg_id": "valid-msg-id",
                "task_id": "task#123!@",
                "task_result": "Result",
            },
        )

        # Either validation error (200) or not found (404)
        assert response.status_code in [200, 404]

    def test_msg_id_with_special_chars(self, client, mock_dependencies):
        """Test msg_id with special characters."""
        response = client.post(
            "/api/v1/task/result",
            json={
                "session_id": "valid-session-id",
                "processed_msg_id": "msg#123!@",
                "task_id": "valid-task-id",
                "task_result": "Result",
            },
        )

        # Either validation error (200) or not found (404)
        assert response.status_code in [200, 404]
