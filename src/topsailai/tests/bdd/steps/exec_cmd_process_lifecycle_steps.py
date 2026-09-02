"""Step definitions for exec_cmd process lifecycle behavior."""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pytest_bdd import parsers, then, when

from topsailai.utils.cmd_tool import exec_cmd
from topsailai.utils.env_tool import resolve_python_interpreter

logger = logging.getLogger("tests.bdd.exec_cmd_process_lifecycle")
PROJECT_TMP = Path(__file__).resolve().parents[3] / ".tmp"
REAL_POPEN = subprocess.Popen


@pytest.fixture
def exec_cmd_lifecycle_ctx():
    """Hold scenario-owned process and filesystem state and clean it afterward."""
    PROJECT_TMP.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="exec-cmd-bdd-", dir=PROJECT_TMP))
    context: dict[str, Any] = {
        "folder": folder,
        "direct_processes": [],
        "recorded_pids": [],
        "exception": None,
        "result": None,
    }
    yield context
    for process in context["direct_processes"]:
        if process.poll() is None:
            _kill_owned_process(process)
    for pid in context["recorded_pids"]:
        if _process_exists(pid):
            os.kill(pid, signal.SIGKILL)
            logger.info("killed leaked BDD child process: pid=[%s]", pid)
    shutil.rmtree(folder)
    logger.info("removed exec_cmd BDD folder: [%s]", folder)


def _kill_owned_process(process: subprocess.Popen) -> None:
    """Kill and reap one exact scenario-owned process or process group."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()
    process.wait(timeout=5)
    logger.info("killed leaked BDD direct process: pid=[%s]", process.pid)


def _process_exists(pid: int) -> bool:
    """Return whether an exact process ID still exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _assert_process_exited(pid: int) -> None:
    """Wait briefly for one exact process ID to disappear."""
    for _ in range(100):
        if not _process_exists(pid):
            return
        time.sleep(0.01)
    pytest.fail(f"process {pid} is still running after exec_cmd timeout cleanup")


def _read_pid(path: Path) -> int:
    """Read a child PID recorded by a scenario command."""
    for _ in range(100):
        if path.exists() and path.read_text(encoding="utf-8").strip():
            return int(path.read_text(encoding="utf-8").strip())
        time.sleep(0.01)
    pytest.fail("timed-out command did not record its child PID")


def _run_with_process_capture(context: dict[str, Any], cmd: str | list[str], **options: Any) -> None:
    """Run exec_cmd while retaining references to every real direct process."""
    def capture_popen(*args: Any, **kwargs: Any) -> subprocess.Popen:
        process = REAL_POPEN(*args, **kwargs)
        context["direct_processes"].append(process)
        return process

    try:
        with patch("topsailai.utils.cmd_tool.subprocess.Popen", side_effect=capture_popen):
            context["result"] = exec_cmd(cmd, **options)
    except Exception as exc:  # noqa: BLE001 - exception identity is an acceptance result
        context["exception"] = exc


@when("exec_cmd lifecycle runs a string command that records a child and exceeds its timeout")
def timeout_string_command(exec_cmd_lifecycle_ctx):
    """Run a shell command whose background child would become orphaned without group cleanup."""
    if os.name != "posix":
        pytest.skip("string process-group lifecycle scenario currently requires POSIX shell semantics")
    pid_file = exec_cmd_lifecycle_ctx["folder"] / "string-child.pid"
    command = f"sleep 30 & echo $! > '{pid_file}'; wait"
    _run_with_process_capture(exec_cmd_lifecycle_ctx, command, timeout=0.2)
    exec_cmd_lifecycle_ctx["recorded_pids"].append(_read_pid(pid_file))


@when("exec_cmd lifecycle runs a list command that records a descendant and exceeds its timeout")
def timeout_list_command(exec_cmd_lifecycle_ctx):
    """Run a list command that creates a descendant within the owned process group."""
    if os.name != "posix":
        pytest.skip("list descendant lifecycle scenario currently requires POSIX shell semantics")
    pid_file = exec_cmd_lifecycle_ctx["folder"] / "list-child.pid"
    command = f"sleep 30 & echo $! > '{pid_file}'; wait"
    _run_with_process_capture(exec_cmd_lifecycle_ctx, ["sh", "-c", command], timeout=0.2)
    exec_cmd_lifecycle_ctx["recorded_pids"].append(_read_pid(pid_file))


@when("exec_cmd lifecycle times out a command with all standard pipes open")
def timeout_with_pipes(exec_cmd_lifecycle_ctx):
    """Time out a real command while stdin, stdout, and stderr are piped."""
    command = [resolve_python_interpreter(), "-c", "import time; time.sleep(30)"]
    _run_with_process_capture(
        exec_cmd_lifecycle_ctx,
        command,
        timeout=0.2,
        stdin=subprocess.PIPE,
    )


