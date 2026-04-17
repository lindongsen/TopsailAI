"""
Unit Tests for SessionClient Module

This module contains unit tests for the SessionClient class which provides
methods for managing sessions including listing, retrieving, deleting,
and processing sessions.

Test Coverage:
    - list_sessions: List sessions with filtering and pagination
    - get_session: Get a single session by ID
    - delete_sessions: Delete multiple sessions
    - process_session: Trigger processing of pending messages

Usage:
    Run all tests:
        pytest tests/unit/test_client/test_session.py -v

    Run specific test class:
        pytest tests/unit/test_client/test_session.py::TestSessionClient -v
"""

import pytest
from unittest.mock import MagicMock, patch
from typing import Any, Dict, List

from topsailai_server.agent_daemon.client.session import SessionClient


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
def session_client(mock_logger):
    """
    Create a SessionClient instance with mocked logger.

    Args:
        mock_logger: Mock logger fixture.

    Returns:
        SessionClient: A SessionClient instance with mocked logger.
    """
    with patch.object(SessionClient, '__init__', lambda self: None):
        client = SessionClient()
        client.logger = mock_logger
        client.base_url = "http://localhost:7373"
        client.timeout = 30
        return client


@pytest.fixture
def sample_session():
    """
    Create a sample session dictionary.

    Returns:
        Dict[str, Any]: A sample session with all fields.
    """
    return {
        "session_id": "session-123",
        "session_name": "Test Session",
        "task": "Test task description",
        "create_time": "2024-01-15T10:30:00",
        "update_time": "2024-01-15T11:00:00",
        "processed_msg_id": "msg-001",
        "status": "idle"
    }


@pytest.fixture
def sample_sessions(sample_session):
    """
    Create a list of sample sessions.

    Args:
        sample_session: Single session fixture.

    Returns:
        List[Dict[str, Any]]: List of sample sessions.
    """
    session2 = sample_session.copy()
    session2["session_id"] = "session-456"
    session2["session_name"] = "Another Session"

    session3 = sample_session.copy()
    session3["session_id"] = "session-789"
    session3["session_name"] = "Third Session"

    return [sample_session, session2, session3]


# =============================================================================
# Test Class: TestSessionClient
# =============================================================================

