"""
Manual test for tool_approval input flow.

Run this script from a shell to verify that the approval prompt reaches the
registered ``agent_runtime_input_with_timeout`` function (set via thread-local
storage by ``workspace/agent/hooks/pre_run_input.py``). When no runtime input
function is registered, the transport falls back to stdin.

Usage:
    # Default: uses registered runtime input if available, otherwise stdin
    python tests/manual/test_tool_approval_manual_input.py

    # Force stdin fallback even when a runtime input function is registered
    python tests/manual/test_tool_approval_manual_input.py --stdin

    # Register a mock runtime input function that reads from stdin
    python tests/manual/test_tool_approval_manual_input.py --register-mock

    # Real named-pipe simulation: a writer thread sends approve/deny automatically
    python tests/manual/test_tool_approval_manual_input.py --pipe
    python tests/manual/test_tool_approval_manual_input.py --pipe --decision deny

    # Fully automated real tool_approval decorator + real session pipe path.
    # A writer thread sends a normal message (with EOF marker) and then the
    # approval decision through the same session pipe used by the workspace
    # input utilities.
    python tests/manual/test_tool_approval_manual_input.py --pipe-manual
    python tests/manual/test_tool_approval_manual_input.py --pipe-manual --decision deny

    # Interactive real tool_approval decorator + real session pipe path.
    # The test sends the normal message automatically, then prints the FIFO
    # path and a ready-to-copy command. Run the printed command in a second
    # terminal to send approve/deny manually.
    python tests/manual/test_tool_approval_manual_input.py --pipe-interactive

When the prompt appears in default/stdin/mock mode, type one of:
    approve / yes / y   -> the tool call is approved
    deny / no / n       -> the tool call is denied
"""

from __future__ import annotations

import argparse
import atexit
import os
import sys
import threading
import time

# Ensure the project source is on sys.path when run directly.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Force TOPSAILAI_HOME to the project .tmp directory so that the real workspace
# pipe utilities create session pipes under .tmp/workspace/task.
os.environ["TOPSAILAI_HOME"] = os.path.join(PROJECT_ROOT, ".tmp")

from topsailai.ai_base.tool_approval.decorator import with_tool_approval
from topsailai.ai_base.tool_approval.exceptions import ToolApprovalDeniedError
from topsailai.ai_base.tool_approval.instance import ToolApprovalInstance
from topsailai.ai_base.tool_approval.transport import LocalApprovalTransport
from topsailai.utils import env_tool
from topsailai.utils.input_tool import _clear_leftover_buffer, input_from_pipe
from topsailai.utils.thread_local_tool import (
    get_agent_runtime_input_with_timeout,
    set_agent_runtime_input_with_timeout,
)
from topsailai.workspace.input_tool import _build_pipe_path, input_from_pipe_session

# Approval rule: require approval for our dummy tool. The timeout placeholder is
# filled in at runtime from the --timeout argument.
APPROVAL_RULES_JSON_TEMPLATE = """[
    {{
        "name": "manual test rule",
        "match": "manual_test_tool",
        "mode": "require",
        "timeout": {timeout},
        "policy": "deny",
        "priority": 0
    }}
]"""


# Track the FIFO created by this process so atexit can remove it even if the
# user interrupts the script with Ctrl-C.
_CREATED_PIPE_PATH: str | None = None


def _cleanup_pipe() -> None:
    """Remove the FIFO created by this process, if it still exists."""
    global _CREATED_PIPE_PATH
    path = _CREATED_PIPE_PATH
    if path and os.path.exists(path):
        try:
            os.unlink(path)
            print(f"\n[INFO] Cleaned up FIFO: {path}")
        except OSError as exc:
            print(f"\n[WARN] Failed to clean up FIFO {path}: {exc}")


atexit.register(_cleanup_pipe)


def _mock_runtime_input(prompt: str, timeout: float | None = None) -> str:
    """A runtime input function that prints what it received and reads from stdin."""
    print("\n[RUNTIME INPUT WRAPPER CALLED]")
    print(f"  prompt length: {len(prompt)}")
    print(f"  timeout: {timeout}")
    # The real workspace wrapper would read from the session pipe. For this
    # manual test we read from stdin so a human can still type the decision.
    return input("[via runtime input] type approve/deny: ")


