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
    build_socket_path,
    discover_socket_paths,
    format_human_response,
    send_control_request,
)


class TestBuildSocketPath:
    def test_build(self, tmp_path):
        path = build_socket_path(str(tmp_path), "abc", "123")
        assert ".session.sock" in path
        assert path.endswith("abc.123.session.sock")
        assert os.path.isabs(path)

    def test_session_id_with_dots(self, tmp_path):
        path = build_socket_path(str(tmp_path), "my.session", "456")
        assert path.endswith("my.session.456.session.sock")

class TestDiscoverSocketPaths:
    def test_specific_session_and_pid(self, tmp_path):
        stdout = tmp_path / "abc.123.session.stdout"
        stdout.write_text("")
        sock = tmp_path / "abc.123.session.sock"
        sock.write_text("")

        result = discover_socket_paths(
            str(tmp_path),
            session_id="abc",
            pid="123",
        )
        assert len(result) == 1
        assert result[0].endswith("abc.123.session.sock")

    def test_skips_missing_sockets(self, tmp_path):
        stdout = tmp_path / "abc.123.session.stdout"
        stdout.write_text("")

        result = discover_socket_paths(
            str(tmp_path),
            session_id="abc",
            pid="123",
        )
        assert result == []

    def test_all_sessions_sorted_by_mtime(self, tmp_path):
        older = tmp_path / "abc.123.session.stdout"
        older.write_text("")
        (tmp_path / "abc.123.session.sock").write_text("")
        newer = tmp_path / "def.456.session.stdout"
        newer.write_text("")
        (tmp_path / "def.456.session.sock").write_text("")

        import time
        time.sleep(0.01)
        newer.touch()

        result = discover_socket_paths(
            str(tmp_path),
            session_id=None,
            pid=None,
        )
        assert len(result) == 2
        assert result[0].endswith("def.456.session.sock")
        assert result[1].endswith("abc.123.session.sock")

    def test_task_stdout(self, tmp_path):
        stdout = tmp_path / "abc.123.step-1.task.stdout"
        stdout.write_text("")
        sock = tmp_path / "abc.123.session.sock"
        sock.write_text("")

        result = discover_socket_paths(
            str(tmp_path),
            session_id="abc",
            pid="123",
        )
        assert len(result) == 1
        assert result[0].endswith("abc.123.session.sock")

    def test_filter_by_session(self, tmp_path):
        (tmp_path / "abc.123.session.stdout").write_text("")
        (tmp_path / "abc.123.session.sock").write_text("")
        (tmp_path / "def.456.session.stdout").write_text("")
        (tmp_path / "def.456.session.sock").write_text("")

        result = discover_socket_paths(
            str(tmp_path),
            session_id="abc",
            pid=None,
        )
        assert len(result) == 1
        assert result[0].endswith("abc.123.session.sock")

    def test_filter_by_pid(self, tmp_path):
        (tmp_path / "abc.123.step-1.task.stdout").write_text("")
        (tmp_path / "abc.123.session.sock").write_text("")
        (tmp_path / "abc.456.step-2.task.stdout").write_text("")
        (tmp_path / "abc.456.session.sock").write_text("")

        result = discover_socket_paths(
            str(tmp_path),
            session_id=None,
            pid="123",
        )
        assert len(result) == 1
        assert result[0].endswith("abc.123.session.sock")

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

    def test_skips_empty_lines(self):
        mock_sock = MagicMock()
        mock_file = MagicMock()
        mock_file.readline.side_effect = ["\n", "\n", json.dumps({
            "request_id": "server-id",
            "status": "ok",
        }) + "\n"]
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

        assert success is True
        assert response["status"] == "ok"

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
    def test_control_actions_are_discovered_from_runtime_handlers(self):
        assert cli_module.get_control_actions() == [
            "clear_interrupt",
            "get_runtime_messages",
            "get_session_messages",
            "hard_interrupt",
            "soft_interrupt",
        ]

    def test_invalid_json_args_exits(self, capsys):
        with patch.object(sys, "argv", ["script", "-c", "hard_interrupt", "-a", "not-json"]):
            with pytest.raises(SystemExit) as exc_info:
                cli_module.get_params()
            assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "not-json" in captured.err

    def test_non_object_args_exits(self, capsys):
        with patch.object(sys, "argv", ["script", "-c", "hard_interrupt", "-a", "[1, 2]"]):
            with pytest.raises(SystemExit) as exc_info:
                cli_module.get_params()
            assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "[1, 2]" in captured.err

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

    def test_empty_args_default_to_empty_object(self):
        with patch.object(
            sys,
            "argv",
            ["script", "-c", "hard_interrupt", "-a", ""],
        ):
            params = cli_module.get_params()

        assert params["payload"] == {}

    def test_unknown_command_rejected(self):
        with patch.object(sys, "argv", ["script", "-c", "unknown_action"]):
            with pytest.raises(SystemExit):
                cli_module.get_params()


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
        (tmp_path / "abc.123.session.sock").write_text("")

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
        (tmp_path / "abc.123.session.sock").write_text("")

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
        (tmp_path / "abc.123.session.sock").write_text("")

        mock_response = {
            "request_id": "server-id",
            "status": "error",
            "error": "unknown action",
        }
        mock_send = MagicMock(return_value=(True, mock_response))

        code = self._run_main(
            ["script", "-s", "abc", "-p", "123", "-c", "hard_interrupt"],
            tmp_path,
            mock_send=mock_send,
        )

        assert code != 0
        captured = capsys.readouterr()
        assert "unknown action" in captured.out

    def test_connection_failure_continues_to_next(self, tmp_path, capsys):
        (tmp_path / "abc.123.session.stdout").write_text("")
        (tmp_path / "abc.123.session.sock").write_text("")
        (tmp_path / "def.456.session.stdout").write_text("")
        (tmp_path / "def.456.session.sock").write_text("")

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
        (tmp_path / "abc.123.session.sock").write_text("")
        (tmp_path / "def.456.session.stdout").write_text("")
        (tmp_path / "def.456.session.sock").write_text("")

        mock_send = MagicMock(return_value=(False, {"error": "down"}))

        code = self._run_main(
            ["script", "-c", "hard_interrupt"],
            tmp_path,
            mock_send=mock_send,
        )

        assert code != 0
        captured = capsys.readouterr()
        assert "All 2 targets failed" in captured.err
        assert "abc" in captured.err
        assert "def" in captured.err

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


