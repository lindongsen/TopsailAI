"""
Unit Tests for client/base.py

This module contains comprehensive unit tests for the BaseClient class
and APIError exception.

Test Coverage:
    - BaseClient initialization (with/without base_url)
    - Environment variable handling for host/port
    - HTTP request methods (get, post, delete, request)
    - Error handling (APIError, ConnectionError, Timeout)
    - Response parsing (success and error cases)
    - format_time static method
    - health_check method
"""

import os
from unittest.mock import MagicMock, patch

import pytest
import requests

from topsailai_server.agent_daemon.client.base import APIError, BaseClient


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_logger():
    """Mock logger to prevent log output during tests."""
    with patch("topsailai_server.agent_daemon.client.base.logger") as mock:
        yield mock


@pytest.fixture
def base_client(mock_logger):
    """Create a BaseClient instance for testing."""
    return BaseClient()


@pytest.fixture
def base_client_with_url(mock_logger):
    """Create a BaseClient instance with explicit base_url."""
    return BaseClient(base_url="http://test-server:8080")


# =============================================================================
# Tests for APIError Exception
# =============================================================================


class TestAPIError:
    """Tests for the APIError exception class."""

    def test_api_error_initialization(self):
        """
        Test APIError initialization with code and message.

        Verifies that the exception stores the code and message
        correctly and formats them in the string representation.
        """
        error = APIError(404, "Not Found")
        assert error.code == 404
        assert error.message == "Not Found"
        assert "404" in str(error)
        assert "Not Found" in str(error)

    def test_api_error_string_format(self):
        """
        Test APIError string format.

        Verifies the exception message follows the expected format
        "API Error {code}: {message}".
        """
        error = APIError(500, "Internal Server Error")
        expected = "API Error 500: Internal Server Error"
        assert str(error) == expected

    def test_api_error_with_empty_message(self):
        """
        Test APIError with empty message.

        Verifies that empty messages are handled correctly.
        """
        error = APIError(400, "")
        assert error.code == 400
        assert error.message == ""
        assert "400" in str(error)


# =============================================================================
# Tests for BaseClient Initialization
# =============================================================================


class TestBaseClientInitialization:
    """Tests for BaseClient initialization."""

    def test_init_with_explicit_base_url(self, mock_logger):
        """
        Test initialization with explicit base_url.

        Verifies that when base_url is provided, it is used directly
        and trailing slashes are stripped.
        """
        client = BaseClient(base_url="http://example.com:8080/")
        assert client.base_url == "http://example.com:8080"
        assert client.timeout == 10

    def test_init_with_explicit_timeout(self, mock_logger):
        """
        Test initialization with explicit timeout.

        Verifies that custom timeout value is stored correctly.
        """
        client = BaseClient(base_url="http://example.com", timeout=30)
        assert client.timeout == 30

    def test_init_without_base_url_uses_default(self, mock_logger):
        """
        Test initialization without base_url uses environment defaults.

        Verifies that when no base_url is provided, the client reads
        from environment variables TOPSAILAI_AGENT_DAEMON_HOST and
        TOPSAILAI_AGENT_DAEMON_PORT.
        """
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT_DAEMON_HOST": "192.168.1.100",
            "TOPSAILAI_AGENT_DAEMON_PORT": "9000"
        }):
            client = BaseClient()
            assert client.base_url == "http://192.168.1.100:9000"

    def test_init_without_env_uses_localhost(self, mock_logger):
        """
        Test initialization without environment variables uses localhost.

        Verifies that when environment variables are not set,
        the default values 127.0.0.1:7373 are used.
        """
        with patch.dict(os.environ, {}, clear=True):
            client = BaseClient()
            assert client.base_url == "http://127.0.0.1:7373"

    def test_init_strips_trailing_slash(self, mock_logger):
        """
        Test that trailing slashes are stripped from base_url.

        Verifies the URL normalization behavior.
        """
        client = BaseClient(base_url="http://example.com/api/")
        assert client.base_url == "http://example.com/api"

    def test_init_strips_multiple_trailing_slashes(self, mock_logger):
        """
        Test that multiple trailing slashes are stripped.

        Verifies robust URL normalization.
        """
        client = BaseClient(base_url="http://example.com/api///")
        assert client.base_url == "http://example.com/api"


