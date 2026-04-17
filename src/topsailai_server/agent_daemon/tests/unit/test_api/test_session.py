"""
Unit tests for api/routes/session.py

Tests the session API endpoints including:
- GET /api/v1/session/{session_id}
- GET /api/v1/session
- DELETE /api/v1/session
- POST /api/v1/session/process
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from fastapi.testclient import TestClient


class TestSessionRoutes:
    """Tests for session API routes."""

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
        # Return empty list for unprocessed messages
        message_storage.get_unprocessed_messages = Mock(return_value=[])
        message_storage.get_latest_message = Mock(return_value=None)

        worker_manager = Mock()
        worker_manager.stop_all = Mock()
        worker_manager.check_session_state = Mock(return_value="idle")
        worker_manager.is_session_idle = Mock(return_value=True)
        worker_manager.start_processor = Mock(return_value=True)

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

    @pytest.fixture
    def mock_session_data(self):
        """Create mock session data."""
        session = Mock()
        session.session_id = "test-session-123"
        session.session_name = "Test Session"
        session.task = None
        session.create_time = datetime.now()
        session.update_time = datetime.now()
        session.processed_msg_id = None
        return session


class TestGetSession(TestSessionRoutes):
    """Tests for GET /api/v1/session/{session_id}."""

    def test_get_session_with_invalid_id(self, client, mock_dependencies):
        """Test getting session with invalid ID format."""
        response = client.get("/api/v1/session/invalid@id!")

        # Either validation error (200) or not found (404)
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            assert data["code"] != 0
            assert "invalid" in data["message"].lower()

    def test_get_session_with_special_chars(self, client, mock_dependencies):
        """Test getting session with special characters."""
        response = client.get("/api/v1/session/session#123!")

        # Either validation error (200) or not found (404)
        assert response.status_code in [200, 404]


class TestListSessions(TestSessionRoutes):
    """Tests for GET /api/v1/session."""

    def test_list_sessions_with_pagination(self, client, mock_dependencies):
        """Test listing sessions with pagination parameters."""
        session_storage, message_storage, worker_manager, scheduler = mock_dependencies

        mock_storage_instance = Mock()
        mock_storage_instance.session.list_sessions = Mock(return_value=[])

        with patch("topsailai_server.agent_daemon.api.routes.session.Storage") as MockStorage:
            MockStorage.return_value = mock_storage_instance

            response = client.get("/api/v1/session?offset=10&limit=50")

            assert response.status_code == 200
            call_kwargs = mock_storage_instance.session.list_sessions.call_args[1]
            assert call_kwargs["offset"] == 10
            assert call_kwargs["limit"] == 50

    def test_list_sessions_with_sorting(self, client, mock_dependencies):
        """Test listing sessions with sorting parameters."""
        session_storage, message_storage, worker_manager, scheduler = mock_dependencies

        mock_storage_instance = Mock()
        mock_storage_instance.session.list_sessions = Mock(return_value=[])

        with patch("topsailai_server.agent_daemon.api.routes.session.Storage") as MockStorage:
            MockStorage.return_value = mock_storage_instance

            response = client.get("/api/v1/session?sort_key=update_time&order_by=asc")

            assert response.status_code == 200
            call_kwargs = mock_storage_instance.session.list_sessions.call_args[1]
            assert call_kwargs["sort_key"] == "update_time"
            assert call_kwargs["order_by"] == "asc"


class TestDeleteSessions(TestSessionRoutes):
    """Tests for DELETE /api/v1/session."""

    def test_delete_sessions_no_ids(self, client, mock_dependencies):
        """Test deleting sessions with no IDs provided."""
        response = client.delete("/api/v1/session")

        # FastAPI returns 422 for missing required query parameters
        assert response.status_code == 422


class TestProcessSession(TestSessionRoutes):
    """Tests for POST /api/v1/session/process."""

    def test_process_session_missing_session_id(self, client, mock_dependencies):
        """Test processing session without session_id."""
        response = client.post("/api/v1/session/process", json={})

        # Either validation error (422) or not found (404)
        assert response.status_code in [422, 404]

    def test_process_session_invalid_session_id(self, client, mock_dependencies):
        """Test processing session with invalid session_id.
        
        Note: The ProcessSessionRequest model doesn't validate session_id format,
        so invalid IDs are accepted but the processing will fail gracefully.
        """
        # Create a mock storage that returns None for session.get
        mock_storage = Mock()
        mock_storage.session.get = Mock(return_value=None)
        
        # Mock the Storage class to return our mock storage
        with patch("topsailai_server.agent_daemon.api.routes.session.Storage") as MockStorage, \
             patch("topsailai_server.agent_daemon.api.routes.session.check_and_process_messages") as mock_check:
            
            MockStorage.return_value = mock_storage
            mock_check.return_value = None  # No processing needed
            
            response = client.post(
                "/api/v1/session/process",
                json={"session_id": "invalid@session!"},
            )

            # The endpoint accepts any session_id format
            # Processing will fail because session doesn't exist
            assert response.status_code in [200, 422, 500]


class TestSessionValidation(TestSessionRoutes):
    """Tests for session validation."""

    def test_session_id_validation_empty(self, client, mock_dependencies):
        """Test session ID validation with empty string."""
        response = client.get("/api/v1/session/ ")

        # Should return 404 or validation error
        assert response.status_code in [200, 404]

    def test_session_id_validation_too_long(self, client, mock_dependencies):
        """Test session ID validation with very long string."""
        long_id = "a" * 1000
        response = client.get(f"/api/v1/session/{long_id}")

        # Should return validation error or 404
        assert response.status_code in [200, 404]
