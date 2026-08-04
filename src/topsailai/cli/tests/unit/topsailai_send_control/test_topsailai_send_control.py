"""Unit tests for topsailai_send_control.py CLI."""
from contextlib import ExitStack

import json
import os
import socket
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure cli/ is importable.
CLI_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(CLI_DIR))

import topsailai_send_control as cli_module
from topsailai_send_control import (
    SOCKET_SUFFIX,
    build_socket_path,
    discover_socket_paths,
    format_human_response,
    send_control_request,
)


class TestBuildSocketPath:
    def test_build(self, tmp_path):
        with patch.object(cli_module, "FOLDER_WORKSPACE_TASK", str(tmp_path)):
            path = build_socket_path("abc", "123")
        assert path.endswith(f"abc.123{SOCKET_SUFFIX}")
        assert os.path.isabs(path)

    def test_session_id_with_dots(self, tmp_path):
        with patch.object(cli_module, "FOLDER_WORKSPACE_TASK", str(tmp_path)):
            path = build_socket_path("my.session", "456")
        assert path.endswith(f"my.session.456{SOCKET_SUFFIX}")


class TestDiscoverSocketPaths:
    def test_specific_session_and_pid(self, tmp_path):
        stdout = tmp_path / "abc.123.session.stdout"
        stdout.write_text("")

        result = discover_socket_paths(
            str(tmp_path),
            session_id="abc",
            pid="123",
        )
        assert len(result) == 1
        assert result[0].endswith(f"abc.123{SOCKET_SUFFIX}")

    def test_all_sessions_sorted_by_mtime(self, tmp_path):
        older = tmp_path / "abc.123.session.stdout"
        older.write_text("")
        newer = tmp_path / "def.456.session.stdout"
        newer.write_text("")

        import time
        time.sleep(0.01)
        newer.touch()

        result = discover_socket_paths(
            str(tmp_path),
            session_id=None,
            pid=None,
        )
        assert len(result) == 2
        assert result[0].endswith(f"def.456{SOCKET_SUFFIX}")
        assert result[1].endswith(f"abc.123{SOCKET_SUFFIX}")

    def test_task_stdout(self, tmp_path):
        stdout = tmp_path / "abc.123.step-1.task.stdout"
        stdout.write_text("")

        result = discover_socket_paths(
            str(tmp_path),
            session_id="abc",
            pid="123",
        )
        assert len(result) == 1
        assert result[0].endswith(f"abc.123{SOCKET_SUFFIX}")

    def test_filter_by_session(self, tmp_path):
        (tmp_path / "abc.123.session.stdout").write_text("")
        (tmp_path / "def.456.session.stdout").write_text("")

        result = discover_socket_paths(
            str(tmp_path),
            session_id="abc",
            pid=None,
        )
        assert len(result) == 1
        assert result[0].endswith(f"abc.123{SOCKET_SUFFIX}")

    def test_filter_by_pid(self, tmp_path):
        (tmp_path / "abc.123.step-1.task.stdout").write_text("")
        (tmp_path / "abc.456.step-2.task.stdout").write_text("")

        result = discover_socket_paths(
            str(tmp_path),
            session_id=None,
            pid="123",
        )
        assert len(result) == 1
        assert result[0].endswith(f"abc.123{SOCKET_SUFFIX}")

    def test_no_task_folder(self, tmp_path):
        nonexistent = tmp_path / "does_not_exist"
        result = discover_socket_paths(str(nonexistent))
        assert result == []

    def test_ignores_non_stdout_files(self, tmp_path):
        (tmp_path / "abc.123.session.stderr").write_text("")
        (tmp_path / "abc.123.session.sock").write_text("")
        result = discover_socket_paths(str(tmp_path))
        assert result == []


