"""
Unit tests for custom exceptions.

Author: AI
Created: 2026-04-15
Purpose: Test custom exception classes for agent_daemon
"""

import pickle
import pytest

from exceptions import (
    AgentDaemonError,
    StorageError,
    WorkerError,
    ConfigError,
    APIError,
)


class TestAgentDaemonError:
    """Tests for AgentDaemonError base exception."""

    def test_init_with_message(self):
        """Test initialization with message."""
        error = AgentDaemonError("Test error message")
        assert str(error) == "Test error message"

    def test_inheritance_from_exception(self):
        """Test that AgentDaemonError inherits from Exception."""
        assert issubclass(AgentDaemonError, Exception)
        error = AgentDaemonError("test")
        assert isinstance(error, Exception)

    def test_str_representation(self):
        """Test string representation."""
        error = AgentDaemonError("Error message")
        assert str(error) == "Error message"

    def test_repr_representation(self):
        """Test repr representation."""
        error = AgentDaemonError("Error message")
        assert "AgentDaemonError" in repr(error)
        assert "Error message" in repr(error)

    def test_empty_message(self):
        """Test initialization with empty message."""
        error = AgentDaemonError("")
        assert str(error) == ""

    def test_unicode_message(self):
        """Test initialization with unicode message."""
        error = AgentDaemonError("Error info")
        assert str(error) == "Error info"

    def test_equality(self):
        """Test equality comparison."""
        error1 = AgentDaemonError("same message")
        error2 = AgentDaemonError("same message")
        error3 = AgentDaemonError("different message")
        assert str(error1) == str(error2)
        assert str(error1) != str(error3)


class TestStorageError:
    """Tests for StorageError exception."""

    def test_inheritance(self):
        """Test that StorageError inherits from AgentDaemonError."""
        assert issubclass(StorageError, AgentDaemonError)
        error = StorageError("test")
        assert isinstance(error, AgentDaemonError)
        assert isinstance(error, Exception)

    def test_init_with_message(self):
        """Test initialization with message."""
        error = StorageError("Database connection failed")
        assert str(error) == "Database connection failed"

    def test_str_representation(self):
        """Test string representation."""
        error = StorageError("Storage error occurred")
        assert str(error) == "Storage error occurred"

    def test_repr_representation(self):
        """Test repr representation."""
        error = StorageError("Storage error")
        assert "StorageError" in repr(error)
        assert "Storage error" in repr(error)

    def test_can_be_caught_as_agent_daemon_error(self):
        """Test that StorageError can be caught as AgentDaemonError."""
        try:
            raise StorageError("storage failure")
        except AgentDaemonError as e:
            assert str(e) == "storage failure"

    def test_exception_chaining(self):
        """Test exception chaining with raise from."""
        original = ValueError("original error")
        try:
            raise StorageError("wrapped error") from original
        except StorageError as e:
            assert str(e) == "wrapped error"
            assert e.__cause__ is original

    def test_unicode_message(self):
        """Test with unicode message."""
        error = StorageError("Database error")
        assert str(error) == "Database error"


class TestWorkerError:
    """Tests for WorkerError exception."""

    def test_inheritance(self):
        """Test that WorkerError inherits from AgentDaemonError."""
        assert issubclass(WorkerError, AgentDaemonError)
        error = WorkerError("test")
        assert isinstance(error, AgentDaemonError)
        assert isinstance(error, Exception)

    def test_init_with_message(self):
        """Test initialization with message."""
        error = WorkerError("Worker process crashed")
        assert str(error) == "Worker process crashed"

    def test_str_representation(self):
        """Test string representation."""
        error = WorkerError("Worker timeout")
        assert str(error) == "Worker timeout"

    def test_repr_representation(self):
        """Test repr representation."""
        error = WorkerError("Worker error")
        assert "WorkerError" in repr(error)
        assert "Worker error" in repr(error)

    def test_can_be_caught_as_agent_daemon_error(self):
        """Test that WorkerError can be caught as AgentDaemonError."""
        try:
            raise WorkerError("worker failure")
        except AgentDaemonError as e:
            assert str(e) == "worker failure"

    def test_exception_chaining(self):
        """Test exception chaining with raise from."""
        original = RuntimeError("process error")
        try:
            raise WorkerError("worker failed") from original
        except WorkerError as e:
            assert str(e) == "worker failed"
            assert e.__cause__ is original

    def test_unicode_message(self):
        """Test with unicode message."""
        error = WorkerError("Worker process error")
        assert str(error) == "Worker process error"