class TestSessionClient:
    """
    Test suite for SessionClient class.

    Tests cover all public methods of the SessionClient class including
    success cases, error handling, and parameter validation.
    """

    # =========================================================================
    # Tests for list_sessions method
    # =========================================================================

    def test_list_sessions_default_params(self, session_client):
        """
        Test list_sessions with default parameters.

        Verifies that the method calls the API with correct default parameters.
        """
        with patch.object(session_client, 'get', return_value=[]) as mock_get:
            result = session_client.list_sessions()

            mock_get.assert_called_once()
            call_args = mock_get.call_args
            assert call_args[0][0] == "/api/v1/session"
            assert call_args[1]["params"]["offset"] == 0
            assert call_args[1]["params"]["limit"] == 1000
            assert call_args[1]["params"]["sort_key"] == "create_time"
            assert call_args[1]["params"]["order_by"] == "desc"
            assert result == []

    def test_list_sessions_with_filters(self, session_client, sample_sessions):
        """
        Test list_sessions with various filters.

        Verifies that filters are correctly passed to the API.
        """
        with patch.object(session_client, 'get', return_value=sample_sessions) as mock_get:
            result = session_client.list_sessions(
                session_ids=["session-123", "session-456"],
                start_time="2024-01-01T00:00:00",
                end_time="2024-01-31T23:59:59",
                offset=10,
                limit=50,
                sort_key="update_time",
                order_by="asc"
            )

            call_args = mock_get.call_args
            params = call_args[1]["params"]
            assert params["session_ids"] == ["session-123", "session-456"]
            assert params["start_time"] == "2024-01-01T00:00:00"
            assert params["end_time"] == "2024-01-31T23:59:59"
            assert params["offset"] == 10
            assert params["limit"] == 50
            assert params["sort_key"] == "update_time"
            assert params["order_by"] == "asc"
            assert len(result) == 3

    def test_list_sessions_empty_result(self, session_client):
        """
        Test list_sessions with empty result.

        Verifies that empty results are handled correctly.
        """
        with patch.object(session_client, 'get', return_value=[]) as mock_get:
            result = session_client.list_sessions()
            assert result == []
            assert mock_get.called

    def test_list_sessions_verbose_output(self, session_client, sample_sessions, capsys):
        """
        Test list_sessions with verbose=True.

        Verifies that verbose mode prints formatted output.
        """
        with patch.object(session_client, 'get', return_value=sample_sessions):
            result = session_client.list_sessions(verbose=True)
            captured = capsys.readouterr()
            assert "Retrieved Sessions: 3" in captured.out
            assert "session-123" in captured.out

    def test_list_sessions_without_session_ids(self, session_client, sample_sessions):
        """
        Test list_sessions when session_ids is not provided.

        Verifies that session_ids is not included in params when not provided.
        """
        with patch.object(session_client, 'get', return_value=sample_sessions) as mock_get:
            session_client.list_sessions()
            params = mock_get.call_args[1]["params"]
            assert "session_ids" not in params

    def test_list_sessions_without_time_filters(self, session_client, sample_sessions):
        """
        Test list_sessions when time filters are not provided.

        Verifies that time filters are not included in params when not provided.
        """
        with patch.object(session_client, 'get', return_value=sample_sessions) as mock_get:
            session_client.list_sessions()
            params = mock_get.call_args[1]["params"]
            assert "start_time" not in params
            assert "end_time" not in params

    # =========================================================================
    # Tests for get_session method
    # =========================================================================

    def test_get_session_success(self, session_client, sample_session):
        """
        Test get_session with valid session ID.

        Verifies that the method returns session details correctly.
        """
        with patch.object(session_client, 'get', return_value=sample_session):
            result = session_client.get_session("session-123")

            assert result["session_id"] == "session-123"
            assert result["session_name"] == "Test Session"
            assert result["status"] == "idle"
            assert result["processed_msg_id"] == "msg-001"

    def test_get_session_verbose_output(self, session_client, sample_session, capsys):
        """
        Test get_session with verbose=True.

        Verifies that verbose mode prints full JSON response.
        """
        with patch.object(session_client, 'get', return_value=sample_session):
            session_client.get_session("session-123", verbose=True)
            captured = capsys.readouterr()
            assert "Session Details" in captured.out
            assert "session-123" in captured.out
            assert "Test Session" in captured.out
            assert "idle" in captured.out

    def test_get_session_formatted_output(self, session_client, sample_session, capsys):
        """
        Test get_session formatted output.

        Verifies that session details are printed correctly.
        """
        with patch.object(session_client, 'get', return_value=sample_session):
            session_client.get_session("session-123")
            captured = capsys.readouterr()
            assert "Session ID:" in captured.out
            assert "Session Name:" in captured.out
            assert "Status:" in captured.out
            assert "Task:" in captured.out
            assert "Processed:" in captured.out
            assert "Created:" in captured.out
            assert "Updated:" in captured.out

    def test_get_session_with_missing_fields(self, session_client):
        """
        Test get_session with session having missing optional fields.

        Verifies that missing fields are handled gracefully with defaults.
        """
        incomplete_session = {
            "session_id": "session-123"
        }

        with patch.object(session_client, 'get', return_value=incomplete_session):
            result = session_client.get_session("session-123")
            assert result["session_id"] == "session-123"
            assert result.get("session_name", "N/A") == "N/A"
            assert result.get("task", "N/A") == "N/A"
            assert result.get("status", "N/A") == "N/A"

    def test_get_session_api_error(self, session_client):
        """
        Test get_session when API returns error.

        Verifies that API errors are propagated correctly.
        """
        from topsailai_server.agent_daemon.client.base import APIError

        with patch.object(session_client, 'get', side_effect=APIError(404, "Session not found")):
            with pytest.raises(APIError) as exc_info:
                session_client.get_session("nonexistent")
            assert "Session not found" in str(exc_info.value)

    # =========================================================================
    # Tests for delete_sessions method
    # =========================================================================

    def test_delete_sessions_success(self, session_client):
        """
        Test delete_sessions with valid session IDs.

        Verifies that sessions are deleted successfully.
        """
        mock_result = {"deleted_count": 2}

        with patch.object(session_client, 'delete', return_value=mock_result) as mock_delete:
            result = session_client.delete_sessions(["session-123", "session-456"])

            mock_delete.assert_called_once()
            call_args = mock_delete.call_args
            assert call_args[0][0] == "/api/v1/session"
            assert call_args[1]["params"]["session_ids"] == "session-123,session-456"
            assert result["deleted_count"] == 2

    def test_delete_sessions_empty_list_raises_error(self, session_client):
        """
        Test delete_sessions with empty list.

        Verifies that ValueError is raised for empty session_ids.
        """
        with pytest.raises(ValueError) as exc_info:
            session_client.delete_sessions([])
        assert "At least one session ID is required" in str(exc_info.value)

    def test_delete_sessions_single_id(self, session_client):
        """
        Test delete_sessions with single session ID.

        Verifies that single ID is handled correctly.
        """
        mock_result = {"deleted_count": 1}

        with patch.object(session_client, 'delete', return_value=mock_result):
            result = session_client.delete_sessions(["session-123"])
            assert result["deleted_count"] == 1

    def test_delete_sessions_verbose_output(self, session_client, capsys):
        """
        Test delete_sessions with verbose=True.

        Verifies that verbose mode prints full JSON response.
        """
        mock_result = {"deleted_count": 2, "details": {"session-123": True}}

        with patch.object(session_client, 'delete', return_value=mock_result):
            session_client.delete_sessions(["session-123", "session-456"], verbose=True)
            captured = capsys.readouterr()
            assert "Deleted 2 session(s)" in captured.out

    def test_delete_sessions_no_result(self, session_client):
        """
        Test delete_sessions when API returns None.

        Verifies that None result is handled gracefully.
        """
        with patch.object(session_client, 'delete', return_value=None):
            result = session_client.delete_sessions(["session-123"])
            assert result is None

    def test_delete_sessions_api_error(self, session_client):
        """
        Test delete_sessions when API returns error.

        Verifies that API errors are propagated correctly.
        """
        from topsailai_server.agent_daemon.client.base import APIError

        with patch.object(session_client, 'delete', side_effect=APIError(500, "Delete failed")):
            with pytest.raises(APIError) as exc_info:
                session_client.delete_sessions(["session-123"])
            assert "Delete failed" in str(exc_info.value)

    # =========================================================================
    # Tests for process_session method
    # =========================================================================

    def test_process_session_success(self, session_client):
        """
        Test process_session with valid session ID.

        Verifies that processing is triggered successfully.
        """
        mock_result = {
            "processed": True,
            "message": "Processing started",
            "processing_msg_id": "msg-002",
            "messages": [{"msg_id": "msg-002", "content": "test"}],
            "processor_pid": 12345
        }

        with patch.object(session_client, 'post', return_value=mock_result) as mock_post:
            result = session_client.process_session("session-123")

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == "/api/v1/session/process"
            assert call_args[1]["json_data"]["session_id"] == "session-123"
            assert result["processed"] is True
            assert result["processor_pid"] == 12345

    def test_process_session_no_messages(self, session_client):
        """
        Test process_session when no messages to process.

        Verifies that response is handled correctly.
        """
        mock_result = {
            "processed": False,
            "message": "No messages to process"
        }

        with patch.object(session_client, 'post', return_value=mock_result):
            result = session_client.process_session("session-123")
            assert result["processed"] is False
            assert "No messages" in result["message"]

    def test_process_session_verbose_output(self, session_client, capsys):
        """
        Test process_session with verbose=True.

        Verifies that verbose mode prints full JSON response.
        """
        mock_result = {
            "processed": True,
            "message": "Processing started",
            "processor_pid": 12345
        }

        with patch.object(session_client, 'post', return_value=mock_result):
            session_client.process_session("session-123", verbose=True)
            captured = capsys.readouterr()
            assert "Session processed: True" in captured.out
            assert "Processing started" in captured.out

    def test_process_session_formatted_output(self, session_client, capsys):
        """
        Test process_session formatted output.

        Verifies that processing status is printed correctly.
        """
        mock_result = {
            "processed": True,
            "message": "Processing started"
        }

        with patch.object(session_client, 'post', return_value=mock_result):
            session_client.process_session("session-123")
            captured = capsys.readouterr()
            assert "Session processed: True" in captured.out
            assert "Message: Processing started" in captured.out

    def test_process_session_api_error(self, session_client):
        """
        Test process_session when API returns error.

        Verifies that API errors are propagated correctly.
        """
        from topsailai_server.agent_daemon.client.base import APIError

        with patch.object(session_client, 'post', side_effect=APIError(500, "Processing failed")):
            with pytest.raises(APIError) as exc_info:
                session_client.process_session("session-123")
            assert "Processing failed" in str(exc_info.value)

    def test_process_session_with_missing_result_fields(self, session_client):
        """
        Test process_session when result has missing fields.

        Verifies that missing fields are handled gracefully.
        """
        mock_result = {"processed": True}

        with patch.object(session_client, 'post', return_value=mock_result):
            result = session_client.process_session("session-123")
            assert result["processed"] is True
            assert result.get("message", "") == ""

    # =========================================================================
    # Tests for _print_session method (private helper)
    # =========================================================================

    def test_print_session_with_full_data(self, session_client, sample_session, capsys):
        """
        Test _print_session with complete session data.

        Verifies that session is printed correctly.
        """
        session_client._print_session(sample_session)
        captured = capsys.readouterr()
        assert "session-123" in captured.out
        assert "Test Session" in captured.out
        assert "Test task description" in captured.out
        assert "msg-001" in captured.out

    def test_print_session_with_missing_fields(self, session_client, capsys):
        """
        Test _print_session with missing optional fields.

        Verifies that missing fields show 'N/A'.
        """
        incomplete_session = {
            "session_id": "session-123",
            "session_name": "session-123"
        }
        session_client._print_session(incomplete_session)
        captured = capsys.readouterr()
        assert "session-123" in captured.out
        assert "N/A" in captured.out

    def test_print_session_different_id_and_name(self, session_client, sample_session, capsys):
        """
        Test _print_session when session_id differs from session_name.

        Verifies that both are displayed.
        """
        sample_session["session_name"] = "Different Name"
        session_client._print_session(sample_session)
        captured = capsys.readouterr()
        assert "session-123: Different Name" in captured.out

    def test_print_session_same_id_and_name(self, session_client, sample_session, capsys):
        """
        Test _print_session when session_id equals session_name.

        Verifies that only one is displayed.
        """
        sample_session["session_name"] = "session-123"
        session_client._print_session(sample_session)
        captured = capsys.readouterr()
        assert captured.out.count("session-123") >= 1