class TestSendControlRequest:
    def test_successful_request_response(self):
        mock_sock = MagicMock()
        mock_file = MagicMock()
        mock_file.readline.return_value = json.dumps({
            "request_id": "server-id",
            "status": "ok",
            "result": {"handled": True},
        }) + "\n"
        mock_sock.makefile.return_value = mock_file

        with patch("socket.socket") as mock_socket_class:
            mock_socket_class.return_value.__enter__ = MagicMock(return_value=mock_sock)
            mock_socket_class.return_value.__exit__ = MagicMock(return_value=False)
            success, response = send_control_request(
                "/tmp/test.sock",
                "hard_interrupt",
                {"reason": "test"},
                5.0,
            )

        assert success is True
        assert response["status"] == "ok"
        assert response["result"] == {"handled": True}

        sent = mock_sock.sendall.call_args[0][0]
        request = json.loads(sent.decode("utf-8").strip())
        assert request["action"] == "hard_interrupt"
        assert request["payload"] == {"reason": "test"}
        assert "request_id" in request
        assert len(request["request_id"]) > 0

    def test_connection_timeout(self):
        with patch("socket.socket") as mock_socket_class:
            mock_sock = MagicMock()
            mock_sock.connect.side_effect = socket.timeout("timed out")
            mock_socket_class.return_value.__enter__ = MagicMock(return_value=mock_sock)
            mock_socket_class.return_value.__exit__ = MagicMock(return_value=False)

            success, response = send_control_request(
                "/tmp/test.sock",
                "hard_interrupt",
                {},
                5.0,
            )

        assert success is False
        assert "timed out" in response["error"]

    def test_os_error(self):
        with patch("socket.socket") as mock_socket_class:
            mock_sock = MagicMock()
            mock_sock.connect.side_effect = OSError("no such file")
            mock_socket_class.return_value.__enter__ = MagicMock(return_value=mock_sock)
            mock_socket_class.return_value.__exit__ = MagicMock(return_value=False)

            success, response = send_control_request(
                "/tmp/test.sock",
                "hard_interrupt",
                {},
                5.0,
            )

        assert success is False
        assert "no such file" in response["error"]

    def test_invalid_json_response(self):
        mock_sock = MagicMock()
        mock_file = MagicMock()
        mock_file.readline.return_value = "not-json\n"
        mock_sock.makefile.return_value = mock_file

        with patch("socket.socket") as mock_socket_class:
            mock_socket_class.return_value.__enter__ = MagicMock(return_value=mock_sock)
            mock_socket_class.return_value.__exit__ = MagicMock(return_value=False)
            success, response = send_control_request(
                "/tmp/test.sock",
                "hard_interrupt",
                {},
                5.0,
            )

        assert success is False
        assert "invalid json" in response["error"]

    def test_empty_response(self):
        mock_sock = MagicMock()
        mock_file = MagicMock()
        mock_file.readline.return_value = ""
        mock_sock.makefile.return_value = mock_file

        with patch("socket.socket") as mock_socket_class:
            mock_socket_class.return_value.__enter__ = MagicMock(return_value=mock_sock)
            mock_socket_class.return_value.__exit__ = MagicMock(return_value=False)
            success, response = send_control_request(
                "/tmp/test.sock",
                "hard_interrupt",
                {},
                5.0,
            )

        assert success is False
        assert "closed connection" in response["error"]


class TestFormatHumanResponse:
    def test_ok_without_result(self):
        text = format_human_response({"status": "ok", "request_id": "abc"})
        assert text == "[ok] request_id=abc"

    def test_ok_with_result(self):
        text = format_human_response({
            "status": "ok",
            "request_id": "abc",
            "result": {"count": 3},
        })
        assert "[ok]" in text
        assert "request_id=abc" in text
        assert '{"count": 3}' in text

    def test_error(self):
        text = format_human_response({
            "status": "error",
            "request_id": "abc",
            "error": "unknown action",
        })
        assert text == "[error] request_id=abc error=unknown action"

    def test_unknown_status(self):
        text = format_human_response({"request_id": "abc"})
        assert "[unknown]" in text


class TestGetParams:
    def test_invalid_json_args_exits(self):
        with patch.object(sys, "argv", ["script", "-c", "hard_interrupt", "-a", "not-json"]):
            with pytest.raises(SystemExit) as exc_info:
                cli_module.get_params()
            assert exc_info.value.code == 1

    def test_non_object_args_exits(self):
        with patch.object(sys, "argv", ["script", "-c", "hard_interrupt", "-a", "[1, 2]"]):
            with pytest.raises(SystemExit) as exc_info:
                cli_module.get_params()
            assert exc_info.value.code == 1

    def test_valid_args(self):
        with patch.object(sys, "argv", [
            "script",
            "-s", "abc",
            "-p", "123",
            "-c", "hard_interrupt",
            "-a", '{"reason": "test"}',
            "--timeout", "10.0",
            "--json",
        ]):
            params = cli_module.get_params()

        assert params["session_id"] == "abc"
        assert params["pid"] == "123"
        assert params["command"] == "hard_interrupt"
        assert params["payload"] == {"reason": "test"}
        assert params["timeout"] == 10.0
        assert params["json_output"] is True