class TestConfigError:
    """Tests for ConfigError exception."""

    def test_inheritance(self):
        """Test that ConfigError inherits from AgentDaemonError."""
        assert issubclass(ConfigError, AgentDaemonError)
        error = ConfigError("test")
        assert isinstance(error, AgentDaemonError)
        assert isinstance(error, Exception)

    def test_init_with_message(self):
        """Test initialization with message."""
        error = ConfigError("Missing required config")
        assert str(error) == "Missing required config"

    def test_str_representation(self):
        """Test string representation."""
        error = ConfigError("Invalid configuration value")
        assert str(error) == "Invalid configuration value"

    def test_repr_representation(self):
        """Test repr representation."""
        error = ConfigError("Config error")
        assert "ConfigError" in repr(error)
        assert "Config error" in repr(error)

    def test_can_be_caught_as_agent_daemon_error(self):
        """Test that ConfigError can be caught as AgentDaemonError."""
        try:
            raise ConfigError("config failure")
        except AgentDaemonError as e:
            assert str(e) == "config failure"

    def test_exception_chaining(self):
        """Test exception chaining with raise from."""
        original = KeyError("missing_key")
        try:
            raise ConfigError("configuration invalid") from original
        except ConfigError as e:
            assert str(e) == "configuration invalid"
            assert e.__cause__ is original

    def test_unicode_message(self):
        """Test with unicode message."""
        error = ConfigError("Configuration error")
        assert str(error) == "Configuration error"


class TestAPIError:
    """Tests for APIError exception."""

    def test_inheritance(self):
        """Test that APIError inherits from AgentDaemonError."""
        assert issubclass(APIError, AgentDaemonError)
        error = APIError("test")
        assert isinstance(error, AgentDaemonError)
        assert isinstance(error, Exception)

    def test_init_with_default_status_code(self):
        """Test initialization with default status_code (400)."""
        error = APIError("Bad request")
        assert str(error) == "Bad request"
        assert error.status_code == 400

    def test_init_with_custom_status_code(self):
        """Test initialization with custom status_code."""
        error = APIError("Not found", status_code=404)
        assert str(error) == "Not found"
        assert error.status_code == 404

    def test_init_with_500_status_code(self):
        """Test initialization with 500 status_code."""
        error = APIError("Internal server error", status_code=500)
        assert error.status_code == 500

    def test_str_representation(self):
        """Test string representation."""
        error = APIError("API error occurred", status_code=500)
        assert str(error) == "API error occurred"

    def test_repr_representation(self):
        """Test repr representation."""
        error = APIError("API error", status_code=400)
        assert "APIError" in repr(error)
        assert "API error" in repr(error)

    def test_can_be_caught_as_agent_daemon_error(self):
        """Test that APIError can be caught as AgentDaemonError."""
        try:
            raise APIError("api failure", status_code=500)
        except AgentDaemonError as e:
            assert str(e) == "api failure"
            assert isinstance(e, APIError)
            assert e.status_code == 500

    def test_exception_chaining(self):
        """Test exception chaining with raise from."""
        original = ConnectionError("network error")
        try:
            raise APIError("api call failed", status_code=503) from original
        except APIError as e:
            assert str(e) == "api call failed"
            assert e.status_code == 503
            assert e.__cause__ is original

    def test_4xx_status_codes(self):
        """Test various 4xx status codes."""
        for code in [400, 401, 403, 404, 422, 429]:
            error = APIError(f"Error {code}", status_code=code)
            assert error.status_code == code

    def test_5xx_status_codes(self):
        """Test various 5xx status codes."""
        for code in [500, 502, 503, 504]:
            error = APIError(f"Error {code}", status_code=code)
            assert error.status_code == code

    def test_unicode_message(self):
        """Test with unicode message."""
        error = APIError("API error", status_code=400)
        assert str(error) == "API error"
        assert error.status_code == 400

    def test_status_code_attribute_access(self):
        """Test direct access to status_code attribute."""
        error = APIError("Test", status_code=418)
        assert hasattr(error, 'status_code')
        assert error.status_code == 418


