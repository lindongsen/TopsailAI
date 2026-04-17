"""Unit tests for processor_callback script."""

import os
from unittest.mock import patch, MagicMock

import pytest
import requests

from topsailai_server.agent_daemon.scripts.processor_callback import (
    get_env, call_set_task_result, call_receive_message, main,
)


@pytest.fixture
def mock_sys_exit():
    """Mock sys.exit to prevent actual exit during tests."""
    with patch("topsailai_server.agent_daemon.scripts.processor_callback.sys.exit") as m:
        yield m


@pytest.fixture
def mock_logger():
    """Mock logger to prevent actual logging during tests."""
    with patch("topsailai_server.agent_daemon.scripts.processor_callback.logger") as m:
        yield m


@pytest.fixture
def mock_request_success():
    """Mock request_with_retry to return a successful response."""
    resp = MagicMock(status_code=200, text="OK")
    with patch("topsailai_server.agent_daemon.scripts.processor_callback.request_with_retry", return_value=resp):
        yield resp


@pytest.fixture
def mock_request_failure():
    """Mock request_with_retry to return None (failure)."""
    with patch("topsailai_server.agent_daemon.scripts.processor_callback.request_with_retry", return_value=None):
        yield None


@pytest.fixture
def base_url():
    """Default base URL for testing."""
    return "http://localhost:7373"


# =============================================================================
# get_env Tests
# =============================================================================

class TestGetEnv:
    """Tests for get_env function."""

    def test_required_env_var_present(self):
        """Test get_env returns value when required env var is present."""
        with patch.dict(os.environ, {"TEST_KEY": "test_value"}):
            assert get_env("TEST_KEY", required=True) == "test_value"

    def test_required_env_var_missing_returns_none(self, mock_logger):
        """Test get_env returns None when required env var is missing."""
        with patch.dict(os.environ, {}, clear=True):
            result = get_env("MISSING_KEY", required=True)
            mock_logger.error.assert_called()
            assert result is None

    def test_optional_env_var_present(self):
        """Test get_env returns value when optional env var is present."""
        with patch.dict(os.environ, {"OPT_KEY": "opt_value"}):
            assert get_env("OPT_KEY", required=False) == "opt_value"

    def test_optional_env_var_missing_returns_none(self, mock_sys_exit):
        """Test get_env returns None when optional env var is missing."""
        with patch.dict(os.environ, {}, clear=True):
            assert get_env("MISSING_OPT", required=False) is None
            mock_sys_exit.assert_not_called()

    def test_required_empty_string_returns_none(self, mock_logger):
        """Test get_env returns None when required env var is empty string."""
        with patch.dict(os.environ, {"EMPTY_KEY": ""}):
            result = get_env("EMPTY_KEY", required=True)
            mock_logger.error.assert_called()
            assert result is None

    def test_optional_empty_string_returns_empty(self):
        """Test get_env returns empty string when optional env var is empty."""
        with patch.dict(os.environ, {"EMPTY_OPT": ""}):
            assert get_env("EMPTY_OPT", required=False) == ""

    def test_whitespace_value_not_trimmed(self):
        """Test get_env returns whitespace value as-is (no trimming)."""
        with patch.dict(os.environ, {"WS_KEY": "  value  "}):
            assert get_env("WS_KEY", required=True) == "  value  "

    def test_logs_error_with_key_name(self, mock_logger):
        """Test that get_env logs error message with key name when required var is missing."""
        with patch.dict(os.environ, {}, clear=True):
            get_env("MY_VAR", required=True)
            mock_logger.error.assert_called_once_with(
                "Missing required environment variable: %s", "MY_VAR"
            )


# =============================================================================
# call_set_task_result Tests
# =============================================================================