class TestMain:
    def _run_main(self, argv, tmp_path, mock_send=None):
        """Run the CLI main with patched task folder and argv."""
        patches = [
            patch.object(cli_module, "FOLDER_WORKSPACE_TASK", str(tmp_path)),
            patch.object(sys, "argv", argv),
        ]
        if mock_send is not None:
            patches.append(patch.object(cli_module, "send_control_request", mock_send))

        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            return cli_module.main()

    def test_no_matches_exits_nonzero(self, tmp_path, capsys):
        code = self._run_main(
            ["script", "-s", "missing", "-p", "99999", "-c", "hard_interrupt"],
            tmp_path,
        )
        assert code != 0
        captured = capsys.readouterr()
        assert "No matching" in captured.err

    def test_successful_send_human_readable(self, tmp_path, capsys):
        (tmp_path / "abc.123.session.stdout").write_text("")

        mock_response = {
            "request_id": "server-id",
            "status": "ok",
            "result": {"handled": True},
        }
        mock_send = MagicMock(return_value=(True, mock_response))

        code = self._run_main(
            ["script", "-s", "abc", "-p", "123", "-c", "hard_interrupt"],
            tmp_path,
            mock_send=mock_send,
        )

        assert code == 0
        captured = capsys.readouterr()
        assert "[ok]" in captured.out
        assert "handled" in captured.out

    def test_successful_send_json_output(self, tmp_path, capsys):
        (tmp_path / "abc.123.session.stdout").write_text("")

        mock_response = {
            "request_id": "server-id",
            "status": "ok",
            "result": {"handled": True},
        }
        mock_send = MagicMock(return_value=(True, mock_response))

        code = self._run_main(
            ["script", "-s", "abc", "-p", "123", "-c", "hard_interrupt", "--json"],
            tmp_path,
            mock_send=mock_send,
        )

        assert code == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["status"] == "ok"

    def test_server_error_exits_nonzero(self, tmp_path, capsys):
        (tmp_path / "abc.123.session.stdout").write_text("")

        mock_response = {
            "request_id": "server-id",
            "status": "error",
            "error": "unknown action",
        }
        mock_send = MagicMock(return_value=(True, mock_response))

        code = self._run_main(
            ["script", "-s", "abc", "-p", "123", "-c", "bad_action"],
            tmp_path,
            mock_send=mock_send,
        )

        assert code != 0
        captured = capsys.readouterr()
        assert "unknown action" in captured.out

    def test_connection_failure_continues_to_next(self, tmp_path, capsys):
        (tmp_path / "abc.123.session.stdout").write_text("")
        (tmp_path / "def.456.session.stdout").write_text("")

        def side_effect(socket_path, action, payload, timeout):
            if "abc" in socket_path:
                return False, {"error": "connection refused"}
            return True, {"status": "ok", "request_id": "server-id", "result": {}}

        mock_send = MagicMock(side_effect=side_effect)

        code = self._run_main(
            ["script", "-c", "hard_interrupt"],
            tmp_path,
            mock_send=mock_send,
        )

        assert code == 0
        captured = capsys.readouterr()
        assert "connection refused" in captured.out
        assert "1/2 targets succeeded" in captured.out

    def test_all_targets_fail(self, tmp_path, capsys):
        (tmp_path / "abc.123.session.stdout").write_text("")
        (tmp_path / "def.456.session.stdout").write_text("")

        mock_send = MagicMock(return_value=(False, {"error": "down"}))

        code = self._run_main(
            ["script", "-c", "hard_interrupt"],
            tmp_path,
            mock_send=mock_send,
        )

        assert code != 0
        captured = capsys.readouterr()
        assert "All 2 targets failed" in captured.err

    def test_socket_path_override(self, tmp_path, capsys):
        override_path = str(tmp_path / "custom.sock")
        mock_send = MagicMock(return_value=(True, {"status": "ok", "request_id": "id"}))

        code = self._run_main(
            ["script", "--socket-path", override_path, "-c", "hard_interrupt"],
            tmp_path,
            mock_send=mock_send,
        )

        assert code == 0
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0]
        assert call_args[0] == override_path