def _build_pipe_input_func(pipe_path: str):
    """Build a real agent_runtime_input_with_timeout function that reads from a FIFO.

    This delegates to :func:`topsailai.utils.input_tool.input_from_pipe` so the
    manual test exercises the same pipe-reading path used by the workspace.
    """

    def _pipe_input(tips: str = "", timeout: float | None = None) -> str:
        """Read a decision from the named pipe, with timeout support."""
        print(f"\n[PIPE INPUT] reading from {pipe_path}")
        print(f"  prompt length: {len(tips)}")
        print(f"  timeout: {timeout}")
        return input_from_pipe(
            pipe_path,
            single_line=True,
            timeout=timeout,
            prompt=tips,
            raise_eof_error=False,
            cleanup_pipe=False,
        )

    return _pipe_input


def _write_to_pipe_after_delay(pipe_path: str, decision: str, delay: float = 0.5) -> None:
    """Write a decision followed by EOF marker to the pipe after a short delay."""
    time.sleep(delay)

    # Wait for the FIFO to be created by input_from_pipe. The reader creates
    # the FIFO and opens it for reading just before it starts selecting.
    deadline = time.time() + 5.0
    while not os.path.exists(pipe_path) and time.time() < deadline:
        time.sleep(0.05)

    # Open for writing. This unblocks the reader's os.open.
    fd = os.open(pipe_path, os.O_WRONLY)
    try:
        payload = f"{decision}\nEOF\n".encode("utf-8")
        os.write(fd, payload)
    finally:
        os.close(fd)


def _make_pipe_path() -> str:
    """Return a deterministic FIFO path under the project workspace .tmp directory."""
    pipe_dir = os.path.join(PROJECT_ROOT, ".tmp")
    os.makedirs(pipe_dir, exist_ok=True)
    return os.path.join(pipe_dir, f"test_tool_approval_manual_input.{os.getpid()}.pipe")


def _prepare_pipe_mode(decision: str) -> str:
    """Create a FIFO and register a real pipe-based runtime input function."""
    global _CREATED_PIPE_PATH
    pipe_path = _make_pipe_path()
    _CREATED_PIPE_PATH = pipe_path

    # Remove any stale FIFO so input_from_pipe can create a fresh one.
    if os.path.exists(pipe_path):
        os.unlink(pipe_path)

    input_func = _build_pipe_input_func(pipe_path)
    set_agent_runtime_input_with_timeout(input_func)

    # Start the writer before any reader opens the pipe.
    writer = threading.Thread(
        target=_write_to_pipe_after_delay,
        args=(pipe_path, decision),
        daemon=True,
        name="approval-pipe-writer",
    )
    writer.start()

    return pipe_path


def _write_to_pipe(pipe_path: str, message: str, timeout: float = 10.0) -> None:
    """Write *message* followed by an EOF marker to *pipe_path*.

    Blocks until the FIFO exists so the reader does not need to coordinate
    creation order.
    """
    deadline = time.time() + timeout
    while not os.path.exists(pipe_path) and time.time() < deadline:
        time.sleep(0.05)
    if not os.path.exists(pipe_path):
        raise TimeoutError(f"Pipe {pipe_path} was not created in time")
    with open(pipe_path, "w", encoding="utf-8") as f:
        f.write(f"{message}\nEOF\n")


def _real_runtime_input_with_timeout(tips: str = "", timeout: float | None = None) -> str:
    """Real agent-runtime input function that reads from the session pipe.

    This mirrors the function registered by
    ``workspace/agent/hooks/pre_run_input.py::pre_run_set_agent_runtime_input``.
    """
    session_id = env_tool.get_session_id()
    pipe_path = _build_pipe_path(session_id)
    _clear_leftover_buffer(pipe_path)
    return input_from_pipe_session(
        session_id=session_id,
        single_line=True,
        timeout=timeout,
        prompt=tips,
        raise_eof_error=False,
    )


def _setup_session_pipe(session_id: str) -> str:
    """Set SESSION_ID, register the real runtime input, reset transport, and prepare the pipe path."""
    os.environ["SESSION_ID"] = session_id
    set_agent_runtime_input_with_timeout(_real_runtime_input_with_timeout)
    LocalApprovalTransport.reset_instance()

    pipe_path = _build_pipe_path(session_id)
    global _CREATED_PIPE_PATH
    _CREATED_PIPE_PATH = pipe_path

    os.makedirs(os.path.dirname(pipe_path), exist_ok=True)
    if os.path.exists(pipe_path):
        os.unlink(pipe_path)

    return pipe_path