class TestCallSetTaskResult:
    """Tests for call_set_task_result function."""

    def test_success_returns_true(self, mock_request_success, mock_logger, base_url):
        """Test call_set_task_result returns True on successful API call."""
        assert call_set_task_result(
            session_id="s1", processed_msg_id="m1",
            task_id="t1", task_result="Done", base_url=base_url
        ) is True

    def test_correct_url(self, mock_logger, base_url):
        """Test call_set_task_result calls correct API endpoint URL."""
        with patch("topsailai_server.agent_daemon.scripts.processor_callback.request_with_retry") as mock_request:
            mock_request.return_value = MagicMock(status_code=200)
            call_set_task_result(
                session_id="s1", processed_msg_id="m1",
                task_id="t1", task_result="Done", base_url=base_url
            )
            call_kwargs = mock_request.call_args[1]
            assert call_kwargs["url"] == f"{base_url}/api/v1/task"

    def test_correct_payload(self, mock_logger, base_url):
        """Test call_set_task_result sends correct payload structure."""
        with patch("topsailai_server.agent_daemon.scripts.processor_callback.request_with_retry") as mock_request:
            mock_request.return_value = MagicMock(status_code=200)
            call_set_task_result(
                session_id="s-abc", processed_msg_id="m-xyz",
                task_id="t-123", task_result="Result data", base_url=base_url
            )
            call_kwargs = mock_request.call_args[1]
            assert call_kwargs["payload"] == {
                "session_id": "s-abc", "processed_msg_id": "m-xyz",
                "task_id": "t-123", "task_result": "Result data"
            }

    def test_timeout_30_seconds(self, mock_logger, base_url):
        """Test call_set_task_result uses 30 second timeout."""
        with patch("topsailai_server.agent_daemon.scripts.processor_callback.request_with_retry") as mock_request:
            mock_request.return_value = MagicMock(status_code=200)
            call_set_task_result(
                session_id="s1", processed_msg_id="m1",
                task_id="t1", task_result="R", base_url=base_url
            )
            call_kwargs = mock_request.call_args[1]
            assert call_kwargs["timeout"] == 30

    def test_http_5xx_returns_false(self, mock_request_failure, mock_logger, base_url):
        """Test call_set_task_result returns False on HTTP 5xx error."""
        assert call_set_task_result(
            session_id="s1", processed_msg_id="m1",
            task_id="t1", task_result="R", base_url=base_url
        ) is False
        mock_logger.exception.assert_called()

    def test_http_4xx_returns_false(self, mock_request_failure, mock_logger, base_url):
        """Test call_set_task_result returns False on HTTP 4xx error."""
        result = call_set_task_result(
            session_id="s1", processed_msg_id="m1",
            task_id="t1", task_result="R", base_url=base_url
        )
        assert result is False

    def test_connection_error_returns_false(self, mock_request_failure, mock_logger, base_url):
        """Test call_set_task_result returns False on connection error."""
        result = call_set_task_result(
            session_id="s1", processed_msg_id="m1",
            task_id="t1", task_result="R", base_url=base_url
        )
        assert result is False
        mock_logger.exception.assert_called()

    def test_timeout_error_returns_false(self, mock_request_failure, mock_logger, base_url):
        """Test call_set_task_result returns False on timeout error."""
        result = call_set_task_result(
            session_id="s1", processed_msg_id="m1",
            task_id="t1", task_result="R", base_url=base_url
        )
        assert result is False
        mock_logger.exception.assert_called()

    def test_generic_request_exception_returns_false(self, mock_request_failure, mock_logger, base_url):
        """Test call_set_task_result returns False on generic RequestException."""
        result = call_set_task_result(
            session_id="s1", processed_msg_id="m1",
            task_id="t1", task_result="R", base_url=base_url
        )
        assert result is False

    def test_logs_info_on_success(self, mock_request_success, mock_logger, base_url):
        """Test that call_set_task_result logs info on success."""
        call_set_task_result(
            session_id="s1", processed_msg_id="m1",
            task_id="t1", task_result="R", base_url=base_url
        )
        mock_logger.info.assert_called()

    def test_logs_exception_on_failure(self, mock_request_failure, mock_logger, base_url):
        """Test that call_set_task_result logs exception on failure."""
        call_set_task_result(
            session_id="s1", processed_msg_id="m1",
            task_id="t1", task_result="R", base_url=base_url
        )
        mock_logger.exception.assert_called()

    def test_custom_base_url(self, mock_logger):
        """Test call_set_task_result uses custom base URL."""
        custom = "http://custom-host:9999"
        with patch("topsailai_server.agent_daemon.scripts.processor_callback.request_with_retry") as mock_request:
            mock_request.return_value = MagicMock(status_code=200)
            call_set_task_result(
                session_id="s1", processed_msg_id="m1",
                task_id="t1", task_result="R", base_url=custom
            )
            call_kwargs = mock_request.call_args[1]
            assert call_kwargs["url"] == f"{custom}/api/v1/task"

    def test_empty_task_result(self, mock_logger, base_url):
        """Test call_set_task_result with empty task_result string."""
        with patch("topsailai_server.agent_daemon.scripts.processor_callback.request_with_retry") as mock_request:
            mock_request.return_value = MagicMock(status_code=200)
            assert call_set_task_result(
                session_id="s1", processed_msg_id="m1",
                task_id="t1", task_result="", base_url=base_url
            ) is True

    def test_unicode_task_result(self, mock_logger, base_url):
        """Test call_set_task_result with unicode characters in task_result."""
        with patch("topsailai_server.agent_daemon.scripts.processor_callback.request_with_retry") as mock_request:
            mock_request.return_value = MagicMock(status_code=200)
            assert call_set_task_result(
                session_id="s1", processed_msg_id="m1",
                task_id="t1", task_result="\u4efb\u52a1\u5b8c\u6210", base_url=base_url
            ) is True


