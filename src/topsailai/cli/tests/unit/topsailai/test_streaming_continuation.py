"""Regression coverage for command-independent runtime viewer lifetime."""
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from cli_topsailai import state, streaming


@pytest.mark.parametrize("mode", ["raw", "legacy", "curses"])
@pytest.mark.parametrize("command", ["/ctx.btw note", "/ctx.btw-all note", "/git status", "/send hello", "/control ping", "/help", "!git status"])
@pytest.mark.parametrize("alive", [False, True])
@pytest.mark.parametrize("log_kind", ["session", "task"])
def test_commands_remain_until_explicit_quit(tmp_path, mode, command, alive, log_kind):
    """Live, finished task and exited session logs stay open after commands."""
    path = tmp_path / f"s1.123.{log_kind}.stdout"
    path.write_text("existing log\n", encoding="utf-8")
    previous_running = state.running
    state.running = True
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(streaming, "_is_session_alive", return_value=alive))
            handle = stack.enter_context(patch.object(streaming, "_handle_stream_command"))
            shell = stack.enter_context(patch.object(streaming, "execute_shell_command"))
            if mode == "curses":
                handler = streaming._build_stream_command_handler(
                    MagicMock(), str(tmp_path), [], "s1", str(path), 123, 456
                )
                assert handler(command) is True
                assert handler("q") is False
                assert handler("quit") is False
            else:
                stack.enter_context(patch.object(streaming, "_load_runtime_history", return_value=[]))
                stack.enter_context(patch.object(streaming, "_persist_runtime_command"))
                stack.enter_context(patch.object(streaming, "_tail_file"))
                stack.enter_context(patch.object(streaming.subprocess, "run"))
                stdin = stack.enter_context(patch.object(streaming.sys, "stdin"))
                stdin.isatty.return_value = True
                stdin.fileno.side_effect = OSError("no physical tty")
                stack.enter_context(patch.object(streaming.select, "select", return_value=([stdin], [], [])))
                read = stack.enter_context(patch.object(streaming, "_read_input_line", side_effect=[command, "q"]))
                viewer = streaming._stream_file_raw if mode == "raw" else streaming._stream_file_legacy
                viewer(str(path), str(tmp_path), [], "s1", str(path), default_pid=123, default_session_pid=456)
                assert read.call_count == 2
            if command.startswith("!"):
                shell.assert_called_once_with(command)
                handle.assert_not_called()
            else:
                assert handle.call_args.args[0] == command
                handle.assert_called_once()
    finally:
        state.running = previous_running
