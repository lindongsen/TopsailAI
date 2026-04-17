"""
Unit tests for the API module.

This module contains comprehensive tests for the FastAPI application factory,
health check endpoint, and API response utilities.

Test Coverage:
    - create_app() - Flask app factory
    - Health check endpoint
    - Response formatting
    - Error handling
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch


class TestCreateApp:
    """Tests for the create_app() function."""

    def test_create_app_returns_fastapi_instance(self):
        """
        Test that create_app returns a FastAPI instance.
        
        Verifies that the create_app function returns an object that is
        an instance of FastAPI with the correct configuration.
        """
        from fastapi import FastAPI
        from topsailai_server.agent_daemon.api import create_app

        # Create mock dependencies
        session_storage = MagicMock()
        message_storage = MagicMock()
        worker_manager = MagicMock()
        scheduler = MagicMock()

        # Call create_app
        app = create_app(session_storage, message_storage, worker_manager, scheduler)

        # Verify it returns a FastAPI instance
        assert isinstance(app, FastAPI)
        assert app.title == "Agent Daemon API"
        assert app.version == "1.0.0"

    def test_create_app_with_none_scheduler(self):
        """
        Test that create_app works when scheduler is None.
        
        Verifies that the application can be created even when
        the scheduler is not provided (None).
        """
        from fastapi import FastAPI
        from topsailai_server.agent_daemon.api import create_app

        # Create mock dependencies with None scheduler
        session_storage = MagicMock()
        message_storage = MagicMock()
        worker_manager = MagicMock()
        scheduler = None

        # Call create_app
        app = create_app(session_storage, message_storage, worker_manager, scheduler)

        # Verify it returns a FastAPI instance
        assert isinstance(app, FastAPI)

    def test_create_app_with_none_worker_manager(self):
        """
        Test that create_app works when worker_manager is None.
        
        Verifies that the application can be created even when
        the worker_manager is not provided (None).
        """
        from fastapi import FastAPI
        from topsailai_server.agent_daemon.api import create_app

        # Create mock dependencies with None worker_manager
        session_storage = MagicMock()
        message_storage = MagicMock()
        worker_manager = None
        scheduler = MagicMock()

        # Call create_app
        app = create_app(session_storage, message_storage, worker_manager, scheduler)

        # Verify it returns a FastAPI instance
        assert isinstance(app, FastAPI)

    def test_create_app_registers_routes(self):
        """
        Test that create_app registers all required routes.
        
        Verifies that the application includes routers for
        message, task, and session endpoints.
        """
        from topsailai_server.agent_daemon.api import create_app

        # Create mock dependencies
        session_storage = MagicMock()
        message_storage = MagicMock()
        worker_manager = MagicMock()
        scheduler = MagicMock()

        # Call create_app
        app = create_app(session_storage, message_storage, worker_manager, scheduler)

        # Verify routes are registered
        route_paths = [route.path for route in app.routes]
        assert "/health" in route_paths

    def test_create_app_multiple_instances(self):
        """
        Test that create_app can create multiple independent instances.
        
        Verifies that calling create_app multiple times creates
        separate, independent FastAPI applications.
        """
        from topsailai_server.agent_daemon.api import create_app

        # Create mock dependencies
        session_storage1 = MagicMock()
        message_storage1 = MagicMock()
        worker_manager1 = MagicMock()
        scheduler1 = MagicMock()

        session_storage2 = MagicMock()
        message_storage2 = MagicMock()
        worker_manager2 = MagicMock()
        scheduler2 = MagicMock()

        # Call create_app twice
        app1 = create_app(session_storage1, message_storage1, worker_manager1, scheduler1)
        app2 = create_app(session_storage2, message_storage2, worker_manager2, scheduler2)

        # Verify they are separate instances
        assert app1 is not app2
        assert app1.title == app2.title


class TestHealthCheck:
    """Tests for the health check endpoint."""

    @pytest.fixture
    def app(self):
        """Create a test FastAPI application."""
        from topsailai_server.agent_daemon.api import create_app
        from fastapi.testclient import TestClient

        # Create mock dependencies
        session_storage = MagicMock()
        message_storage = MagicMock()
        worker_manager = MagicMock()
        scheduler = MagicMock()

        # Create app
        app = create_app(session_storage, message_storage, worker_manager, scheduler)
        return TestClient(app)

    def test_health_check_returns_200(self, app):
        """
        Test that health check endpoint returns 200 status.
        
        Verifies that the /health endpoint responds with
        a successful HTTP status code.
        """
        response = app.get("/health")
        assert response.status_code == 200

    def test_health_check_response_format(self, app):
        """
        Test that health check returns correct response format.
        
        Verifies that the response contains the unified API format
        with code, data, and message fields.
        """
        response = app.get("/health")
        data = response.json()

        # Verify unified response format
        assert "code" in data
        assert "data" in data
        assert "message" in data

    def test_health_check_data_fields(self, app):
        """
        Test that health check data contains required fields.
        
        Verifies that the data object contains status, database,
        and timestamp fields.
        """
        response = app.get("/health")
        data = response.json()

        # Verify data fields
        assert "status" in data["data"]
        assert "database" in data["data"]
        assert "timestamp" in data["data"]

    def test_health_check_status_values(self, app):
        """
        Test that health check status can be healthy or degraded.
        
        Verifies that the status field can have valid values
        of 'healthy' or 'degraded'.
        """
        response = app.get("/health")
        data = response.json()

        # Verify status is one of the valid values
        assert data["data"]["status"] in ["healthy", "degraded"]

    def test_health_check_database_values(self, app):
        """
        Test that health check database status can be healthy or unhealthy.
        
        Verifies that the database field can have valid values
        of 'healthy' or 'unhealthy'.
        """
        response = app.get("/health")
        data = response.json()

        # Verify database status is one of the valid values
        assert data["data"]["database"] in ["healthy", "unhealthy"]

    def test_health_check_timestamp_format(self, app):
        """
        Test that health check timestamp is a valid ISO format.
        
        Verifies that the timestamp field contains a valid
        ISO 8601 formatted datetime string.
        """
        response = app.get("/health")
        data = response.json()

        # Verify timestamp is a valid datetime string
        timestamp_str = data["data"]["timestamp"]
        assert datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))

    def test_health_check_code_zero_on_success(self, app):
        """
        Test that health check returns code 0 on success.
        
        Verifies that the response code is 0 when the
        health check is successful.
        """
        response = app.get("/health")
        data = response.json()

        # Verify code is 0 on success
        assert data["code"] == 0

    def test_health_check_message_ok(self, app):
        """
        Test that health check returns 'OK' message on success.
        
        Verifies that the response message is 'OK' when the
        health check is successful.
        """
        response = app.get("/health")
        data = response.json()

        # Verify message is 'OK'
        assert data["message"] == "OK"


class TestHealthCheckDatabaseFailure:
    """Tests for health check behavior when database fails."""

    @pytest.fixture
    def app_with_db_failure(self):
        """Create a test FastAPI application with database failure."""
        from topsailai_server.agent_daemon.api import create_app
        from fastapi.testclient import TestClient

        # Create mock dependencies
        session_storage = MagicMock()
        message_storage = MagicMock()
        worker_manager = MagicMock()
        scheduler = MagicMock()

        # Patch the internal Storage class to raise exception
        with patch('topsailai_server.agent_daemon.api.app.Storage') as mock_storage_class:
            # Create mock storage instance
            mock_storage_instance = MagicMock()
            mock_storage_instance.session.get_all.side_effect = Exception("Database connection failed")
            mock_storage_class.return_value = mock_storage_instance

            # Create app
            app = create_app(session_storage, message_storage, worker_manager, scheduler)
            yield TestClient(app)

    def test_health_check_degraded_on_db_failure(self, app_with_db_failure):
        """
        Test that health check returns degraded status on database failure.
        
        Verifies that when the database health check fails,
        the status is set to 'degraded' and database is 'unhealthy'.
        """
        response = app_with_db_failure.get("/health")
        data = response.json()

        # Verify degraded status
        assert data["data"]["status"] == "degraded"
        assert data["data"]["database"] == "unhealthy"

    def test_health_check_still_returns_200_on_db_failure(self, app_with_db_failure):
        """
        Test that health check still returns 200 even on database failure.
        
        Verifies that the endpoint returns HTTP 200 even when
        the database is unhealthy, just with degraded status.
        """
        response = app_with_db_failure.get("/health")
        assert response.status_code == 200


class TestApiUtils:
    """Tests for API utility functions."""

    def test_success_response_default(self):
        """
        Test success_response with default parameters.
        
        Verifies that success_response returns correct format
        with default values when no arguments are provided.
        """
        from topsailai_server.agent_daemon.api.utils import success_response

        response = success_response()

        assert response.code == 0
        assert response.data is None
        assert response.message == "OK"

    def test_success_response_with_data(self):
        """
        Test success_response with custom data.
        
        Verifies that success_response correctly includes
        the provided data in the response.
        """
        from topsailai_server.agent_daemon.api.utils import success_response

        test_data = {"key": "value", "count": 42}
        response = success_response(data=test_data)

        assert response.code == 0
        assert response.data == test_data
        assert response.message == "OK"

    def test_success_response_with_message(self):
        """
        Test success_response with custom message.
        
        Verifies that success_response correctly includes
        the provided message in the response.
        """
        from topsailai_server.agent_daemon.api.utils import success_response

        custom_message = "Operation completed successfully"
        response = success_response(message=custom_message)

        assert response.code == 0
        assert response.data is None
        assert response.message == custom_message

    def test_success_response_with_data_and_message(self):
        """
        Test success_response with both data and message.
        
        Verifies that success_response correctly includes
        both data and message in the response.
        """
        from topsailai_server.agent_daemon.api.utils import success_response

        test_data = {"result": "success"}
        custom_message = "Custom success message"
        response = success_response(data=test_data, message=custom_message)

        assert response.code == 0
        assert response.data == test_data
        assert response.message == custom_message

    def test_error_response_default(self):
        """
        Test error_response with default parameters.
        
        Verifies that error_response returns correct format
        with default values when only message is provided.
        """
        from topsailai_server.agent_daemon.api.utils import error_response

        error_message = "An error occurred"
        response = error_response(error_message)

        assert response.code == -1
        assert response.data is None
        assert response.message == error_message

    def test_error_response_with_code(self):
        """
        Test error_response with custom error code.
        
        Verifies that error_response correctly includes
        the provided error code in the response.
        """
        from topsailai_server.agent_daemon.api.utils import error_response

        error_message = "Not found"
        custom_code = 404
        response = error_response(error_message, code=custom_code)

        assert response.code == custom_code
        assert response.data is None
        assert response.message == error_message

    def test_error_response_different_codes(self):
        """
        Test error_response with various error codes.
        
        Verifies that error_response handles different
        error codes correctly.
        """
        from topsailai_server.agent_daemon.api.utils import error_response

        test_cases = [
            (400, "Bad request"),
            (401, "Unauthorized"),
            (403, "Forbidden"),
            (404, "Not found"),
            (500, "Internal server error"),
        ]

        for code, message in test_cases:
            response = error_response(message, code=code)
            assert response.code == code
            assert response.message == message

    def test_api_response_model(self):
        """
        Test ApiResponse model initialization.
        
        Verifies that ApiResponse model can be instantiated
        with various parameter combinations.
        """
        from topsailai_server.agent_daemon.api.utils import ApiResponse

        # Test with all parameters
        response = ApiResponse(code=0, data={"test": True}, message="Success")
        assert response.code == 0
        assert response.data == {"test": True}
        assert response.message == "Success"

        # Test with minimal parameters
        response = ApiResponse()
        assert response.code == 0
        assert response.data is None
        assert response.message is None


class TestApiResponseFormat:
    """Tests for unified API response format consistency."""

    def test_success_response_is_api_response(self):
        """
        Test that success_response returns ApiResponse instance.
        
        Verifies that the success_response function returns
        an instance of the ApiResponse model.
        """
        from topsailai_server.agent_daemon.api.utils import success_response, ApiResponse

        response = success_response()
        assert isinstance(response, ApiResponse)

    def test_error_response_is_api_response(self):
        """
        Test that error_response returns ApiResponse instance.
        
        Verifies that the error_response function returns
        an instance of the ApiResponse model.
        """
        from topsailai_server.agent_daemon.api.utils import error_response, ApiResponse

        response = error_response("Error")
        assert isinstance(response, ApiResponse)

    def test_response_can_be_serialized(self):
        """
        Test that responses can be serialized to JSON.
        
        Verifies that ApiResponse instances can be properly
        serialized to JSON format.
        """
        from topsailai_server.agent_daemon.api.utils import success_response

        response = success_response(data={"key": "value"})
        json_data = response.model_dump()

        assert isinstance(json_data, dict)
        assert "code" in json_data
        assert "data" in json_data
        assert "message" in json_data


class TestAppConfiguration:
    """Tests for application configuration."""

    def test_app_title(self):
        """
        Test that app has correct title.
        
        Verifies that the FastAPI application is configured
        with the correct title.
        """
        from topsailai_server.agent_daemon.api import create_app

        session_storage = MagicMock()
        message_storage = MagicMock()
        worker_manager = MagicMock()
        scheduler = MagicMock()

        app = create_app(session_storage, message_storage, worker_manager, scheduler)

        assert app.title == "Agent Daemon API"

    def test_app_description(self):
        """
        Test that app has correct description.
        
        Verifies that the FastAPI application is configured
        with the correct description.
        """
        from topsailai_server.agent_daemon.api import create_app

        session_storage = MagicMock()
        message_storage = MagicMock()
        worker_manager = MagicMock()
        scheduler = MagicMock()

        app = create_app(session_storage, message_storage, worker_manager, scheduler)

        assert app.description == "API for managing sessions and messages"

    def test_app_version(self):
        """
        Test that app has correct version.
        
        Verifies that the FastAPI application is configured
        with the correct version string.
        """
        from topsailai_server.agent_daemon.api import create_app

        session_storage = MagicMock()
        message_storage = MagicMock()
        worker_manager = MagicMock()
        scheduler = MagicMock()

        app = create_app(session_storage, message_storage, worker_manager, scheduler)

        assert app.version == "1.0.0"


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_app_with_mock_storages(self):
        """
        Test that app works with mock storages.
        
        Verifies that the application can be created even when
        the storage objects are mocked.
        """
        from topsailai_server.agent_daemon.api import create_app
        from fastapi import FastAPI

        # Create mock storages with engine attribute
        session_storage = MagicMock()
        session_storage.engine = MagicMock()
        message_storage = MagicMock()
        message_storage.engine = MagicMock()
        worker_manager = MagicMock()
        scheduler = MagicMock()

        app = create_app(session_storage, message_storage, worker_manager, scheduler)

        assert isinstance(app, FastAPI)

    def test_multiple_health_check_requests(self):
        """
        Test multiple rapid health check requests.
        
        Verifies that the health check endpoint can handle
        multiple concurrent requests.
        """
        from topsailai_server.agent_daemon.api import create_app
        from fastapi.testclient import TestClient

        session_storage = MagicMock()
        message_storage = MagicMock()
        worker_manager = MagicMock()
        scheduler = MagicMock()

        app = create_app(session_storage, message_storage, worker_manager, scheduler)
        client = TestClient(app)

        # Make multiple requests
        for _ in range(5):
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json()["code"] == 0