# =============================================================================
# call_receive_message Tests
# =============================================================================

class TestCallReceiveMessage:
    """Tests for call_receive_message function."""

    def test_success_returns_true(self, mock_request_success, mock_logger, base_url):
        """Test call_receive_message returns True on successful API call."""
        assert call_receive_message(
            session_id="s1", processed_msg_id="m1",
            message="Hello reply", role="assistant", base_url=base_url
        ) is True

    def test_correct_url(self, mock_logger, base_url):
        """Test call_receive_message calls correct API endpoint URL."""
        with patch("topsailai_server.agent_daemon.scripts.processor_callback.request_with_retry") as mock_request:
            mock_request.return_value = MagicMock(status_code=200)
            call_receive_message(
                session_id="s1", processed_msg_id="m1",
                message="Reply", role="assistant", base_url=base_url
            )
            call_kwargs = mock_request.call_args[1]
            assert call_kwargs["url"] == f"{base_url}/api/v1/message"

    def test_correct_payload(self, mock_logger, base_url):
        """Test call_receive_message sends correct payload structure."""
        with patch("topsailai_server.agent_daemon.scripts.processor_callback.request_with_retry") as mock_request:
            mock_request.return_value = MagicMock(status_code=200)
            call_receive_message(
                session_id="s-abc", processed_msg_id="m-xyz",
                message="Direct reply", role="assistant", base_url=base_url
            )
            call_kwargs = mock_request.call_args[1]
            assert call_kwargs["payload"] == {
                "session_id": "s-abc", "processed_msg_id": "m-xyz",
                "message": "Direct reply", "role": "assistant"
            }

    def test_timeout_30_seconds(self, mock_logger, base_url):
        """Test call_receive_message uses 30 second timeout."""
        with patch("topsailai_server.agent_daemon.scripts.processor_callback.request_with_retry") as mock_request:
            mock_request.return_value = MagicMock(status_code=200)
            call_receive_message(
                session_id="s1", processed_msg_id="m1",
                message="Reply", role="assistant", base_url=base_url
            )
            call_kwargs = mock_request.call_args[1]
            assert call_kwargs["timeout"] == 30

    def test_http_5xx_returns_false(self, mock_request_failure, mock_logger, base_url):
        """Test call_receive_message returns False on HTTP 5xx error."""
        assert call_receive_message(
            session_id="s1", processed_msg_id="m1",
            message="Reply", role="assistant", base_url=base_url
        ) is False
        mock_logger.exception.assert_called()

    def test_http_4xx_returns_false(self, mock_request_failure, mock_logger, base_url):
        """Test call_receive_message returns False on HTTP 4xx error."""
        result = call_receive_message(
            session_id="s1", processed_msg_id="m1",
            message="Reply", role="assistant", base_url=base_url
        )
        assert result is False

    def test_connection_error_returns_false(self, mock_request_failure, mock_logger, base_url):
        """Test call_receive_message returns False on connection error."""
        result = call_receive_message(
            session_id="s1", processed_msg_id="m1",
            message="Reply", role="assistant", base_url=base_url
        )
        assert result is False
        mock_logger.exception.assert_called()

    def test_timeout_error_returns_false(self, mock_request_failure, mock_logger, base_url):
        """Test call_receive_message returns False on timeout error."""
        result = call_receive_message(
            session_id="s1", processed_msg_id="m1",
            message="Reply", role="assistant", base_url=base_url
        )
        assert result is False
        mock_logger.exception.assert_called()

    def test_generic_request_exception_returns_false(self, mock_request_failure, mock_logger, base_url):
        """Test call_receive_message returns False on generic RequestException."""
        result = call_receive_message(
            session_id="s1", processed_msg_id="m1",
            message="Reply", role="assistant", base_url=base_url
        )
        assert result is False

    def test_logs_info_on_success(self, mock_request_success, mock_logger, base_url):
        """Test that call_receive_message logs info on success."""
        call_receive_message(
            session_id="s1", processed_msg_id="m1",
            message="Reply", role="assistant", base_url=base_url
        )
        mock_logger.info.assert_called()

    def test_logs_exception_on_failure(self, mock_request_failure, mock_logger, base_url):
        """Test that call_receive_message logs exception on failure."""
        call_receive_message(
            session_id="s1", processed_msg_id="m1",
            message="Reply", role="assistant", base_url=base_url
        )
        mock_logger.exception.assert_called()

    def test_unicode_message(self, mock_logger, base_url):
        """Test call_receive_message with unicode characters in message."""
        with patch("topsailai_server.agent_daemon.scripts.processor_callback.request_with_retry") as mock_request:
            mock_request.return_value = MagicMock(status_code=200)
            assert call_receive_message(
                session_id="s1", processed_msg_id="m1",
                message="\u3053\u3093\u306b\u3061\u306f", role="assistant", base_url=base_url
            ) is True

    def test_empty_message(self, mock_logger, base_url):
        """Test call_receive_message with empty message string."""
        with patch("topsailai_server.agent_daemon.scripts.processor_callback.request_with_retry") as mock_request:
            mock_request.return_value = MagicMock(status_code=200)
            assert call_receive_message(
                session_id="s1", processed_msg_id="m1",
                message="", role="assistant", base_url=base_url
            ) is True

    def test_custom_base_url(self, mock_logger):
        """Test call_receive_message uses custom base URL."""
        custom = "http://custom-host:9999"
        with patch("topsailai_server.agent_daemon.scripts.processor_callback.request_with_retry") as mock_request:
            mock_request.return_value = MagicMock(status_code=200)
            call_receive_message(
                session_id="s1", processed_msg_id="m1",
                message="Reply", role="assistant", base_url=custom
            )
            call_kwargs = mock_request.call_args[1]
            assert call_kwargs["url"] == f"{custom}/api/v1/message"


