"""Strict runtime CLI contracts; all delivery is injected or isolated.

Author: DawsonLin
"""

import io
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

from cli_topsailai import runtime_cli as cli
from cli_topsailai.runtime_operations import RuntimeResult


class Input(io.BytesIO):
    """Expose a controllable TTY marker and byte-read evidence."""

    def __init__(self, data=b"", tty=False):
        """Initialize bounded fixture input without using real stdin."""
        super().__init__(data)
        self.tty = tty
        self.calls = []

    def isatty(self):
        """Return the fixture terminal state."""
        return self.tty

    def read(self, size=-1):
        """Record every read size to prove bounded acquisition."""
        self.calls.append(size)
        return super().read(size)


def invoke(argv, **kwargs):
    """Run the CLI with a harmless operation spy and explicit home."""
    executor = kwargs.pop("executor", Mock(return_value=RuntimeResult(
        True, 0, "send", "s", 123, "pipe_written")))
    code = cli.run_runtime_cli(argv, executor=executor,
                               home_resolver=lambda: "/isolated/home", **kwargs)
    return code, executor


@pytest.mark.parametrize("structured,instruction", [
    (["send", "-m", '  x "quoted"\n雪 $(echo no); /control.stop  '],
     '/send   x "quoted"\n雪 $(echo no); /control.stop  '),
    (["btw", "-m", "\ttext\n "], "/ctx.btw \ttext\n "),
    (["control", "dynamic", "-a", '{"x":"雪", "nested":[1]}'],
     '/control dynamic {"x":"雪", "nested":[1]}'),
    (["control", "dynamic", "-a", '{}'], '/control.dynamic'),
])
def test_equivalent_syntax(structured, instruction, capsys):
    """Both forms preserve body/payload and dispatch exactly once."""
    _, left = invoke(["-s", "s", "--timeout", "3", *structured])
    _, right = invoke(["-i", instruction, "--timeout", "3", "-s", "s"])
    assert left.call_args == right.call_args
    left.assert_called_once()
    right.assert_called_once()
    assert left.call_args.args[1] == Path("/isolated/home/workspace/task")


@pytest.mark.parametrize("argv", [
    ["-s", "s", "send", "-p", "123", "-m", "x"],
    ["send", "--session-id", "s", "--pid", "123", "--message", "x"],
    ["--session_id", "s", "--pid=123", "send", "--message=x"],
    ["-s", "s", "send", "-s", "s", "-p", "123", "-m", "x"],
])
def test_common_positions_aliases(argv):
    """Common options survive either side of the structured action."""
    code, executor = invoke(argv)
    assert code == 0
    assert executor.call_args.kwargs == {"session_id": "s", "pid": 123}
    assert executor.call_args.args[0].timeout == 5


