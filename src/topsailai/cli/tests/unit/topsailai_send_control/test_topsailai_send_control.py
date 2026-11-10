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
    def test_shared_transport_export(self):
        """The old helper delegates to the same hardened public protocol."""
        from cli_topsailai import runtime_control
        assert send_control_request is runtime_control.send_control_request

    @pytest.mark.parametrize("status", ["ok", "error"])
    def test_valid_response_compatibility(self, monkeypatch, status):
        """Correlated rejection remains a transport-success tuple."""
        from cli_topsailai import runtime_control as transport
        response = {"request_id": "id", "status": status}
        def deliver(*args, **kwargs):
            """Simulate structured response without opening a real endpoint."""
            if status == "error":
                raise transport.ControlDeliveryError("rejected", "control_rejected",
                                                     6, "id", False, response)
            return transport.ControlDeliveryResult("id", response)
        monkeypatch.setattr(transport, "send_to_control", deliver)
        assert send_control_request("/fixture/control.sock", "hard_interrupt", {}, 5) == (True, response)

    def test_protocol_failure_compatibility(self, monkeypatch):
        """Malformed correlation remains failure in the old tuple."""
        from cli_topsailai import runtime_control as transport
        def deliver(*args, **kwargs):
            """Reject untrusted response via structured facts."""
            raise transport.ControlDeliveryError("invalid response", "invalid_response", 6)
        monkeypatch.setattr(transport, "send_to_control", deliver)
        assert send_control_request("/fixture/control.sock", "hard_interrupt", {}, 5) == (False, {"error": "invalid response"})


