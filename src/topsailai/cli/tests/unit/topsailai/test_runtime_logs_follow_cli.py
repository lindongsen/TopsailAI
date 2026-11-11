"""Follow-mode operation and CLI contracts, with injected seams only.

Author: DawsonLin
"""

import json
from functools import partial
from pathlib import Path
from unittest.mock import Mock

import pytest

from cli_topsailai import runtime_cli as cli
from cli_topsailai import runtime_operations as operations
from cli_topsailai.runtime_operations import RuntimeResult


def target(tmp_path, data=b"a\nb\nc\n"):
    """Create one fixture session log without any live process."""
    (tmp_path / "session.x.123.session.stdout").write_bytes(data)
    return tmp_path


def follow_request(count=20):
    """Build one normalized follow request."""
    return operations.RuntimeRequest("logs", lines=count, follow=True)


def run_follow(tmp_path, request=None, **kwargs):
    """Execute a follow with injected output seams and a bounded poll count."""
    emitted, warned = [], []
    kwargs.setdefault("emit", emitted.append)
    kwargs.setdefault("warn", warned.append)
    kwargs.setdefault("sleep", Mock())
    result = operations.execute_log_follow(request or follow_request(), tmp_path,
                                          session_id="session.x", **kwargs)
    return result, emitted, warned


def test_follow_prints_tail_then_appends(tmp_path):
    """The initial tail is printed, then appended records, then the interrupt."""
    folder = target(tmp_path)
    polls = []

    def sleep(_interval):
        """Append one record on the first wait and interrupt on the second."""
        polls.append(_interval)
        if len(polls) == 1:
            with open(folder / "session.x.123.session.stdout", "ab") as writer:
                writer.write(b"d\n")
            return
        raise KeyboardInterrupt()

    emitted = []
    with pytest.raises(KeyboardInterrupt):
        operations.execute_log_follow(follow_request(2), folder, session_id="session.x",
                                      emit=emitted.append, sleep=sleep)
    assert emitted == ["b", "c", "d"]


def test_follow_flushes_pending_on_interrupt(tmp_path):
    """An unterminated record is printed exactly once when the follow ends."""
    folder = target(tmp_path, b"a\n")

    def sleep(_interval):
        """Append an unterminated record and then interrupt."""
        with open(folder / "session.x.123.session.stdout", "ab") as writer:
            writer.write(b"partial")
        raise KeyboardInterrupt()

    emitted = []
    with pytest.raises(KeyboardInterrupt):
        operations.execute_log_follow(follow_request(), folder, session_id="session.x",
                                      emit=emitted.append, sleep=sleep)
    assert emitted == ["a", "partial"]


def test_follow_warns_when_scan_limited(tmp_path, monkeypatch):
    """A scan-limited initial tail warns once on the injected channel."""
    folder = target(tmp_path, b"x" * 64 + b"\n")
    bounded = partial(operations.runtime_logs.LogFollower, chunk_size=8, budget=8)
    monkeypatch.setattr(operations.runtime_logs, "LogFollower", bounded)
    emitted, warned = [], []
    with pytest.raises(KeyboardInterrupt):
        operations.execute_log_follow(follow_request(), folder, session_id="session.x",
                                      emit=emitted.append, warn=warned.append,
                                      sleep=Mock(side_effect=KeyboardInterrupt))
    assert warned == ["Log scan limit reached; output is partial"]


def test_follow_read_failure_is_classified(tmp_path, monkeypatch):
    """A read failure during follow returns the existing classified result."""
    folder = target(tmp_path)
    error = operations.runtime_logs.RuntimeLogError("log_read_failed", "Safe failure")
    monkeypatch.setattr(operations.runtime_logs.LogFollower, "poll",
                        Mock(side_effect=error))
    result, emitted, _ = run_follow(folder)
    assert not result.ok and result.exit_code == 5
    assert result.error_code == "log_read_failed" and result.action == "logs"
    assert result.session_id == "session.x" and result.pid == 123
    assert emitted == ["a", "b", "c"]


def test_follow_missing_target_is_classified(tmp_path):
    """A missing target keeps the offline target classification."""
    result, emitted, _ = run_follow(tmp_path)
    assert not result.ok and result.exit_code == 3
    assert result.error_code == "target_not_found" and not emitted


@pytest.mark.parametrize("runtime_request", [
    operations.RuntimeRequest("logs", lines=20, follow=1),
    operations.RuntimeRequest("logs", lines=20, follow="yes"),
    operations.RuntimeRequest("send", "x", follow=True),
    operations.RuntimeRequest("btw", "x", follow=True),
    operations.RuntimeRequest("control", control_action="test", follow=True),
    operations.RuntimeRequest("logs", lines=0, follow=True),
])
def test_follow_invalid_before_discovery(runtime_request, tmp_path, monkeypatch):
    """Python callers cannot bypass follow validation or cross-action rules."""
    resolver = Mock(side_effect=AssertionError("no discovery"))
    monkeypatch.setattr(operations.runtime_logs, "resolve_log_target", resolver)
    result = operations.execute_log_follow(runtime_request, tmp_path)
    assert result.exit_code == 2 and result.error_code == "usage_error"
    resolver.assert_not_called()