class TestEnsureSessionIdInPayload:
    def test_injects_session_id_for_get_session_messages(self):
        params = {
            "command": "get_session_messages",
            "session_id": "20260804T191116",
            "payload": {},
        }
        result = cli_module._ensure_session_id_in_payload(params)
        assert result["payload"]["session_id"] == "20260804T191116"

    def test_preserves_explicit_payload_session_id(self):
        params = {
            "command": "get_session_messages",
            "session_id": "from-cli",
            "payload": {"session_id": "explicit-id"},
        }
        result = cli_module._ensure_session_id_in_payload(params)
        assert result["payload"]["session_id"] == "explicit-id"

    def test_no_injection_without_session_id(self):
        params = {
            "command": "get_session_messages",
            "session_id": None,
            "payload": {},
        }
        result = cli_module._ensure_session_id_in_payload(params)
        assert result["payload"] == {}

    def test_no_injection_for_other_commands(self):
        params = {
            "command": "hard_interrupt",
            "session_id": "20260804T191116",
            "payload": {},
        }
        result = cli_module._ensure_session_id_in_payload(params)
        assert result["payload"] == {}


class TestMainGetSessionMessages:
    def _run_main(self, argv, tmp_path, mock_send=None):
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

    def test_main_injects_session_id_for_get_session_messages(self, tmp_path, capsys):
        (tmp_path / "20260804T191116.439605.session.stdout").write_text("")
        (tmp_path / "20260804T191116.439605.session.sock").write_text("")

        mock_send = MagicMock(return_value=(True, {
            "status": "ok",
            "request_id": "server-id",
            "result": {"count": 0, "messages": []},
        }))

        code = self._run_main(
            [
                "script",
                "-s", "20260804T191116",
                "-p", "439605",
                "-c", "get_session_messages",
            ],
            tmp_path,
            mock_send=mock_send,
        )

        assert code == 0
        mock_send.assert_called_once()
        _, action, payload, _ = mock_send.call_args[0]
        assert action == "get_session_messages"
        assert payload["session_id"] == "20260804T191116"

    def test_main_preserves_explicit_session_id(self, tmp_path, capsys):
        (tmp_path / "20260804T191116.439605.session.stdout").write_text("")
        (tmp_path / "20260804T191116.439605.session.sock").write_text("")

        mock_send = MagicMock(return_value=(True, {
            "status": "ok",
            "request_id": "server-id",
            "result": {"count": 0, "messages": []},
        }))

        code = self._run_main(
            [
                "script",
                "-s", "20260804T191116",
                "-p", "439605",
                "-c", "get_session_messages",
                "-a", '{"session_id":"explicit-id"}',
            ],
            tmp_path,
            mock_send=mock_send,
        )

        assert code == 0
        mock_send.assert_called_once()
        _, action, payload, _ = mock_send.call_args[0]
        assert action == "get_session_messages"
        assert payload["session_id"] == "explicit-id"