class TestFormatHumanResponse:
    def test_ok_without_result(self):
        text = format_human_response({"status": "ok", "request_id": "abc"}, color=False)
        assert text == "status: ok    request_id: abc"

    def test_ok_with_result(self):
        text = format_human_response({
            "status": "ok",
            "request_id": "abc",
            "result": {"count": 3},
        }, color=False)
        assert "status: ok" in text
        assert "request_id: abc" in text
        assert '  "count": 3' in text

    def test_multiline_string_result_keeps_real_newlines(self):
        """Instruction help output must not be escaped into one line."""
        result = "-----\nInstructions:\n\n  /env.set\n    - set_env\n-----"
        text = format_human_response(
            {"status": "ok", "request_id": "abc", "result": result}, color=False)
        assert result in text
        assert "\\n" not in text
        assert text.endswith(result)

    def test_error(self):
        text = format_human_response({
            "status": "error",
            "request_id": "abc",
            "error": "unknown action",
        }, color=False)
        assert text == "status: error    request_id: abc\nerror: unknown action"

    def test_error_still_prints_non_empty_result(self):
        """A non-empty result is never hidden, even when the status is error."""
        text = format_human_response({
            "status": "error",
            "request_id": "abc",
            "error": "boom",
            "result": "line1\nline2",
        }, color=False)
        assert "error: boom" in text
        assert "line1\nline2" in text

    def test_unknown_status(self):
        text = format_human_response({"request_id": "abc"}, color=False)
        assert "status: unknown" in text

    def test_unknown_status_still_prints_result(self):
        text = format_human_response(
            {"request_id": "abc", "result": {"state": "queued"}}, color=False)
        assert "status: unknown" in text
        assert '"state": "queued"' in text

    @pytest.mark.parametrize("result", [None, "", "   ", {}, [], ()])
    def test_empty_result_is_omitted(self, result):
        """Only an empty result may be hidden."""
        text = format_human_response(
            {"status": "ok", "request_id": "abc", "result": result}, color=False)
        assert text == "status: ok    request_id: abc"

    def test_ansi_and_control_characters_are_stripped(self):
        text = format_human_response({
            "status": "ok",
            "request_id": "abc",
            "result": "\x1b[31mred\x1b[0m\x00ok\r\nnext",
        }, color=False)
        assert "\x1b" not in text
        assert "\x00" not in text
        assert "redok" in text

    def test_error_text_is_sanitized(self):
        text = format_human_response({
            "status": "error",
            "request_id": "abc",
            "error": "\x1b[2Jcleared",
        }, color=False)
        assert "\x1b" not in text
        assert "cleared" in text

    def test_color_disabled_emits_no_escape_codes(self):
        text = format_human_response(
            {"status": "ok", "request_id": "abc", "result": "x"}, color=False)
        assert "\x1b" not in text

    def test_color_enabled_emits_escape_codes(self):
        text = format_human_response(
            {"status": "ok", "request_id": "abc", "result": "x"}, color=True)
        assert "\x1b" in text

    def test_no_color_environment_disables_color(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
        text = format_human_response({"status": "ok", "request_id": "abc"})
        assert "\x1b" not in text

    def test_non_tty_disables_color(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)
        text = format_human_response({"status": "ok", "request_id": "abc"})
        assert "\x1b" not in text


class TestGetParams:
    def test_control_actions_match_the_fallback_list(self):
        """Discovery must agree with the built-in list used when it is unavailable."""
        from cli_topsailai.runtime_cli import _FALLBACK_CONTROL_ACTIONS

        assert cli_module.get_control_actions() == sorted(_FALLBACK_CONTROL_ACTIONS)

    def test_control_actions_fall_back_when_the_registry_is_unavailable(self):
        """An unavailable registry must degrade to the built-in list, not crash."""
        from cli_topsailai import runtime_cli

        with patch("cli_topsailai.runtime_control.get_control_actions",
                   side_effect=ImportError("registry unavailable")):
            assert runtime_cli._help_control_actions() == runtime_cli._FALLBACK_CONTROL_ACTIONS

    def test_call_instruction_command_is_accepted(self):
        with patch.object(sys, "argv", ["script", "-c", "call_instruction"]):
            params = cli_module.get_params()

        assert params["command"] == "call_instruction"

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

    def test_successful_send_readable_by_default(self, tmp_path, capsys):
        """The default output is readable text, not escaped JSON."""
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
        output = captured.out
        assert "status: ok" in output
        assert "request_id: server-id" in output
        assert '  "handled": true' in output
        assert '"request_id": "server-id"' not in output

    def test_default_output_keeps_multiline_result_readable(self, tmp_path, capsys):
        """A multi-line instruction result must not be escaped into one line."""
        (tmp_path / "abc.123.session.stdout").write_text("")
        (tmp_path / "abc.123.session.sock").write_text("")

        result = "-----\nInstructions:\n\n  /env.set\n    - set_env\n-----"
        mock_send = MagicMock(return_value=(True, {
            "request_id": "server-id",
            "status": "ok",
            "result": result,
        }))

        code = self._run_main(
            ["script", "-s", "abc", "-p", "123", "-c", "call_instruction"],
            tmp_path,
            mock_send=mock_send,
        )

        assert code == 0
        output = capsys.readouterr().out
        assert result in output
        assert "\\n" not in output

    def test_default_output_prints_result_for_error_status(self, tmp_path, capsys):
        """A non-empty result is printed even when the status is not ok."""
        (tmp_path / "abc.123.session.stdout").write_text("")
        (tmp_path / "abc.123.session.sock").write_text("")

        mock_send = MagicMock(return_value=(True, {
            "request_id": "server-id",
            "status": "error",
            "error": "unknown action",
            "result": {"detail": "kept"},
        }))

        code = self._run_main(
            ["script", "-s", "abc", "-p", "123", "-c", "hard_interrupt"],
            tmp_path,
            mock_send=mock_send,
        )

        assert code != 0
        output = capsys.readouterr().out
        assert "error: unknown action" in output
        assert '"detail": "kept"' in output

    def test_default_output_omits_empty_result(self, tmp_path, capsys):
        """Only an empty result may be hidden."""
        (tmp_path / "abc.123.session.stdout").write_text("")
        (tmp_path / "abc.123.session.sock").write_text("")

        mock_send = MagicMock(return_value=(True, {
            "request_id": "server-id",
            "status": "ok",
            "result": {},
        }))

        code = self._run_main(
            ["script", "-s", "abc", "-p", "123", "-c", "hard_interrupt"],
            tmp_path,
            mock_send=mock_send,
        )

        assert code == 0
        assert capsys.readouterr().out.strip() == "status: ok    request_id: server-id"

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

    def test_json_output_preserves_escaped_multiline_result(self, tmp_path, capsys):
        """--json keeps the pre-change escaped single-line result."""
        (tmp_path / "abc.123.session.stdout").write_text("")
        (tmp_path / "abc.123.session.sock").write_text("")

        result = "-----\nInstructions:\n-----"
        mock_response = {
            "request_id": "server-id",
            "status": "ok",
            "result": result,
        }
        mock_send = MagicMock(return_value=(True, mock_response))

        code = self._run_main(
            ["script", "-s", "abc", "-p", "123", "-c", "call_instruction", "--json"],
            tmp_path,
            mock_send=mock_send,
        )

        assert code == 0
        output = capsys.readouterr().out
        assert json.loads(output) == mock_response
        assert "\\n" in output

    def test_multi_target_human_mode_prints_headers(self, tmp_path, capsys):
        """Each target block is headed by its socket path in human mode."""
        (tmp_path / "abc.123.session.stdout").write_text("")
        (tmp_path / "abc.123.session.sock").write_text("")
        (tmp_path / "def.456.session.stdout").write_text("")
        (tmp_path / "def.456.session.sock").write_text("")

        mock_send = MagicMock(return_value=(True, {
            "request_id": "server-id",
            "status": "ok",
            "result": "line1\nline2",
        }))

        code = self._run_main(
            ["script", "-c", "hard_interrupt"],
            tmp_path,
            mock_send=mock_send,
        )

        assert code == 0
        output = capsys.readouterr().out
        assert output.count("=== ") == 2
        assert "abc.123.session.sock ===" in output
        assert "def.456.session.sock ===" in output
        assert output.count("line1\nline2") == 2

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
