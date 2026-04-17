"""
Unit tests for api/routes/message.py

Tests the message API endpoints including:
- POST /api/v1/message
- GET /api/v1/message
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from fastapi.testclient import TestClient


class TestMessageRoutes:
    """Tests for message API routes."""

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


class TestReceiveMessage(TestMessageRoutes):
    """Tests for POST /api/v1/message."""

    def test_receive_message_invalid_session_id(self, client, mock_dependencies):
        """Test receiving a message with invalid session_id."""
        response = client.post(
            "/api/v1/message",
            json={
                "message": "Hello",
                "session_id": "invalid@session!",
                "role": "user",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] != 0
        assert "invalid" in data["message"].lower()

    def test_receive_message_invalid_role(self, client, mock_dependencies):
        """Test receiving a message with invalid role."""
        response = client.post(
            "/api/v1/message",
            json={
                "message": "Hello",
                "session_id": "valid-session-id",
                "role": "invalid_role",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] != 0

    def test_receive_message_empty_content(self, client, mock_dependencies):
        """Test receiving a message with empty content."""
        response = client.post(
            "/api/v1/message",
            json={
                "message": "",
                "session_id": "valid-session-id",
                "role": "user",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] != 0

    def test_receive_message_missing_session_id(self, client, mock_dependencies):
        """Test receiving a message without session_id."""
        response = client.post(
            "/api/v1/message",
            json={
                "message": "Hello",
                "role": "user",
            },
        )

        assert response.status_code == 422  # Validation error

    def test_receive_message_missing_message(self, client, mock_dependencies):
        """Test receiving a message without message content."""
        response = client.post(
            "/api/v1/message",
            json={
                "session_id": "valid-session-id",
                "role": "user",
            },
        )

        assert response.status_code == 422  # Validation error


class TestRetrieveMessages(TestMessageRoutes):
    """Tests for GET /api/v1/message."""

    def test_retrieve_messages_invalid_session_id(self, client, mock_dependencies):
        """Test retrieving messages with invalid session_id."""
        response = client.get("/api/v1/message?session_id=invalid@id!")

        assert response.status_code == 200
        data = response.json()
        assert data["code"] != 0

    def test_retrieve_messages_missing_session_id(self, client, mock_dependencies):
        """Test retrieving messages without session_id."""
        response = client.get("/api/v1/message")

        assert response.status_code == 422  # Validation error


class TestMessageValidation(TestMessageRoutes):
    """Tests for message validation."""

    def test_message_content_validation_whitespace(self, client, mock_dependencies):
        """Test message content validation with whitespace only."""
        response = client.post(
            "/api/v1/message",
            json={
                "message": "   ",
                "session_id": "valid-session-id",
                "role": "user",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] != 0

    def test_role_validation_case_sensitive(self, client, mock_dependencies):
        """Test role validation is case sensitive."""
        response = client.post(
            "/api/v1/message",
            json={
                "message": "Hello",
                "session_id": "valid-session-id",
                "role": "USER",  # uppercase should be invalid
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] != 0

    def test_session_id_with_special_chars(self, client, mock_dependencies):
        """Test session ID with special characters."""
        response = client.post(
            "/api/v1/message",
            json={
                "message": "Hello",
                "session_id": "session#123!@#",
                "role": "user",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] != 0