def _consume_normal_message(pipe_path: str, session_id: str) -> str:
    """Send and consume a normal user message through the session pipe."""
    normal_msg_consumed = threading.Event()

    def writer() -> None:
        time.sleep(0.2)
        _write_to_pipe(pipe_path, "hello agent")
        normal_msg_consumed.set()

    writer_thread = threading.Thread(target=writer, daemon=True, name="pipe-normal-msg-writer")
    writer_thread.start()

    normal_msg = input_from_pipe_session(
        session_id=session_id,
        single_line=True,
        timeout=10,
        raise_eof_error=False,
    )
    writer_thread.join(timeout=5)
    return normal_msg


def _run_pipe_manual_mode(decision: str, timeout: float) -> int:
    """Run the real tool_approval decorator against a real session pipe.

    Simulates the actual agent code path:

      1. A normal user message is sent through the session pipe and consumed.
         This leaves an EOF marker in the pipe-read buffer, reproducing the
         state that previously broke approval input.
      2. A tool decorated with ``with_tool_approval`` is triggered. Approval
         reads from the same session pipe via the real workspace runtime
         input function.
      3. The decision (approve/deny) is sent through the same pipe.
    """
    session_id = f"manual-test-{os.getpid()}"
    pipe_path = _setup_session_pipe(session_id)

    normal_msg = _consume_normal_message(pipe_path, session_id)
    print(f"\n[INFO] Normal message consumed: {normal_msg!r}")

    @with_tool_approval
    def exec_manual_test_tool(tool_func, args, tool_name=None):
        return tool_func(**args)

    def dummy_tool():
        return "TOOL_EXECUTED"

    print("[INFO] Triggering decorated tool; approval request will read from the session pipe.")

    approval_request_sent = threading.Event()

    def decision_writer() -> None:
        approval_request_sent.wait(timeout=10)
        # Small delay so the approval reader has opened the pipe.
        time.sleep(0.2)
        _write_to_pipe(pipe_path, decision)

    writer_thread = threading.Thread(target=decision_writer, daemon=True, name="pipe-manual-writer")
    writer_thread.start()

    expect_approved = decision in ("approve", "yes", "y")
    approval_request_sent.set()

    try:
        result = exec_manual_test_tool(dummy_tool, {}, tool_name="manual_test_tool")
    except ToolApprovalDeniedError as exc:
        writer_thread.join(timeout=5)
        if expect_approved:
            print(f"\n[FAIL] Tool was denied unexpectedly: {exc}")
            return 1
        print("\n[PASS] Tool was denied as expected.")
        return 0

    writer_thread.join(timeout=5)

    if not expect_approved:
        print(f"\n[FAIL] Expected denial but tool executed and returned: {result!r}")
        return 1

    if result == "TOOL_EXECUTED":
        print(f"\n[PASS] Tool was approved and returned: {result!r}")
        return 0

    print(f"\n[FAIL] Tool returned unexpected value: {result!r}")
    return 1