@when(parsers.parse("exec_cmd lifecycle sends {input_kind} containing lifecycle-input to a child"))
def send_command_input(exec_cmd_lifecycle_ctx, input_kind):
    """Send bytes or UTF-8 text through the public exec_cmd input interfaces."""
    command = [
        resolve_python_interpreter(),
        "-c",
        "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())",
    ]
    options = {"input": b"lifecycle-input"}
    if input_kind == "stdin_text":
        options = {"stdin_text": "lifecycle-input"}
    _run_with_process_capture(exec_cmd_lifecycle_ctx, command, **options)


@when("exec_cmd lifecycle combines input bytes with an explicit stdin pipe")
def combine_input_and_stdin(exec_cmd_lifecycle_ctx):
    """Call the mutually exclusive input interfaces together."""
    _run_with_process_capture(
        exec_cmd_lifecycle_ctx,
        [resolve_python_interpreter(), "-c", "pass"],
        input=b"lifecycle-input",
        stdin=subprocess.PIPE,
    )


@when(
    "exec_cmd lifecycle runs a command that exits 7 with stdout normal-out and stderr normal-err"
)
def run_normal_command(exec_cmd_lifecycle_ctx):
    """Run a non-timeout command that produces both output streams and a nonzero code."""
    command = [
        resolve_python_interpreter(),
        "-c",
        "import sys; print('normal-out'); print('normal-err', file=sys.stderr); raise SystemExit(7)",
    ]
    _run_with_process_capture(exec_cmd_lifecycle_ctx, command)


@then("exec_cmd lifecycle raises TimeoutExpired")
def raises_timeout_expired(exec_cmd_lifecycle_ctx):
    """The timeout remains visible to the caller after cleanup."""
    assert isinstance(exec_cmd_lifecycle_ctx["exception"], subprocess.TimeoutExpired)


@then("exec_cmd lifecycle leaves no recorded child process running")
def no_recorded_process_running(exec_cmd_lifecycle_ctx):
    """Neither the direct command nor its recorded descendant remains alive."""
    assert exec_cmd_lifecycle_ctx["direct_processes"]
    for process in exec_cmd_lifecycle_ctx["direct_processes"]:
        _assert_process_exited(process.pid)
    for pid in exec_cmd_lifecycle_ctx["recorded_pids"]:
        _assert_process_exited(pid)


@then("exec_cmd lifecycle has reaped the direct process")
def direct_process_reaped(exec_cmd_lifecycle_ctx):
    """The direct Popen child has a terminal return code and no live PID."""
    process = exec_cmd_lifecycle_ctx["direct_processes"][0]
    assert process.returncode is not None
    _assert_process_exited(process.pid)


@then("exec_cmd lifecycle has closed all standard pipes")
def standard_pipes_closed(exec_cmd_lifecycle_ctx):
    """The final communicate call closes every configured standard pipe."""
    process = exec_cmd_lifecycle_ctx["direct_processes"][0]
    assert process.stdin is not None and process.stdin.closed
    assert process.stdout is not None and process.stdout.closed
    assert process.stderr is not None and process.stderr.closed


@then(parsers.parse("exec_cmd lifecycle returns code {code:d} stdout {stdout} and empty stderr"))
def returns_with_empty_stderr(exec_cmd_lifecycle_ctx, code, stdout):
    """The command returns the expected stdin round-trip result."""
    assert exec_cmd_lifecycle_ctx["exception"] is None
    assert exec_cmd_lifecycle_ctx["result"] == (code, stdout, "")


@then("exec_cmd lifecycle raises the input and stdin conflict error")
def raises_input_stdin_conflict(exec_cmd_lifecycle_ctx):
    """Mutually exclusive stdin arguments fail before a process is created."""
    error = exec_cmd_lifecycle_ctx["exception"]
    assert isinstance(error, ValueError)
    assert str(error) == "stdin and input arguments may not both be used."
    assert exec_cmd_lifecycle_ctx["direct_processes"] == []


@then(
    parsers.parse(
        "exec_cmd lifecycle returns code {code:d} stdout {stdout} and stderr {stderr}"
    )
)
def returns_with_stderr(exec_cmd_lifecycle_ctx, code, stdout, stderr):
    """Normal execution preserves all three public result fields."""
    assert exec_cmd_lifecycle_ctx["exception"] is None
    result_code, result_stdout, result_stderr = exec_cmd_lifecycle_ctx["result"]
    assert result_code == code
    assert result_stdout.strip() == stdout
    assert result_stderr.strip() == stderr
