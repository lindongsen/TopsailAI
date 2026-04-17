"""
Unit tests for api/utils.py

Tests the unified API response format utilities including:
- ApiResponse model
- success_response function
- error_response function
"""

import pytest
from datetime import datetime
from topsailai_server.agent_daemon.api.utils import (
    ApiResponse,
    success_response,
    error_response,
)


class TestApiResponse:
    """Tests for ApiResponse model."""

    def test_default_values(self):
        """Test ApiResponse with default values."""
        response = ApiResponse()
        assert response.code == 0
        assert response.data is None
        assert response.message is None

    def test_with_data(self):
        """Test ApiResponse with data."""
        data = {"key": "value", "count": 42}
        response = ApiResponse(code=0, data=data, message="OK")
        assert response.code == 0
        assert response.data == data
        assert response.message == "OK"

    def test_with_error_code(self):
        """Test ApiResponse with error code."""
        response = ApiResponse(code=-1, data=None, message="Not found")
        assert response.code == -1
        assert response.data is None
        assert response.message == "Not found"

    def test_with_complex_data(self):
        """Test ApiResponse with complex nested data."""
        complex_data = {
            "sessions": [
                {"session_id": "s1", "name": "Session 1"},
                {"session_id": "s2", "name": "Session 2"},
            ],
            "total": 2,
            "pagination": {"offset": 0, "limit": 100},
        }
        response = ApiResponse(code=0, data=complex_data)
        assert response.data == complex_data

    def test_with_list_data(self):
        """Test ApiResponse with list data."""
        list_data = ["item1", "item2", "item3"]
        response = ApiResponse(code=0, data=list_data)
        assert response.data == list_data

    def test_with_datetime_data(self):
        """Test ApiResponse with datetime in data."""
        now = datetime.now()
        data = {"timestamp": now}
        response = ApiResponse(code=0, data=data)
        assert response.data["timestamp"] == now

    def test_with_none_message(self):
        """Test ApiResponse with None message."""
        response = ApiResponse(code=0, data={"key": "value"}, message=None)
        assert response.message is None

    def test_with_empty_string_message(self):
        """Test ApiResponse with empty string message."""
        response = ApiResponse(code=0, data=None, message="")
        assert response.message == ""

    def test_model_dump(self):
        """Test ApiResponse model_dump method."""
        response = ApiResponse(code=0, data={"key": "value"}, message="OK")
        dumped = response.model_dump()
        assert dumped["code"] == 0
        assert dumped["data"] == {"key": "value"}
        assert dumped["message"] == "OK"


class TestSuccessResponse:
    """Tests for success_response function."""

    def test_default_success_response(self):
        """Test success_response with default values."""
        response = success_response()
        assert response.code == 0
        assert response.data is None
        assert response.message == "OK"

    def test_success_response_with_data(self):
        """Test success_response with custom data."""
        data = {"session_id": "test123", "name": "Test Session"}
        response = success_response(data=data)
        assert response.code == 0
        assert response.data == data
        assert response.message == "OK"

    def test_success_response_with_custom_message(self):
        """Test success_response with custom message."""
        response = success_response(message="Custom success message")
        assert response.code == 0
        assert response.data is None
        assert response.message == "Custom success message"

    def test_success_response_with_data_and_message(self):
        """Test success_response with both data and custom message."""
        data = {"id": 1, "status": "completed"}
        response = success_response(data=data, message="Operation completed")
        assert response.code == 0
        assert response.data == data
        assert response.message == "Operation completed"

    def test_success_response_with_list_data(self):
        """Test success_response with list data."""
        data = ["item1", "item2", "item3"]
        response = success_response(data=data)
        assert response.data == data

    def test_success_response_with_empty_list(self):
        """Test success_response with empty list data."""
        response = success_response(data=[])
        assert response.data == []

    def test_success_response_with_nested_data(self):
        """Test success_response with nested data structure."""
        data = {
            "user": {"id": 1, "name": "John"},
            "sessions": [{"id": "s1"}, {"id": "s2"}],
        }
        response = success_response(data=data)
        assert response.data == data


class TestErrorResponse:
    """Tests for error_response function."""

    def test_default_error_response(self):
        """Test error_response with default error code."""
        response = error_response(message="Error occurred")
        assert response.code == -1
        assert response.data is None
        assert response.message == "Error occurred"

    def test_error_response_with_custom_code(self):
        """Test error_response with custom error code."""
        response = error_response(message="Not found", code=404)
        assert response.code == 404
        assert response.message == "Not found"

    def test_error_response_with_various_codes(self):
        """Test error_response with various error codes."""
        error_codes = {
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            500: "Internal Server Error",
        }
        for code, msg in error_codes.items():
            response = error_response(message=msg, code=code)
            assert response.code == code
            assert response.message == msg

    def test_error_response_with_empty_message(self):
        """Test error_response with empty message."""
        response = error_response(message="")
        assert response.code == -1
        assert response.message == ""

    def test_error_response_with_long_message(self):
        """Test error_response with long error message."""
        long_message = "This is a very long error message " * 10
        response = error_response(message=long_message)
        assert response.message == long_message

    def test_error_response_with_special_characters(self):
        """Test error_response with special characters in message."""
        special_msg = "Error: <script>alert('xss')</script> & 'quotes'"
        response = error_response(message=special_msg)
        assert response.message == special_msg


class TestResponseIntegration:
    """Integration tests for response utilities."""

    def test_success_then_error_workflow(self):
        """Test a workflow that goes from success to error."""
        # First operation succeeds
        success = success_response(data={"id": 1}, message="Created")
        assert success.code == 0

        # Second operation fails
        error = error_response(message="Update failed", code=500)
        assert error.code == 500

    def test_multiple_success_responses(self):
        """Test creating multiple success responses."""
        responses = [
            success_response(data={"count": i}) for i in range(5)
        ]
        for r in responses:
            assert r.code == 0
            assert r.message == "OK"

    def test_multiple_error_responses(self):
        """Test creating multiple error responses."""
        errors = [
            error_response(message=f"Error {i}", code=i * 100)
            for i in range(1, 6)
        ]
        for i, r in enumerate(errors):
            assert r.code == (i + 1) * 100
            assert r.message == f"Error {i + 1}"

    def test_response_serialization(self):
        """Test response serialization to dict."""
        response = success_response(
            data={"key": "value"},
            message="Success"
        )
        serialized = response.model_dump()
        assert isinstance(serialized, dict)
        assert serialized["code"] == 0
        assert serialized["data"] == {"key": "value"}
        assert serialized["message"] == "Success"