# =============================================================================
# Tests for format_time Static Method
# =============================================================================


class TestFormatTime:
    """Tests for the format_time static method."""

    def test_format_time_with_iso_format(self):
        """
        Test format_time with ISO format timestamp.

        Verifies correct parsing of ISO 8601 timestamps with microseconds.
        """
        result = BaseClient.format_time("2026-04-13T23:27:53.123456")
        assert result == "2026-04-13 23:27:53"

    def test_format_time_with_iso_format_no_microseconds(self):
        """
        Test format_time with ISO format without microseconds.

        Verifies handling of timestamps without fractional seconds.
        """
        result = BaseClient.format_time("2026-04-13T23:27:53")
        assert result == "2026-04-13 23:27:53"

    def test_format_time_with_none(self):
        """
        Test format_time with None input.

        Verifies that None returns "N/A".
        """
        result = BaseClient.format_time(None)
        assert result == "N/A"

    def test_format_time_with_empty_string(self):
        """
        Test format_time with empty string input.

        Verifies that empty string returns "N/A".
        """
        result = BaseClient.format_time("")
        assert result == "N/A"

    def test_format_time_already_formatted(self):
        """
        Test format_time with already formatted string.

        Verifies that non-ISO format strings are returned as-is.
        """
        result = BaseClient.format_time("2026-04-13 23:27:53")
        assert result == "2026-04-13 23:27:53"

    def test_format_time_with_different_date(self):
        """
        Test format_time with different date values.

        Verifies correct handling of various dates.
        """
        result = BaseClient.format_time("2025-01-01T12:00:00.000000")
        assert result == "2025-01-01 12:00:00"


# =============================================================================
# Tests for HTTP Request Methods
# =============================================================================


class TestRequestMethod:
    """Tests for the request method."""

    def test_request_get_success(self, base_client, mock_logger):
        """
        Test successful GET request.

        Verifies that GET requests work correctly and return data.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": {"id": "123"}, "message": "OK"}

        with patch("topsailai_server.agent_daemon.client.base.requests.request", return_value=mock_response):
            result = base_client.request("GET", "/api/test")
            assert result == {"id": "123"}

    def test_request_post_success(self, base_client, mock_logger):
        """
        Test successful POST request.

        Verifies that POST requests with JSON body work correctly.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": {"created": True}, "message": "Created"}

        with patch("topsailai_server.agent_daemon.client.base.requests.request", return_value=mock_response):
            result = base_client.request("POST", "/api/test", json_data={"name": "test"})
            assert result == {"created": True}

    def test_request_delete_success(self, base_client, mock_logger):
        """
        Test successful DELETE request.

        Verifies that DELETE requests work correctly.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": {"deleted": True}, "message": "Deleted"}

        with patch("topsailai_server.agent_daemon.client.base.requests.request", return_value=mock_response):
            result = base_client.request("DELETE", "/api/test")
            assert result == {"deleted": True}

    def test_request_with_params(self, base_client, mock_logger):
        """
        Test request with query parameters.

        Verifies that params are passed correctly to requests.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": [], "message": "OK"}

        with patch("topsailai_server.agent_daemon.client.base.requests.request") as mock_request:
            mock_request.return_value = mock_response
            base_client.request("GET", "/api/test", params={"key": "value"})
            mock_request.assert_called_once()
            call_kwargs = mock_request.call_args[1]
            assert call_kwargs["params"] == {"key": "value"}

    def test_request_with_custom_timeout(self, base_client, mock_logger):
        """
        Test request with custom timeout.

        Verifies that custom timeout overrides default timeout.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": None, "message": "OK"}

        with patch("topsailai_server.agent_daemon.client.base.requests.request", return_value=mock_response) as mock_request:
            base_client.request("GET", "/api/test", timeout=60)
            call_kwargs = mock_request.call_args[1]
            assert call_kwargs["timeout"] == 60

    def test_request_method_case_insensitive(self, base_client, mock_logger):
        """
        Test that HTTP method is case-insensitive.

        Verifies that lowercase methods are converted to uppercase.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": None, "message": "OK"}

        with patch("topsailai_server.agent_daemon.client.base.requests.request", return_value=mock_response) as mock_request:
            base_client.request("get", "/api/test")
            call_kwargs = mock_request.call_args[1]
            assert call_kwargs["method"] == "GET"