@pytest.mark.parametrize("argv", [
    [], ["send", "-m", "x"], ["-s", "s"],
    ["send", "-s", "s", "-m", "x", "-s", "other"],
    ["send", "-s", "s", "-m", "x", "--timeout", "2", "--timeout", "3"],
    ["send", "-s", "s", "-m", "x", "--pid", "a"],
    ["send", "-s", "s", "-m", "x", "--pid", "0"],
    ["send", "-s", "s", "-m", "x", "--timeout", "nan"],
    ["send", "-s", "s", "-m", "x", "--timeout", "inf"],
    ["send", "-s", "s", "-m", "x", "--timeout", "-1"],
    ["send", "-s", "../s", "-m", "x"],
    ["send", "-s", "", "-m", "x"],
    ["send", "-s", "s", "-m", "x", "--unknown"],
    ["send", "-s", "s", "-m", "x", "--time", "3"],
    ["send", "-s", "s", "-m", "x", "extra"],
    ["send", "-s", "s", "-m", "x", "-i", "/send x"],
    ["send", "-s", "s", "-m", "x", "-a", "{}"],
    ["control", "x", "-s", "s", "-m", "x"],
    ["control", "x", "-s", "s", "--stdin"],
    ["control", "x", "-s", "s", "-c", "x"],
    ["control", "-s", "s"],
    ["control", "x", "-s", "s", "-a", "[]"],
    ["control", "x", "-s", "s", "-a", "{"],
    ["control", "x", "-s", "s", "-a", '{"x":NaN}'],
    ["control", "x", "-s", "s", "-a", '{"x":"\\ud800"}'],
    ["-s", "s", "-i", "/control"],
    ["-s", "s", "-i", ""], ["-s", "s", "-i", " /send x"],
    ["-s", "s", "-i", "/ctx.add_msg x"],
    ["-s", "s", "-i", "!echo secret"],
    ["-s", "s", "-i", "/send x", "--stdin"],
    ["-s", "s", "-i", "/send", "-a", "{}"],
    ["btw", "-s", "s"], ["btw", "-s", "s", "-m", "x", "--stdin"],
])
def test_usage_zero_dispatch_and_read(argv, capsys):
    """Malformed syntax produces safe failures without consuming input."""
    stream = Input(b"do not consume")
    code, executor = invoke([*argv, "--json"], stdin=stream)
    assert code == 2
    executor.assert_not_called()
    assert not stream.calls
    output = capsys.readouterr()
    assert not output.err
    result = json.loads(output.out)
    assert result["error_code"] == "usage_error"
    assert not result["delivery_unknown"]


@pytest.mark.parametrize("argv", [
    ["send", "-s", "s", "--stdin"],
    ["btw", "-p", "123", "--stdin"],
    ["-s", "s", "-i", "/send", "--stdin"],
    ["-s", "s", "-i", "/ctx.btw", "--stdin"],
])
def test_stdin_preserves_bytes(argv):
    """Only explicit stdin supplies the preserved UTF-8 body."""
    stream = Input('  雪\n"x"  '.encode())
    code, executor = invoke(argv, stdin=stream)
    assert code == 0
    assert executor.call_args.args[0].message == '  雪\n"x"  '
    assert stream.calls[0] == cli.MESSAGE_LIMIT + 1


@pytest.mark.parametrize("stream", [
    Input(b"x", tty=True), Input(b"\xff"), Input(b" \n"), Input(),
    Input(b"a" * (cli.MESSAGE_LIMIT + 1)), io.StringIO("text"),
])
def test_invalid_stdin(stream):
    """TTY, invalid bytes, empty, oversized and nonbinary input fail."""
    code, executor = invoke(["send", "-s", "s", "--stdin"], stdin=stream)
    assert code == 2
    executor.assert_not_called()


def test_stdin_exact_limit():
    """The exact byte limit is accepted and no unbounded read occurs."""
    stream = Input(b"a" * cli.MESSAGE_LIMIT)
    code, executor = invoke(["send", "-s", "s", "--stdin"], stdin=stream)
    assert code == 0
    assert len(executor.call_args.args[0].message) == cli.MESSAGE_LIMIT
    assert stream.calls == [cli.MESSAGE_LIMIT + 1, 1]


@pytest.mark.parametrize("argv,expected", [
    (["send", "-s", "s", "--message=--json"], "--json"),
    (["send", "-s", "s", "-m", "--json"], None),
    (["send", "-s", "s", "-mraw"], "raw"),
    (["send", "-s", "s", "-m", "tmux"], "tmux"),
])
def test_option_literal_json_detection(argv, expected, capsys):
    """A message option value must never switch JSON output mode."""
    code, executor = invoke(argv)
    output = capsys.readouterr()
    assert not output.out.startswith("{")
    if expected is None:
        assert code == 2
    else:
        assert code == 0
        assert executor.call_args.args[0].message == expected