def _run_pipe_interactive_mode(timeout: float) -> int:
    """Interactive mode: the user sends approve/deny from a second terminal.

    The test sets up a real session pipe, sends and consumes a normal message
    automatically, then triggers a real ``with_tool_approval`` decorated tool.
    It prints the FIFO path and a ready-to-copy ``printf`` command. The human
    runs that command in another terminal to approve or deny the request.
    """
    session_id = f"manual-test-{os.getpid()}"
    pipe_path = _setup_session_pipe(session_id)

    print(f"\n[INFO] Session pipe: {pipe_path}")
    print("[INFO] Send a normal message with:")
    print(f"  printf 'hello agent\\nEOF\\n' > {pipe_path}")

    normal_msg = _consume_normal_message(pipe_path, session_id)
    print(f"\n[INFO] Normal message consumed: {normal_msg!r}")

    @with_tool_approval
    def exec_manual_test_tool(tool_func, args, tool_name=None):
        return tool_func(**args)

    def dummy_tool():
        return "TOOL_EXECUTED"

    print("[INFO] Triggering decorated tool; approval request will read from the session pipe.")
    # Give the transport's input reader a moment to open the FIFO for reading.
    time.sleep(0.5)
    print("\n[INFO] To approve or deny, run in another terminal:")
    print(f"  printf 'approve\\nEOF\\n' > {pipe_path}")
    print(f"  printf 'deny\\nEOF\\n' > {pipe_path}")
    print("[INFO] Waiting for your decision...\n")

    try:
        result = exec_manual_test_tool(dummy_tool, {}, tool_name="manual_test_tool")
    except ToolApprovalDeniedError:
        print("\n[RESULT] Tool was denied.")
        return 0

    if result == "TOOL_EXECUTED":
        print(f"\n[RESULT] Tool was approved and returned: {result!r}")
        return 0

    print(f"\n[RESULT] Tool returned unexpected value: {result!r}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual test for tool approval input")
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Force stdin fallback even if a runtime input function is registered",
    )
    parser.add_argument(
        "--register-mock",
        action="store_true",
        help="Register a mock runtime input function to simulate pipe-based input",
    )
    parser.add_argument(
        "--pipe",
        action="store_true",
        help="Use a real named pipe (FIFO) and an automatic writer thread",
    )
    parser.add_argument(
        "--pipe-manual",
        action="store_true",
        help=(
            "Use the real with_tool_approval decorator and the real session pipe "
            "path. A writer thread sends a normal message and then the decision."
        ),
    )
    parser.add_argument(
        "--pipe-interactive",
        action="store_true",
        help=(
            "Use the real with_tool_approval decorator and the real session pipe "
            "path. The test sends the normal message automatically; you send "
            "approve/deny from a second terminal."
        ),
    )
    parser.add_argument(
        "--decision",
        choices=["approve", "deny"],
        default="approve",
        help="Decision written to the pipe in --pipe/--pipe-manual mode (default: approve)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Approval timeout in seconds (default: 300)",
    )
    args = parser.parse_args()

    exclusive = [args.pipe, args.pipe_manual, args.pipe_interactive]
    if sum(exclusive) > 1:
        parser.error("--pipe, --pipe-manual, and --pipe-interactive are mutually exclusive")

    # Enable tool approval.
    os.environ["TOPSAILAI_TOOL_APPROVAL_ENABLED"] = "1"
    os.environ["TOPSAILAI_TOOL_APPROVAL_RULES"] = APPROVAL_RULES_JSON_TEMPLATE.format(
        timeout=args.timeout
    )
    os.environ["TOPSAILAI_TOOL_APPROVAL_DEFAULT_TIMEOUT"] = str(args.timeout)
    os.environ["TOPSAILAI_TOOL_APPROVAL_DEFAULT_POLICY"] = "deny"

    # Reset the singleton so this script gets a fresh transport.
    LocalApprovalTransport.reset_instance()

    if args.pipe_manual:
        return _run_pipe_manual_mode(args.decision, args.timeout)

    if args.pipe_interactive:
        return _run_pipe_interactive_mode(args.timeout)

    pipe_path: str | None = None

    if args.pipe:
        pipe_path = _prepare_pipe_mode(args.decision)
        print(f"[INFO] Created FIFO: {pipe_path}")
        print(f"[INFO] Writer thread will send '{args.decision}' in ~0.5s.")
    elif args.register_mock and not args.stdin:
        set_agent_runtime_input_with_timeout(_mock_runtime_input)
        print("[INFO] Registered mock agent_runtime_input_with_timeout")

    registered = get_agent_runtime_input_with_timeout()
    if registered is not None:
        print("[INFO] A runtime input function is registered; approval will use it.")
    else:
        print("[INFO] No runtime input function registered; approval will fall back to stdin.")

    transport = LocalApprovalTransport.get_instance()
    instance = ToolApprovalInstance(
        tool_name="manual_test_tool",
        tool_args={"action": "demo"},
        transport=transport,
    )

    print("\nStarting approval request...")
    if args.pipe:
        print("The writer thread will send the decision automatically.\n")
    else:
        print("The script will block until you type approve/deny.\n")

    transport.send_request(instance)
    status = instance.wait_for_decision(timeout=instance.timeout, policy=instance.policy)

    print(f"\nFinal approval status: {status}")
    print(f"Decision by: {instance.decision_by}")
    print(f"Decision at: {instance.decision_at}")

    _cleanup_pipe()

    if status == ToolApprovalInstance.STATUS_APPROVED:
        print("Tool call would be executed.")
        return 0
    print("Tool call was NOT approved.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