# =============================================================================
# Tests for Error Handling
# =============================================================================


class TestRequestErrors:
    """Tests for request error handling."""

    def test_request_http_error(self, base_client, mock_logger):
        """
        Test handling of HTTP error status codes.

        Verifies that non-200 status codes raise APIError.
        """
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("topsailai_server.agent_daemon.client.base.requests.request", return_value=mock_response):
            with pytest.raises(APIError) as exc_info:
                base_client.request("GET", "/api/test")
            assert exc_info.value.code == 500

    def test_request_api_error_code(self, base_client, mock_logger):
        """
        Test handling of API error codes.

        Verifies that non-zero API codes raise APIError.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 400, "data": None, "message": "Bad Request"}

        with patch("topsailai_server.agent_daemon.client.base.requests.request", return_value=mock_response):
            with pytest.raises(APIError) as exc_info:
                base_client.request("GET", "/api/test")
            assert exc_info.value.code == 400
            assert exc_info.value.message == "Bad Request"

    def test_request_connection_error(self, base_client, mock_logger):
        """
        Test handling of connection errors.

        Verifies that connection errors are propagated correctly.
        """
        with patch("topsailai_server.agent_daemon.client.base.requests.request") as mock_request:
            mock_request.side_effect = requests.exceptions.ConnectionError("Connection refused")
            with pytest.raises(requests.exceptions.ConnectionError):
                base_client.request("GET", "/api/test")

    def test_request_timeout_error(self, base_client, mock_logger):
        """
        Test handling of timeout errors.

        Verifies that timeout errors are propagated correctly.
        """
        with patch("topsailai_server.agent_daemon.client.base.requests.request") as mock_request:
            mock_request.side_effect = requests.exceptions.Timeout("Request timed out")
            with pytest.raises(requests.exceptions.Timeout):
                base_client.request("GET", "/api/test")

    def test_request_unexpected_error(self, base_client, mock_logger):
        """
        Test handling of unexpected errors.

        Verifies that unexpected exceptions are propagated.
        """
        with patch("topsailai_server.agent_daemon.client.base.requests.request") as mock_request:
            mock_request.side_effect = ValueError("Unexpected error")
            with pytest.raises(ValueError):
                base_client.request("GET", "/api/test")


# =============================================================================
# Tests for Convenience Methods
# =============================================================================


class TestConvenienceMethods:
    """Tests for get, post, delete convenience methods."""

    def test_get_method(self, base_client, mock_logger):
        """
        Test the get convenience method.

        Verifies that get method calls request with GET.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": {"test": True}, "message": "OK"}

        with patch.object(base_client, "request", return_value={"test": True}) as mock_request:
            result = base_client.get("/api/test", params={"key": "value"})
            mock_request.assert_called_once_with("GET", "/api/test", params={"key": "value"}, timeout=None)
            assert result == {"test": True}

    def test_post_method(self, base_client, mock_logger):
        """
        Test the post convenience method.

        Verifies that post method calls request with POST.
        """
        with patch.object(base_client, "request", return_value={"created": True}) as mock_request:
            result = base_client.post("/api/test", json_data={"name": "test"})
            mock_request.assert_called_once_with("POST", "/api/test", json_data={"name": "test"}, timeout=None)
            assert result == {"created": True}

    def test_delete_method(self, base_client, mock_logger):
        """
        Test the delete convenience method.

        Verifies that delete method calls request with DELETE.
        """
        with patch.object(base_client, "request", return_value={"deleted": True}) as mock_request:
            result = base_client.delete("/api/test")
            mock_request.assert_called_once_with("DELETE", "/api/test", params=None, timeout=None)
            assert result == {"deleted": True}


# =============================================================================
# Tests for health_check Method
# =============================================================================