class TestExceptionHierarchy:
    """Tests for exception hierarchy and catching behavior."""

    def test_all_inherit_from_agent_daemon_error(self):
        """Test that all custom exceptions inherit from AgentDaemonError."""
        exceptions = [StorageError, WorkerError, ConfigError, APIError]
        for exc_class in exceptions:
            assert issubclass(exc_class, AgentDaemonError), f"{exc_class} should inherit from AgentDaemonError"

    def test_catch_all_as_base_class(self):
        """Test catching all exceptions as AgentDaemonError."""
        exceptions = [
            StorageError("storage"),
            WorkerError("worker"),
            ConfigError("config"),
            APIError("api", status_code=500),
        ]
        for exc in exceptions:
            try:
                raise exc
            except AgentDaemonError as e:
                assert str(e) == exc.args[0]

    def test_isinstance_checks(self):
        """Test isinstance checks for all exception types."""
        error = APIError("test", status_code=500)
        assert isinstance(error, APIError)
        assert isinstance(error, AgentDaemonError)
        assert isinstance(error, Exception)

    def test_mro_order(self):
        """Test method resolution order."""
        # APIError MRO should be: APIError -> AgentDaemonError -> Exception -> BaseException -> object
        mro = APIError.__mro__
        assert mro[0] == APIError
        assert AgentDaemonError in mro
        assert Exception in mro

    def test_exception_args(self):
        """Test that exception args are preserved."""
        error = APIError("message", status_code=404)
        assert error.args == ("message",)
        assert error.status_code == 404  # status_code is separate attribute

    def test_multiple_catch_blocks(self):
        """Test catching specific exceptions before base class."""
        caught_type = None
        try:
            raise StorageError("specific error")
        except StorageError:
            caught_type = "StorageError"
        except AgentDaemonError:
            caught_type = "AgentDaemonError"
        assert caught_type == "StorageError"


class TestExceptionPickling:
    """Tests for exception pickling (serialization)."""

    def test_agent_daemon_error_pickle(self):
        """Test pickling AgentDaemonError."""
        error = AgentDaemonError("pickle test")
        pickled = pickle.dumps(error)
        restored = pickle.loads(pickled)
        assert str(restored) == str(error)

    def test_storage_error_pickle(self):
        """Test pickling StorageError."""
        error = StorageError("storage pickle")
        pickled = pickle.dumps(error)
        restored = pickle.loads(pickled)
        assert str(restored) == str(error)

    def test_api_error_pickle(self):
        """Test pickling APIError with status_code."""
        error = APIError("api pickle", status_code=500)
        pickled = pickle.dumps(error)
        restored = pickle.loads(pickled)
        assert str(restored) == str(error)
        assert restored.status_code == error.status_code

    def test_worker_error_pickle(self):
        """Test pickling WorkerError."""
        error = WorkerError("worker pickle")
        pickled = pickle.dumps(error)
        restored = pickle.loads(pickled)
        assert str(restored) == str(error)

    def test_config_error_pickle(self):
        """Test pickling ConfigError."""
        error = ConfigError("config pickle")
        pickled = pickle.dumps(error)
        restored = pickle.loads(pickled)
        assert str(restored) == str(error)