@pytest.mark.parametrize("action", [None, "send", "btw", "control"])
def test_offline_help(action, monkeypatch, capsys):
    """Each help path bypasses home, stdin, registry, writer and execution."""
    from cli_topsailai import runtime_operations as operations
    fail = Mock(side_effect=AssertionError("must remain offline"))
    monkeypatch.setattr(operations.runtime_control, "get_control_actions", fail)
    monkeypatch.setattr(operations, "write_injection", fail)
    with pytest.raises(SystemExit) as exc:
        cli.run_runtime_cli(([action] if action else []) + ["--help"],
                            executor=fail, home_resolver=fail, stdin=fail)
    assert exc.value.code == 0
    fail.assert_not_called()
    assert "topsailai runtime" in capsys.readouterr().out


@pytest.mark.parametrize("code,error,state", [
    (0, None, "control_acknowledged"), (2, "usage_error", "not_delivered"),
    (3, "ambiguous_target", "not_delivered"), (4, "endpoint_invalid", "not_delivered"),
    (5, "timeout", "delivery_unknown"), (6, "control_rejected", "delivery_unknown"),
])
def test_public_json(code, error, state, capsys):
    """Public JSON keeps evidence but never serializes body or exception."""
    result = RuntimeResult(code == 0, code, "control", "s", 123, state,
                           error, "Runtime operation failed", bytes_written=3,
                           request_id="id", response={"status": "error"},
                           delivery_unknown=code >= 5, cause=RuntimeError("PRIVATE BODY"))
    returned, executor = invoke(["control", "x", "-s", "s", "--json"],
                                executor=Mock(return_value=result))
    output = capsys.readouterr()
    assert returned == code and not output.err
    document = json.loads(output.out)
    assert document["exit_code"] == code and document["request_id"] == "id"
    assert "cause" not in document and "PRIVATE BODY" not in output.out
    executor.assert_called_once()


def test_plain_failure(capsys):
    """Ordinary failures write only safe diagnostics to stderr."""
    invoke(["send", "-s", "s", "-m", "SECRET"],
           executor=Mock(return_value=RuntimeResult(False, 5, "send", error_code="timeout")))
    output = capsys.readouterr()
    assert not output.out and "timeout" in output.err and "SECRET" not in output.err


def test_default_dependencies(monkeypatch, tmp_path, capsys):
    """Default boundary seams resolve home and execute without globals in layers."""
    home, executor = Mock(return_value=str(tmp_path)), Mock(return_value=RuntimeResult(
        True, 0, "send", delivery_state="pipe_written"))
    monkeypatch.setattr(cli, "get_topsailai_home", home)
    monkeypatch.setattr(cli, "execute_runtime_request", executor)
    monkeypatch.setattr(cli.sys, "stdin", Input(b"x"))
    assert cli.run_runtime_cli(["send", "-p", "123", "--stdin"]) == 0
    executor.assert_called_once()
    home.assert_called_once()