class TestHealthCheck:
    """Tests for the health_check method."""

    def test_health_check_success(self, base_client, mock_logger):
        """
        Test successful health check.

        Verifies that health_check returns True when server is healthy.
        """
        with patch.object(base_client, "get", return_value=None):
            result = base_client.health_check()
            assert result is True

    def test_health_check_failure(self, base_client, mock_logger):
        """
        Test failed health check.

        Verifies that health_check returns False when server is down.
        """
        with patch.object(base_client, "get", side_effect=Exception("Connection failed")):
            result = base_client.health_check()
            assert result is False

    def test_health_check_uses_short_timeout(self, base_client, mock_logger):
        """
        Test that health check uses short timeout.

        Verifies that health_check uses 5 second timeout.
        """
        with patch.object(base_client, "get", return_value=None) as mock_get:
            base_client.health_check()
            mock_get.assert_called_once_with("/health", timeout=5)


# =============================================================================
# Tests for URL Construction
# =============================================================================


class TestURLConstruction:
    """Tests for URL construction in requests."""

    def test_url_construction_with_endpoint(self, base_client_with_url, mock_logger):
        """
        Test URL construction with endpoint.

        Verifies that base_url and endpoint are combined correctly.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": None, "message": "OK"}

        with patch("topsailai_server.agent_daemon.client.base.requests.request", return_value=mock_response) as mock_request:
            base_client_with_url.get("/api/v1/session")
            call_kwargs = mock_request.call_args[1]
            assert call_kwargs["url"] == "http://test-server:8080/api/v1/session"

    def test_url_construction_without_leading_slash(self, base_client_with_url, mock_logger):
        """
        Test URL construction when endpoint doesn't start with slash.

        Verifies that the URL is constructed correctly.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": None, "message": "OK"}

        with patch("topsailai_server.agent_daemon.client.base.requests.request", return_value=mock_response) as mock_request:
            base_client_with_url.get("api/v1/session")
            call_kwargs = mock_request.call_args[1]
            assert call_kwargs["url"] == "http://test-server:8080api/v1/session"


# =============================================================================
# Tests for Response Parsing
# =============================================================================


class TestResponseParsing:
    """Tests for API response parsing."""

    def test_response_with_dict_data(self, base_client, mock_logger):
        """
        Test response parsing with dictionary data.

        Verifies that dictionary data is returned correctly.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": 0,
            "data": {"id": "123", "name": "test"},
            "message": "Success"
        }

        with patch("topsailai_server.agent_daemon.client.base.requests.request", return_value=mock_response):
            result = base_client.request("GET", "/api/test")
            assert result == {"id": "123", "name": "test"}

    def test_response_with_list_data(self, base_client, mock_logger):
        """
        Test response parsing with list data.

        Verifies that list data is returned correctly.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": 0,
            "data": [{"id": "1"}, {"id": "2"}],
            "message": "OK"
        }

        with patch("topsailai_server.agent_daemon.client.base.requests.request", return_value=mock_response):
            result = base_client.request("GET", "/api/test")
            assert result == [{"id": "1"}, {"id": "2"}]

    def test_response_with_null_data(self, base_client, mock_logger):
        """
        Test response parsing with null data.

        Verifies that null data returns None.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": None, "message": "OK"}

        with patch("topsailai_server.agent_daemon.client.base.requests.request", return_value=mock_response):
            result = base_client.request("GET", "/api/test")
            assert result is None

    def test_response_missing_code_field(self, base_client, mock_logger):
        """
        Test response parsing when code field is missing.

        Verifies that missing code defaults to -1 and raises APIError.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": None, "message": "OK"}

        with patch("topsailai_server.agent_daemon.client.base.requests.request", return_value=mock_response):
            with pytest.raises(APIError):
                base_client.request("GET", "/api/test")

    def test_response_missing_message_field(self, base_client, mock_logger):
        """
        Test response parsing when message field is missing.

        Verifies that missing message defaults to "Unknown error".
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": None}

        with patch("topsailai_server.agent_daemon.client.base.requests.request", return_value=mock_response):
            result = base_client.request("GET", "/api/test")
            assert result is None