# =============================================================================
# main Tests
# =============================================================================

class TestMain:
    """Tests for main function."""

    def test_with_task_id_calls_set_task_result(self, mock_logger, mock_sys_exit):
        """Test main calls SetTaskResult when TASK_ID is present."""
        env = {
            "TOPSAILAI_SESSION_ID": "test-session-123",
            "TOPSAILAI_MSG_ID": "msg-456",
            "TOPSAILAI_FINAL_ANSWER": "Task completed successfully",
            "TOPSAILAI_TASK_ID": "task-789",
            "TOPSAILAI_AGENT_DAEMON_HOST": "localhost",
            "TOPSAILAI_AGENT_DAEMON_PORT": "7373",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("topsailai_server.agent_daemon.scripts.processor_callback.call_set_task_result", return_value=True) as mock_set_task:
                with patch("topsailai_server.agent_daemon.scripts.processor_callback.call_receive_message") as mock_receive:
                    with patch("topsailai_server.agent_daemon.scripts.processor_callback.set_thread_name"):
                        main()
                        mock_set_task.assert_called_once_with(
                            session_id="test-session-123", processed_msg_id="msg-456",
                            task_id="task-789", task_result="Task completed successfully",
                            base_url="http://localhost:7373"
                        )
                        mock_receive.assert_not_called()
                        mock_sys_exit.assert_called_once_with(0)

    def test_without_task_id_calls_receive_message(self, mock_logger, mock_sys_exit):
        """Test main calls ReceiveMessage when TASK_ID is absent."""
        env = {
            "TOPSAILAI_SESSION_ID": "test-session-123",
            "TOPSAILAI_MSG_ID": "msg-456",
            "TOPSAILAI_FINAL_ANSWER": "This is the final answer",
            "TOPSAILAI_AGENT_DAEMON_HOST": "localhost",
            "TOPSAILAI_AGENT_DAEMON_PORT": "7373",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("topsailai_server.agent_daemon.scripts.processor_callback.call_receive_message", return_value=True) as mock_receive:
                with patch("topsailai_server.agent_daemon.scripts.processor_callback.call_set_task_result") as mock_set_task:
                    with patch("topsailai_server.agent_daemon.scripts.processor_callback.set_thread_name"):
                        main()
                        mock_receive.assert_called_once_with(
                            session_id="test-session-123", processed_msg_id="msg-456",
                            message="This is the final answer", role="assistant",
                            base_url="http://localhost:7373"
                        )
                        mock_set_task.assert_not_called()
                        mock_sys_exit.assert_called_once_with(0)

    def test_success_exits_with_zero(self, mock_logger, mock_sys_exit):
        """Test main exits with 0 on successful API call."""
        env = {
            "TOPSAILAI_SESSION_ID": "s1", "TOPSAILAI_MSG_ID": "m1",
            "TOPSAILAI_FINAL_ANSWER": "Answer", "TOPSAILAI_TASK_ID": "t1",
            "TOPSAILAI_AGENT_DAEMON_HOST": "localhost", "TOPSAILAI_AGENT_DAEMON_PORT": "7373",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("topsailai_server.agent_daemon.scripts.processor_callback.call_set_task_result", return_value=True):
                with patch("topsailai_server.agent_daemon.scripts.processor_callback.set_thread_name"):
                    main()
                    mock_sys_exit.assert_called_once_with(0)

    def test_failure_exits_with_one(self, mock_logger, mock_sys_exit):
        """Test main exits with 1 on failed API call."""
        env = {
            "TOPSAILAI_SESSION_ID": "s1", "TOPSAILAI_MSG_ID": "m1",
            "TOPSAILAI_FINAL_ANSWER": "Answer", "TOPSAILAI_TASK_ID": "t1",
            "TOPSAILAI_AGENT_DAEMON_HOST": "localhost", "TOPSAILAI_AGENT_DAEMON_PORT": "7373",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("topsailai_server.agent_daemon.scripts.processor_callback.call_set_task_result", return_value=False):
                with patch("topsailai_server.agent_daemon.scripts.processor_callback.set_thread_name"):
                    main()
                    mock_sys_exit.assert_called_once_with(1)

    def test_missing_session_id_exits_with_one(self, mock_logger, mock_sys_exit):
        """Test main exits when TOPSAILAI_SESSION_ID is missing."""
        env = {
            "TOPSAILAI_MSG_ID": "m1", "TOPSAILAI_FINAL_ANSWER": "Answer",
            "TOPSAILAI_AGENT_DAEMON_HOST": "localhost", "TOPSAILAI_AGENT_DAEMON_PORT": "7373",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("topsailai_server.agent_daemon.scripts.processor_callback.set_thread_name"):
                main()
                mock_sys_exit.assert_called_with(1)

    def test_missing_msg_id_exits_with_one(self, mock_logger, mock_sys_exit):
        """Test main exits when TOPSAILAI_MSG_ID is missing."""
        env = {
            "TOPSAILAI_SESSION_ID": "s1", "TOPSAILAI_FINAL_ANSWER": "Answer",
            "TOPSAILAI_AGENT_DAEMON_HOST": "localhost", "TOPSAILAI_AGENT_DAEMON_PORT": "7373",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("topsailai_server.agent_daemon.scripts.processor_callback.set_thread_name"):
                main()
                mock_sys_exit.assert_any_call(1)

    def test_missing_final_answer_exits_with_one(self, mock_logger, mock_sys_exit):
        """Test main exits when TOPSAILAI_FINAL_ANSWER is missing."""
        env = {
            "TOPSAILAI_SESSION_ID": "s1", "TOPSAILAI_MSG_ID": "m1",
            "TOPSAILAI_AGENT_DAEMON_HOST": "localhost", "TOPSAILAI_AGENT_DAEMON_PORT": "7373",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("topsailai_server.agent_daemon.scripts.processor_callback.set_thread_name"):
                main()
                mock_sys_exit.assert_called_with(1)

    def test_default_host_and_port(self, mock_logger, mock_sys_exit):
        """Test main uses default host (localhost) and port (7373) when env vars are missing."""
        env = {
            "TOPSAILAI_SESSION_ID": "s1", "TOPSAILAI_MSG_ID": "m1",
            "TOPSAILAI_FINAL_ANSWER": "Answer",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("topsailai_server.agent_daemon.scripts.processor_callback.call_receive_message", return_value=True) as mock_receive:
                with patch("topsailai_server.agent_daemon.scripts.processor_callback.set_thread_name"):
                    main()
                    call_kwargs = mock_receive.call_args[1]
                    assert call_kwargs["base_url"] == "http://localhost:7373"

    def test_custom_host_and_port(self, mock_logger, mock_sys_exit):
        """Test main uses custom host and port from env vars."""
        env = {
            "TOPSAILAI_SESSION_ID": "s1", "TOPSAILAI_MSG_ID": "m1",
            "TOPSAILAI_FINAL_ANSWER": "Answer",
            "TOPSAILAI_AGENT_DAEMON_HOST": "my-host",
            "TOPSAILAI_AGENT_DAEMON_PORT": "8080",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("topsailai_server.agent_daemon.scripts.processor_callback.call_receive_message", return_value=True) as mock_receive:
                with patch("topsailai_server.agent_daemon.scripts.processor_callback.set_thread_name"):
                    main()
                    call_kwargs = mock_receive.call_args[1]
                    assert call_kwargs["base_url"] == "http://my-host:8080"

    def test_receive_message_failure_exits_with_one(self, mock_logger, mock_sys_exit):
        """Test main exits with 1 when call_receive_message fails."""
        env = {
            "TOPSAILAI_SESSION_ID": "s1", "TOPSAILAI_MSG_ID": "m1",
            "TOPSAILAI_FINAL_ANSWER": "Answer",
            "TOPSAILAI_AGENT_DAEMON_HOST": "localhost", "TOPSAILAI_AGENT_DAEMON_PORT": "7373",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("topsailai_server.agent_daemon.scripts.processor_callback.call_receive_message", return_value=False):
                with patch("topsailai_server.agent_daemon.scripts.processor_callback.set_thread_name"):
                    main()
                    mock_sys_exit.assert_called_once_with(1)

    def test_set_thread_name_called(self, mock_logger, mock_sys_exit):
        """Test main calls set_thread_name for thread identification."""
        env = {
            "TOPSAILAI_SESSION_ID": "s1", "TOPSAILAI_MSG_ID": "m1",
            "TOPSAILAI_FINAL_ANSWER": "Answer",
            "TOPSAILAI_AGENT_DAEMON_HOST": "localhost", "TOPSAILAI_AGENT_DAEMON_PORT": "7373",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("topsailai_server.agent_daemon.scripts.processor_callback.call_receive_message", return_value=True):
                with patch("topsailai_server.agent_daemon.scripts.processor_callback.set_thread_name") as mock_thread:
                    main()
                    mock_thread.assert_called_once()

    def test_no_env_vars_exits_with_one(self, mock_logger, mock_sys_exit):
        """Test main exits with 1 when all required env vars are missing."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("topsailai_server.agent_daemon.scripts.processor_callback.set_thread_name"):
                main()
                mock_sys_exit.assert_called_with(1)

    def test_unicode_final_answer(self, mock_logger, mock_sys_exit):
        """Test main handles unicode characters in FINAL_ANSWER env var."""
        env = {
            "TOPSAILAI_SESSION_ID": "s1", "TOPSAILAI_MSG_ID": "m1",
            "TOPSAILAI_FINAL_ANSWER": "\u4efb\u52a1\u5b8c\u6210 \U0001f389",
            "TOPSAILAI_AGENT_DAEMON_HOST": "localhost", "TOPSAILAI_AGENT_DAEMON_PORT": "7373",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("topsailai_server.agent_daemon.scripts.processor_callback.call_receive_message", return_value=True) as mock_receive:
                with patch("topsailai_server.agent_daemon.scripts.processor_callback.set_thread_name"):
                    main()
                    call_kwargs = mock_receive.call_args[1]
                    assert call_kwargs["message"] == "\u4efb\u52a1\u5b8c\u6210 \U0001f389"
                    with patch("topsailai_server.agent_daemon.scripts.processor_callback.set_thread_name") as mock_thread:
                        main()
                        mock_thread.assert_called_once()

    def test_no_env_vars_exits_with_one(self, mock_logger, mock_sys_exit):
        """Test main exits with 1 when all required env vars are missing."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("topsailai_server.agent_daemon.scripts.processor_callback.set_thread_name"):
                main()
                mock_sys_exit.assert_any_call(1)

    def test_unicode_final_answer(self, mock_logger, mock_sys_exit):
        """Test main handles unicode characters in FINAL_ANSWER env var."""
        env = {
            "TOPSAILAI_SESSION_ID": "s1", "TOPSAILAI_MSG_ID": "m1",
            "TOPSAILAI_FINAL_ANSWER": "\u4efb\u52a1\u5b8c\u6210 \U0001f389",
            "TOPSAILAI_AGENT_DAEMON_HOST": "localhost", "TOPSAILAI_AGENT_DAEMON_PORT": "7373",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("topsailai_server.agent_daemon.scripts.processor_callback.call_receive_message", return_value=True) as mock_receive:
                with patch("topsailai_server.agent_daemon.scripts.processor_callback.set_thread_name"):
                    main()
                    call_kwargs = mock_receive.call_args[1]
                    assert call_kwargs["message"] == "\u4efb\u52a1\u5b8c\u6210 \U0001f389"
