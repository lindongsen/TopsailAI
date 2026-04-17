"""
Unit tests for api/app.py

Tests the FastAPI application factory including:
- create_app function
- Health check endpoint
- Router registration
- Lifespan context management
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime
from fastapi.testclient import TestClient


class TestCreateApp:
    """Tests for create_app function."""

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies for testing."""
        session_storage = Mock()
        session_storage.engine = Mock()
        session_storage.get_all = Mock(return_value=[])

        message_storage = Mock()

        worker_manager = Mock()
        worker_manager.stop_all = Mock()

        scheduler = Mock()
        scheduler.start = Mock()
        scheduler.stop = Mock()

        return session_storage, message_storage, worker_manager, scheduler

    def test_create_app_returns_fastapi_instance(self, mock_dependencies):
        """Test create_app returns a FastAPI instance."""
        from topsailai_server.agent_daemon.api.app import create_app

        session_storage, message_storage, worker_manager, scheduler = mock_dependencies

        app = create_app(session_storage, message_storage, worker_manager, scheduler)

        assert app is not None
        assert hasattr(app, "title")
        assert app.title == "Agent Daemon API"

    def test_create_app_with_none_scheduler(self, mock_dependencies):
        """Test create_app works without scheduler."""
        from topsailai_server.agent_daemon.api.app import create_app

        session_storage, message_storage, worker_manager, _ = mock_dependencies

        app = create_app(session_storage, message_storage, worker_manager, None)

        assert app is not None

    def test_create_app_with_none_worker_manager(self, mock_dependencies):
        """Test create_app works without worker manager."""
        from topsailai_server.agent_daemon.api.app import create_app

        session_storage, message_storage, _, scheduler = mock_dependencies

        app = create_app(session_storage, message_storage, None, scheduler)

        assert app is not None

    def test_create_app_registers_routes(self, mock_dependencies):
        """Test create_app registers all required routes."""
        from topsailai_server.agent_daemon.api.app import create_app

        session_storage, message_storage, worker_manager, scheduler = mock_dependencies

        app = create_app(session_storage, message_storage, worker_manager, scheduler)

        # Check that routes are registered
        route_paths = [r.path for r in app.routes]
        assert any("/health" in path for path in route_paths)
        assert any("/api/v1/session" in path for path in route_paths)
        assert any("/api/v1/message" in path for path in route_paths)
        assert any("/api/v1/task" in path for path in route_paths)

    def test_create_app_multiple_instances(self, mock_dependencies):
        """Test create_app can create multiple instances."""
        from topsailai_server.agent_daemon.api.app import create_app

        session_storage, message_storage, worker_manager, scheduler = mock_dependencies

        app1 = create_app(session_storage, message_storage, worker_manager, scheduler)
        app2 = create_app(session_storage, message_storage, worker_manager, scheduler)

        assert app1 is not None
        assert app2 is not None
        assert app1 is not app2


class TestHealthCheck:
    """Tests for health check endpoint."""

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies for testing."""
        session_storage = Mock()
        session_storage.engine = Mock()
        session_storage.get_all = Mock(return_value=[])

        message_storage = Mock()

        worker_manager = Mock()
        worker_manager.stop_all = Mock()

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

    def test_health_check_returns_200(self, client):
        """Test health check endpoint returns 200."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_check_response_format(self, client):
        """Test health check response has correct format."""
        response = client.get("/health")
        data = response.json()

        assert "code" in data
        assert "data" in data
        assert "message" in data

    def test_health_check_data_fields(self, client):
        """Test health check data has correct fields."""
        response = client.get("/health")
        data = response.json()

        assert data["code"] == 0
        assert "status" in data["data"]
        assert "database" in data["data"]
        assert "timestamp" in data["data"]

    def test_health_check_status_values(self, client):
        """Test health check status values are valid."""
        response = client.get("/health")
        data = response.json()

        assert data["data"]["status"] in ["healthy", "degraded"]
        assert data["data"]["database"] in ["healthy", "unhealthy"]

    def test_health_check_database_values(self, client):
        """Test health check database value is valid."""
        response = client.get("/health")
        data = response.json()

        assert data["data"]["database"] in ["healthy", "unhealthy"]

    def test_health_check_timestamp_format(self, client):
        """Test health check timestamp is valid."""
        response = client.get("/health")
        data = response.json()

        timestamp_str = data["data"]["timestamp"]
        # Should be parseable as datetime
        parsed = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        assert parsed is not None

    def test_health_check_code_zero_on_success(self, client):
        """Test health check returns code 0 on success."""
        response = client.get("/health")
        data = response.json()

        assert data["code"] == 0

    def test_health_check_message_ok(self, client):
        """Test health check returns OK message."""
        response = client.get("/health")
        data = response.json()

        assert data["message"] == "OK"