def test_snapshot_unchanged_by_follow_field(tmp_path):
    """A snapshot request still returns one bounded read without following."""
    folder = target(tmp_path)
    result = operations.execute_runtime_request(
        operations.RuntimeRequest("logs", lines=2), folder, session_id="session.x")
    assert result.ok and result.delivery_state == "log_read"
    assert result.response["lines"] == ["b", "c"]


def invoke(argv, **kwargs):
    """Run the CLI with injected follow and snapshot executors."""
    follow_executor = kwargs.pop("follow_executor", Mock(return_value=RuntimeResult(
        True, 0, "logs", "s", 123, "log_read")))
    executor = kwargs.pop("executor", Mock(return_value=RuntimeResult(
        True, 0, "logs", "s", 123, "log_read",
        response={"lines": ["a"], "scan_limited": False})))
    code = cli.run_runtime_cli(argv, executor=executor, follow_executor=follow_executor,
                               home_resolver=lambda: "/isolated/home", **kwargs)
    return code, executor, follow_executor


@pytest.mark.parametrize("argv,count", [
    (["logs", "-s", "s", "-f"], 20),
    (["logs", "-s", "s", "--follow", "-n", "5"], 5),
    (["-f", "logs", "-s", "s", "--lines", "7"], 7),
])
def test_follow_normalization(argv, count):
    """Follow combines with the initial tail count in either option order."""
    args = cli.build_parser().parse_intermixed_args(argv)
    request = cli.normalize(args)
    assert request.action == "logs" and request.follow and request.lines == count


@pytest.mark.parametrize("argv", [
    ["logs", "-s", "s", "-f", "--json"],
    ["send", "-s", "s", "-m", "x", "-f"],
    ["btw", "-s", "s", "-m", "x", "--follow"],
    ["control", "x", "-s", "s", "-f"],
    ["-s", "s", "-i", "/send x", "-f"],
])
def test_follow_rejected_offline(argv, capsys):
    """Follow is rejected with JSON or a delivery action before any access."""
    home, executor, follow_executor = Mock(), Mock(), Mock()
    assert cli.run_runtime_cli([*argv, "--json"], home_resolver=home,
                               executor=executor, follow_executor=follow_executor) == 2
    assert json.loads(capsys.readouterr().out)["error_code"] == "usage_error"
    home.assert_not_called()
    executor.assert_not_called()
    follow_executor.assert_not_called()


def test_follow_task_selector_reaches_resolution(tmp_path, monkeypatch):
    """Follow execution selects task stdout when the request asks for it."""
    task_path = tmp_path / "sessionx.456.work.task.stdout"
    task_path.write_text("task\n")
    resolver = Mock(wraps=operations.runtime_logs.resolve_log_target)
    monkeypatch.setattr(operations.runtime_logs, "resolve_log_target", resolver)
    request = operations.RuntimeRequest("logs", lines=20, follow=True,
                                        is_task=True)
    with pytest.raises(KeyboardInterrupt):
        operations.execute_log_follow(
            request, tmp_path, session_id="sessionx", pid=456,
            emit=Mock(), sleep=Mock(side_effect=KeyboardInterrupt))
    assert resolver.call_args.kwargs["is_task"] is True


def test_follow_dispatches_to_follow_executor(capsys):
    """A follow request uses the follow executor and streams no snapshot lines."""
    code, executor, follow_executor = invoke(["logs", "-s", "s", "-n", "3", "-f"])
    assert code == 0
    executor.assert_not_called()
    follow_executor.assert_called_once()
    request = follow_executor.call_args.args[0]
    assert request.follow and request.lines == 3
    assert follow_executor.call_args.args[1] == Path("/isolated/home/workspace/task")
    assert follow_executor.call_args.kwargs["session_id"] == "s"
    assert capsys.readouterr().out == ""


def test_snapshot_does_not_use_follow_executor(capsys):
    """A snapshot request keeps the unchanged snapshot path and output."""
    code, executor, follow_executor = invoke(["logs", "-s", "s"])
    assert code == 0
    executor.assert_called_once()
    follow_executor.assert_not_called()
    assert capsys.readouterr().out == "a\n"


def test_follow_interrupt_exits_zero(capsys):
    """Ctrl-C during a follow is its normal exit and prints no failure line."""
    code, _, follow_executor = invoke(
        ["logs", "-s", "s", "-f"],
        follow_executor=Mock(side_effect=KeyboardInterrupt()))
    assert code == 0
    follow_executor.assert_called_once()
    output = capsys.readouterr()
    assert output.out == "" and output.err == ""


def test_follow_failure_prints_one_diagnostic(capsys):
    """A classified follow failure prints one safe stderr line."""
    code, _, _ = invoke(["logs", "-s", "s", "-f"], follow_executor=Mock(
        return_value=RuntimeResult(False, 5, "logs", error_code="log_read_failed")))
    assert code == 5
    output = capsys.readouterr()
    assert output.out == "" and "log_read_failed" in output.err


def test_follow_help_lists_option(capsys):
    """Help documents the follow option without touching any seam."""
    home, executor, follow_executor = Mock(), Mock(), Mock()
    with pytest.raises(SystemExit) as error:
        cli.run_runtime_cli(["logs", "--help"], home_resolver=home,
                            executor=executor, follow_executor=follow_executor)
    assert error.value.code == 0
    output = capsys.readouterr().out
    assert "--follow" in output and "-f" in output
    home.assert_not_called()
    executor.assert_not_called()
    follow_executor.assert_not_called()
