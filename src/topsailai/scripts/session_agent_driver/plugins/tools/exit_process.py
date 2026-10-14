"""
exit_process plugin tool: request the driver script to exit its polling loop.

The analysis agent calls this tool when it determines that the target session
has achieved its final goal. The tool sets a shared threading.Event; the main
script checks ``is_exit_requested()`` after each analysis run and exits.
"""

import threading

from ai_base.agent_types.exception import AgentEndProcess

# Shared exit flag between the plugin module and the main script.
_EXIT_EVENT = threading.Event()
_EXIT_GUARD = None


def set_exit_guard(guard):
    """Bind a fresh whole-session completion check during analysis."""
    global _EXIT_GUARD
    _EXIT_GUARD = guard


def exit_process(session_id: str | None = None) -> str:
    """Request the driver script to exit.

    Sets the shared exit flag. The main script checks ``is_exit_requested()``
    after each analysis run and terminates its polling loop.

    Args:
        session_id: Optional target session identifier, kept for traceability.

    Returns:
        A short confirmation string.
    """
    if _EXIT_GUARD is not None and not _EXIT_GUARD():
        raise AgentEndProcess("exit refused: child tasks remain alive")
    _EXIT_EVENT.set()
    return "exit requested"


def is_exit_requested() -> bool:
    """Return whether the driver script should exit."""
    return _EXIT_EVENT.is_set()


def reset_exit_flag() -> None:
    """Clear the exit flag (used by tests and by the main script on startup)."""
    _EXIT_EVENT.clear()


# name: func
TOOLS = {
    "exit_process": exit_process,
}

TOOLS_INFO = {
    "exit_process": {
        "type": "function",
        "function": {
            "name": "exit_process",
            "description": (
                "Request the driver script to exit its polling loop. Call this "
                "when the target session has achieved its final goal and no "
                "further input is needed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": (
                            "Optional target session identifier for traceability."
                        ),
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
}