def test_real_entry_isolated_failure(tmp_path):
    """The actual shim produces one failure document without a real target."""
    import os
    root = Path(__file__).resolve().parents[3]
    env = dict(os.environ, TOPSAILAI_HOME=str(tmp_path), HOME=str(tmp_path))
    completed = subprocess.run(
        [sys.executable, str(root / "topsailai_cli.py"), "runtime", "send",
         "-s", "nonexistent-fixture", "-m", "secret-body", "--json"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 3
    assert json.loads(completed.stdout)["exit_code"] == 3
    assert "secret-body" not in completed.stdout and not completed.stderr


def test_end_of_options_does_not_activate_json(capsys):
    """Tokens after the option terminator cannot request JSON output."""
    code, executor = invoke(["send", "-s", "s", "-m", "x", "--", "--json"])
    assert code == 2
    executor.assert_not_called()
    output = capsys.readouterr()
    assert not output.out and "usage_error" in output.err


def test_chunked_stdin():
    """Short reads accumulate under one aggregate byte budget."""
    stream = Mock()
    stream.isatty.return_value = False
    stream.buffer.read.side_effect = [b"\xe9", b"\x9b\xaa", b""]
    code, executor = invoke(["btw", "-s", "s", "--stdin"], stdin=stream)
    assert code == 0 and executor.call_args.args[0].message == "雪"
    assert [call.args[0] for call in stream.buffer.read.call_args_list] == [
        cli.MESSAGE_LIMIT + 1, cli.MESSAGE_LIMIT, cli.MESSAGE_LIMIT - 2]


@pytest.mark.parametrize("body", [" ", "\ud800", "a" * (cli.MESSAGE_LIMIT + 1), "x\nEOF\nx"])
def test_real_operation_validation_no_target(body, monkeypatch, capsys):
    """Inline request failures pass through the approved operation validator."""
    from cli_topsailai import runtime_operations as operations
    resolver = Mock(side_effect=AssertionError("no target access"))
    monkeypatch.setattr(operations.runtime_target, "resolve_runtime_target", resolver)
    code = cli.run_runtime_cli(["send", "-s", "s", "--json", "-m", body],
                               home_resolver=lambda: "/isolated/home")
    assert code == 2
    assert json.loads(capsys.readouterr().out)["exit_code"] == 2
    resolver.assert_not_called()


@pytest.mark.parametrize("selector", [".", ".."])
def test_invalid_selector_does_not_read(selector):
    """Invalid lexical targets are rejected before stdin acquisition."""
    stream = Input(b"x")
    code, executor = invoke(["send", "-s", selector, "--stdin"], stdin=stream)
    assert code == 2 and not stream.calls
    executor.assert_not_called()


@pytest.mark.parametrize("boundary", ["isatty", "initial", "partial"])
@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize("action", ["send", "btw"])
def test_stdin_device_failure(boundary, json_mode, action, monkeypatch, capsys):
    """Classify device failure before home, target, registry or delivery access."""
    from cli_topsailai import runtime_operations as operations
    failure = OSError("PRIVATE DEVICE AND BODY")
    stream = Mock()
    stream.isatty.return_value = False
    if boundary == "isatty":
        stream.isatty.side_effect = failure
    else:
        stream.buffer.read.side_effect = ([b"PRIVATE PARTIAL BODY", failure]
                                         if boundary == "partial" else failure)
    downstream = Mock(side_effect=AssertionError("downstream must remain untouched"))
    monkeypatch.setattr(cli, "get_topsailai_home", downstream)
    monkeypatch.setattr(cli, "execute_runtime_request", downstream)
    monkeypatch.setattr(operations.runtime_target, "resolve_runtime_target", downstream)
    monkeypatch.setattr(operations.runtime_control, "get_control_actions", downstream)
    monkeypatch.setattr(operations.runtime_pipe, "send_to_pipe", downstream)
    monkeypatch.setattr(operations.runtime_control, "send_to_control", downstream)
    monkeypatch.setattr(operations, "write_injection", downstream)
    argv = [action, "-s", "fixture", "-p", "123", "--stdin"]
    assert cli.run_runtime_cli(argv + (["--json"] if json_mode else []), stdin=stream) == 5
    downstream.assert_not_called()
    output = capsys.readouterr()
    assert "PRIVATE" not in output.out + output.err
    if json_mode:
        assert not output.err
        document = json.loads(output.out)
        assert document["error_code"] == "input_read_failed"
        assert document["exit_code"] == 5 and not document["ok"]
        assert document["action"] == action
        assert document["session_id"] == "fixture" and document["pid"] == 123
        assert document["delivery_state"] == "not_delivered"
        assert document["delivery_unknown"] is False
        assert document["bytes_written"] is None and "cause" not in document
    else:
        assert not output.out
        assert output.err == "Runtime failed: input_read_failed (exit 5)\n"


@pytest.mark.parametrize("boundary", ["isatty", "initial", "partial"])
@pytest.mark.parametrize("interrupt_type", [KeyboardInterrupt, SystemExit])
def test_stdin_host_interrupt(boundary, interrupt_type, capsys):
    """Propagate the exact host interrupt without output or downstream work."""
    interrupt = interrupt_type("host stop")
    stream = Mock()
    stream.isatty.return_value = False
    if boundary == "isatty":
        stream.isatty.side_effect = interrupt
    else:
        stream.buffer.read.side_effect = ([b"partial", interrupt]
                                         if boundary == "partial" else interrupt)
    downstream = Mock()
    with pytest.raises(interrupt_type) as caught:
        cli.run_runtime_cli(["send", "-s", "fixture", "--stdin", "--json"],
                            stdin=stream, executor=downstream, home_resolver=downstream)
    assert caught.value is interrupt
    downstream.assert_not_called()
    output = capsys.readouterr()
    assert not output.out and not output.err


@pytest.mark.parametrize("argv,count", [
    (["logs", "-s", "s"], 20), (["-n", "1", "logs", "-s", "s"], 1),
    (["logs", "-s", "s", "--lines", "10000"], 10000),
    (["logs", "-s", "s", "-n", "2", "--lines", "2"], 2),
])
def test_logs_normalization(argv, count):
    """Line counts use the strict shared namespace and default only for logs."""
    args = cli.build_parser().parse_intermixed_args(argv)
    request = cli.normalize(args)
    assert request.action == "logs" and request.lines == count


@pytest.mark.parametrize("extra", [
    ["-n", "0"], ["-n", "-1"], ["-n", "10001"], ["-n", "x"],
    ["-n", "1", "--lines", "2"], ["-m", "x"], ["--stdin"],
    ["-a", "{}"], ["-i", "/send x"], ["--timeout", "5"], ["extra"],
])
def test_logs_invalid_offline(extra, capsys):
    """Rejected syntax never resolves home or calls any operation."""
    home, executor = Mock(), Mock()
    assert cli.run_runtime_cli(["logs", "-s", "s", *extra, "--json"],
                               home_resolver=home, executor=executor) == 2
    assert json.loads(capsys.readouterr().out)["error_code"] == "usage_error"
    home.assert_not_called()
    executor.assert_not_called()


@pytest.mark.parametrize("argv", [["send", "-m", "x"], ["btw", "-m", "x"],
                                    ["control", "x"], ["-i", "/send x"]])
def test_lines_reject_delivery(argv):
    """New options never alter existing delivery actions."""
    code, executor = invoke([*argv, "-s", "s", "-n", "2"])
    assert code == 2
    executor.assert_not_called()


@pytest.mark.parametrize("lines,limited,json_mode", [([], False, False),
    (["a", ""], False, False), (["a"], True, False), (["a"], True, True)])
def test_logs_output(lines, limited, json_mode, capsys):
    """Plain output is raw chronological text; JSON retains the envelope."""
    result = RuntimeResult(True, 0, "logs", "s", 123, "log_read",
                           response={"lines": lines, "scan_limited": limited})
    code, _ = invoke(["logs", "-s", "s", *(["--json"] if json_mode else [])],
                     executor=Mock(return_value=result))
    output = capsys.readouterr()
    assert code == 0
    if json_mode:
        assert json.loads(output.out) == cli.public_result(result)
        assert output.err == ""
    else:
        assert output.out == "".join(line + "\n" for line in lines)
        assert bool(output.err) == limited


def test_logs_help_offline(capsys):
    """Help requires neither home nor stdin nor target observation."""
    home, executor = Mock(), Mock()
    with pytest.raises(SystemExit) as error:
        cli.run_runtime_cli(["logs", "--help"], home_resolver=home, executor=executor)
    assert error.value.code == 0 and "--lines" in capsys.readouterr().out
    home.assert_not_called()
    executor.assert_not_called()


def test_logs_json_value_not_output_switch(capsys):
    """A consumed invalid line-count value never enables JSON output."""
    code, executor = invoke(["logs", "-s", "s", "--lines", "--json"])
    assert code == 2
    executor.assert_not_called()
    output = capsys.readouterr()
    assert output.out == "" and "usage_error" in output.err