class TestHealthCheckDatabaseFailure:
    """Tests for health check with database failure."""

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies with failing database."""
        session_storage = Mock()
        session_storage.engine = Mock()
        session_storage.get_all = Mock(side_effect=Exception("DB connection failed"))

        message_storage = Mock()

        worker_manager = Mock()
        worker_manager.stop_all = Mock()

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

    def test_health_check_degraded_on_db_failure(self, client):
        """Test health check shows degraded status on database failure."""
        response = client.get("/health")
        data = response.json()

        assert data["data"]["status"] == "degraded"
        assert data["data"]["database"] == "unhealthy"

    def test_health_check_still_returns_200_on_db_failure(self, client):
        """Test health check still returns 200 even on database failure."""
        response = client.get("/health")
        assert response.status_code == 200


class TestApiUtils:
    """Tests for API utility functions."""

    def test_success_response_default(self):
        """Test success_response with default values."""
        from topsailai_server.agent_daemon.api.utils import success_response

        response = success_response()
        assert response.code == 0
        assert response.data is None
        assert response.message == "OK"

    def test_success_response_with_data(self):
        """Test success_response with custom data."""
        from topsailai_server.agent_daemon.api.utils import success_response

        data = {"key": "value"}
        response = success_response(data=data)
        assert response.code == 0
        assert response.data == data

    def test_success_response_with_message(self):
        """Test success_response with custom message."""
        from topsailai_server.agent_daemon.api.utils import success_response

        response = success_response(message="Custom message")
        assert response.message == "Custom message"

    def test_success_response_with_data_and_message(self):
        """Test success_response with both data and message."""
        from topsailai_server.agent_daemon.api.utils import success_response

        data = {"id": 1}
        response = success_response(data=data, message="Created")
        assert response.data == data
        assert response.message == "Created"

    def test_error_response_default(self):
        """Test error_response with default values."""
        from topsailai_server.agent_daemon.api.utils import error_response

        response = error_response(message="Error")
        assert response.code == -1
        assert response.message == "Error"

    def test_error_response_with_code(self):
        """Test error_response with custom code."""
        from topsailai_server.agent_daemon.api.utils import error_response

        response = error_response(message="Not found", code=404)
        assert response.code == 404

    def test_error_response_different_codes(self):
        """Test error_response with different error codes."""
        from topsailai_server.agent_daemon.api.utils import error_response

        for code in [400, 401, 403, 404, 500]:
            response = error_response(message="Error", code=code)
            assert response.code == code

    def test_api_response_model(self):
        """Test ApiResponse model."""
        from topsailai_server.agent_daemon.api.utils import ApiResponse

        response = ApiResponse(code=0, data={"key": "value"}, message="OK")
        dumped = response.model_dump()
        assert dumped["code"] == 0
        assert dumped["data"] == {"key": "value"}
        assert dumped["message"] == "OK"


class TestApiResponseFormat:
    """Tests for API response format."""

    def test_success_response_is_api_response(self):
        """Test success_response returns ApiResponse instance."""
        from topsailai_server.agent_daemon.api.utils import success_response, ApiResponse

        response = success_response(data={"key": "value"})
        assert isinstance(response, ApiResponse)

    def test_error_response_is_api_response(self):
        """Test error_response returns ApiResponse instance."""
        from topsailai_server.agent_daemon.api.utils import error_response, ApiResponse

        response = error_response(message="Error")
        assert isinstance(response, ApiResponse)

    def test_response_can_be_serialized(self):
        """Test response can be serialized to dict."""
        from topsailai_server.agent_daemon.api.utils import success_response

        response = success_response(data={"key": "value"})
        serialized = response.model_dump()
        assert isinstance(serialized, dict)
        assert serialized["code"] == 0


class TestAppConfiguration:
    """Tests for application configuration."""

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies for testing."""
        session_storage = Mock()
        session_storage.engine = Mock()
        session_storage.get_all = Mock(return_value=[])

        message_storage = Mock()

        worker_manager = Mock()
        worker_manager.stop_all = Mock()

        scheduler = Mock()
        scheduler.start = Mock()
        scheduler.stop = Mock()

        return session_storage, message_storage, worker_manager, scheduler

    def test_app_title(self, mock_dependencies):
        """Test app has correct title."""
        from topsailai_server.agent_daemon.api.app import create_app

        session_storage, message_storage, worker_manager, scheduler = mock_dependencies

        app = create_app(session_storage, message_storage, worker_manager, scheduler)

        assert app.title == "Agent Daemon API"

    def test_app_version(self, mock_dependencies):
        """Test app has correct version."""
        from topsailai_server.agent_daemon.api.app import create_app

        session_storage, message_storage, worker_manager, scheduler = mock_dependencies

        app = create_app(session_storage, message_storage, worker_manager, scheduler)

        assert app.version == "1.0.0"

    def test_app_description(self, mock_dependencies):
        """Test app has correct description."""
        from topsailai_server.agent_daemon.api.app import create_app

        session_storage, message_storage, worker_manager, scheduler = mock_dependencies

        app = create_app(session_storage, message_storage, worker_manager, scheduler)

        assert "managing sessions and messages" in app.description
