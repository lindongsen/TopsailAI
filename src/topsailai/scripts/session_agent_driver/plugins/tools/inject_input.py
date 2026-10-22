"""
inject_input plugin tool: inject suggested input content into the target session.

The analysis agent calls this tool to send input to the target session through
the session FIFO pipe (equivalent to ``topsailai runtime send``).

Failure semantics (user-confirmed round 7): when injection fails, this tool
raises ``AgentEndProcess`` so the analysis agent shuts down completely and the
driver script continues its polling loop.
"""

from pathlib import Path

from driver_targets import send_task_input

from ai_base.agent_types.exception import AgentEndProcess
from cli_topsailai.paths import get_topsailai_home
from cli_topsailai.runtime_operations import RuntimeRequest, execute_runtime_request

# Default injection timeout in seconds.
_INJECT_TIMEOUT = 5.0


def _task_dir() -> Path:
    """Return the task directory where session pipes and logs live."""
    return Path(get_topsailai_home()) / "workspace" / "task"


def _normalize_injected_content(content: str) -> str:
    """Replace CRLF, CR, and LF separators with semicolons."""
    return content.replace("\r\n", ";").replace("\r", ";").replace("\n", ";")


_INPUT_GUARD = None
_INPUT_DELIVERED = None


def set_input_guard(guard, delivered=None):
    """Bind a single admitted analysis to its original input owner."""
    global _INPUT_GUARD, _INPUT_DELIVERED
    _INPUT_GUARD = guard
    _INPUT_DELIVERED = delivered


def inject_input(session_id: str, content: str, pid: int | None = None) -> str:
    """Inject input content into the target session.

    Sends *content* to the session FIFO pipe (message plus EOF line), which is
    equivalent to ``topsailai runtime send -s {session_id} -m {content}``.

    Args:
        session_id: Target session identifier.
        content: Input text to inject into the target session.
        pid: Optional target process PID. When omitted, the single living
            process of the session is resolved automatically.

    Returns:
        A short confirmation string when the injection is delivered.

    Raises:
        AgentEndProcess: When injection fails (pipe closed, timeout, target
            exited, or any transport error). This aborts the analysis agent
            completely so the driver script can continue polling.
    """
    if not isinstance(session_id, str) or not session_id.strip():
        raise AgentEndProcess("inject_input failed: invalid session_id")
    if not isinstance(content, str) or not content.strip():
        raise AgentEndProcess("inject_input failed: content must be nonempty text")
    content = _normalize_injected_content(content)
    try:
        if _INPUT_GUARD is not None and not _INPUT_GUARD(session_id.strip(), pid):
            raise AgentEndProcess("inject_input rejected: analysis input owner changed")
        if pid is not None and send_task_input(
            _task_dir(), session_id.strip(), pid, content, timeout=_INJECT_TIMEOUT
        ):
            if _INPUT_DELIVERED is not None:
                _INPUT_DELIVERED()
            return f"input injected to session {session_id} pid {pid}"
        result = execute_runtime_request(
            RuntimeRequest(action="send", message=content, timeout=_INJECT_TIMEOUT),
            _task_dir(),
            session_id=session_id.strip(),
            pid=pid,
        )
    except AgentEndProcess:
        raise
    except Exception as error:  # noqa: BLE001 - any failure aborts the agent
        raise AgentEndProcess(
            f"inject_input failed for session {session_id}: {error}"
        ) from error
    if not result.ok:
        raise AgentEndProcess(
            f"inject_input failed for session {session_id}: "
            f"error_code={result.error_code}, message={result.message}"
        )
    if _INPUT_DELIVERED is not None:
        _INPUT_DELIVERED()
    return f"input injected to session {session_id}"


# name: func
TOOLS = {
    "inject_input": inject_input,
}

TOOLS_INFO = {
    "inject_input": {
        "type": "function",
        "function": {
            "name": "inject_input",
            "description": (
                "Inject suggested input content into the target session so the "
                "target agent can continue executing. Use this when the session "
                "is waiting for input and you have decided what it should receive."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Target session identifier.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Input text to inject into the target session.",
                    },
                    "pid": {
                        "type": "integer",
                        "description": (
                            "Optional target process PID. Omit when the session "
                            "has a single living process."
                        ),
                    },
                },
                "required": ["session_id", "content"],
                "additionalProperties": False,
            },
        },
    },
}