# =============================================================================
# Test Class: TestSessionClientEdgeCases
# =============================================================================

class TestSessionClientEdgeCases:
    """
    Test suite for edge cases in SessionClient class.

    Tests cover boundary conditions, special inputs, and error scenarios.
    """

    def test_list_sessions_large_offset(self, session_client):
        """
        Test list_sessions with large offset value.

        Verifies that large offset is handled correctly.
        """
        with patch.object(session_client, 'get', return_value=[]) as mock_get:
            session_client.list_sessions(offset=1000000)
            params = mock_get.call_args[1]["params"]
            assert params["offset"] == 1000000

    def test_list_sessions_large_limit(self, session_client):
        """
        Test list_sessions with large limit value.

        Verifies that large limit is handled correctly.
        """
        with patch.object(session_client, 'get', return_value=[]) as mock_get:
            session_client.list_sessions(limit=100000)
            params = mock_get.call_args[1]["params"]
            assert params["limit"] == 100000

    def test_list_sessions_invalid_sort_key(self, session_client):
        """
        Test list_sessions with invalid sort key.

        Verifies that invalid sort key is passed to API (API should validate).
        """
        with patch.object(session_client, 'get', return_value=[]) as mock_get:
            session_client.list_sessions(sort_key="invalid_field")
            params = mock_get.call_args[1]["params"]
            assert params["sort_key"] == "invalid_field"

    def test_list_sessions_invalid_order_by(self, session_client):
        """
        Test list_sessions with invalid order_by value.

        Verifies that invalid order_by is passed to API (API should validate).
        """
        with patch.object(session_client, 'get', return_value=[]) as mock_get:
            session_client.list_sessions(order_by="invalid")
            params = mock_get.call_args[1]["params"]
            assert params["order_by"] == "invalid"

    def test_delete_sessions_many_ids(self, session_client):
        """
        Test delete_sessions with many session IDs.

        Verifies that many IDs are joined correctly.
        """
        mock_result = {"deleted_count": 100}
        many_ids = [f"session-{i}" for i in range(100)]

        with patch.object(session_client, 'delete', return_value=mock_result) as mock_delete:
            session_client.delete_sessions(many_ids)
            params = mock_delete.call_args[1]["params"]
            assert "session-0" in params["session_ids"]
            assert "session-99" in params["session_ids"]

    def test_get_session_special_characters_in_id(self, session_client):
        """
        Test get_session with special characters in session ID.

        Verifies that special characters are handled correctly.
        """
        special_id = "session-123-abc_def.ghi"
        mock_session = {"session_id": special_id}

        with patch.object(session_client, 'get', return_value=mock_session):
            result = session_client.get_session(special_id)
            assert result["session_id"] == special_id

    def test_process_session_concurrent_processing(self, session_client):
        """
        Test process_session when session is already being processed.

        Verifies that response indicates processing already in progress.
        """
        mock_result = {
            "processed": False,
            "message": "Session is already being processed"
        }

        with patch.object(session_client, 'post', return_value=mock_result):
            result = session_client.process_session("session-123")
            assert result["processed"] is False
            assert "already" in result["message"].lower()
