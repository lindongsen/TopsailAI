"""Gate and deliver a graceful agent exit for one verified workspace target.

Author: DawsonLin

A graceful shutdown asks the agent to leave on its own instead of signalling it.
That is only safe when two independently observed facts hold at the same moment:

* the session lock is ``idle``, so no task currently holds the session, and
* the agent state is ``input``, so the process is alive and waiting for input.

The two facts come from different authorities and neither implies the other. A
session can be ``idle`` while its process is still running, and a process can be
waiting for input while a task holds the session. This module therefore reads
both and refuses unless both agree.

Nothing here re-derives either fact. The lock state comes from the existing
``topsailai_session_status`` command through
:func:`cli_topsailai.workspace_session_status.collect_workspace_session_status`,
and the agent state comes from the existing
:func:`cli_topsailai.formatting.enrich_workspace_rows`. The exit message is
delivered through the existing FIFO transport in
:func:`cli_topsailai.runtime_operations.execute_runtime_request`, so the framing,
the endpoint identity check and the process-group-safe timeout are the ones this
project already fixed and tested.

``/exit`` needs no new handler. ``utils/instruction_tool.py`` lists it in
``DESCRIPTION_EXIT_SET`` and ``hook_message`` calls ``sys.exit(0)`` for every
member, and the agent's input path routes each line through ``hook_message``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

#: The exit spelling the agent already understands. It is one member of the
#: existing ``DESCRIPTION_EXIT_SET``, so no new command is introduced.
GRACEFUL_EXIT_MESSAGE = "/exit"

#: The lock state that means no task holds the session.
SESSION_IDLE = "idle"

#: The agent state that means the process is alive and waiting for input.
AGENT_WAITING = "input"


class GracefulRefusal(Exception):
    """Classify why a graceful shutdown was refused before any delivery."""

    def __init__(self, error_code: str, message: str):
        """Keep the refusal category separate from its diagnostic text."""
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def _refuse(error_code: str, message: str) -> GracefulRefusal:
    """Build one refusal with a stable code and a human-readable reason."""
    return GracefulRefusal(error_code, message)


def _session_state(record: Optional[Dict[str, Any]]) -> str:
    """Extract the lock state, refusing when it was not observed.

    A missing record, a ``null`` status, or a collector error all mean the lock
    state is unknown. Unknown is not ``idle``: treating it as satisfied would
    deliver ``/exit`` to a session that may be mid-task.
    """
    if not isinstance(record, dict):
        raise _refuse(
            "graceful_status_unavailable",
            "The session lock state was not observed",
        )
    status = record.get("status")
    if status is None:
        detail = record.get("message") or record.get("error_code")
        raise _refuse(
            "graceful_status_unavailable",
            f"The session lock state is unavailable: {detail or 'no status'}",
        )
    if status != SESSION_IDLE:
        raise _refuse(
            "graceful_session_busy",
            f"The session lock state is {status!r}, not {SESSION_IDLE!r}",
        )
    return status


def _agent_state(row: Dict[str, Any]) -> str:
    """Extract the agent state, refusing when it is not waiting for input.

    ``enrich_workspace_rows`` writes ``workspace_status`` as ``input`` only when
    the process is alive and holds its session pipe, ``running`` when it is alive
    without the pipe, and ``idle`` when no process is visible. Only ``input``
    means the agent is blocked on its input channel, which is the one state where
    a delivered line is actually consumed.
    """
    status = row.get("workspace_status")
    if not isinstance(status, str) or not status:
        raise _refuse(
            "graceful_status_unavailable",
            "The agent state was not observed",
        )
    if status != AGENT_WAITING:
        raise _refuse(
            "graceful_agent_not_waiting",
            f"The agent state is {status!r}, not {AGENT_WAITING!r}",
        )
    return status


def observe_graceful_states(
    row: Dict[str, Any],
    home: str,
    *,
    enrich: Optional[Callable[..., None]] = None,
    collect: Optional[Callable[..., Dict[str, Dict[str, Any]]]] = None,
) -> Dict[str, str]:
    """Observe both preconditions for one row and refuse unless both hold.

    Only the target row is passed to each collector, so one invocation runs at
    most one child process. Passing every discovered row would query every
    session in the task directory to answer a question about one session.

    Args:
        row: The exact discovered row the kill target was resolved from.
        home: The resolved ``TOPSAILAI_HOME`` directory.
        enrich: Optional seam replacing the agent-state collector.
        collect: Optional seam replacing the lock-state collector.

    Returns:
        ``{"session_status": "idle", "agent_status": "input"}`` when both
        preconditions hold.

    Raises:
        GracefulRefusal: When either precondition does not hold or cannot be
            observed. Nothing has been delivered at that point.
    """
    if enrich is None:
        from cli_topsailai.formatting import enrich_workspace_rows

        enrich = enrich_workspace_rows
    if collect is None:
        from cli_topsailai.workspace_session_status import (
            collect_workspace_session_status,
        )

        collect = collect_workspace_session_status

    # The agent state is refreshed on this row only. The collector mutates the
    # row in place, which is why the caller passes the discovered row rather
    # than a copy: the same object is the one the target was resolved from.
    enrich([row], home)
    agent_status = _agent_state(row)

    filename = row.get("filename")
    if not isinstance(filename, str) or not filename:
        raise _refuse(
            "graceful_status_unavailable",
            "The target row carries no filename to key the lock state by",
        )
    answers = collect([row])
    session_status = _session_state(answers.get(filename))
    return {"session_status": session_status, "agent_status": agent_status}


def deliver_graceful_exit(
    task_dir: str,
    session_id: str,
    pid: int,
    *,
    execute: Optional[Callable[..., Any]] = None,
) -> Any:
    """Deliver ``/exit`` through the existing FIFO transport.

    The transport resolves and revalidates the target itself, so the endpoint is
    derived from the same verified session and PID the caller already proved.
    Delivery is not exit: a written line proves the bytes reached the pipe, not
    that the agent consumed them or terminated.

    Args:
        task_dir: The task directory holding the session pipe. It is normalized
            to an absolute ``Path`` here because the transport requires one and
            rejects a plain string as a usage error before resolving a target.
        session_id: The verified session identity.
        pid: The verified process ID.
        execute: Optional seam replacing the runtime executor.

    Returns:
        The executor's result object, whose ``ok`` and ``error_code`` describe
        the delivery outcome.
    """
    from cli_topsailai.runtime_operations import RuntimeRequest

    endpoint_dir = Path(task_dir)
    if not endpoint_dir.is_absolute():
        endpoint_dir = endpoint_dir.absolute()
    # A seam receives the same normalized request the real executor would, so a
    # test cannot pass by delivering a different message.
    request = RuntimeRequest(action="send", message=GRACEFUL_EXIT_MESSAGE)
    if execute is None:
        from cli_topsailai.runtime_operations import execute_runtime_request

        execute = execute_runtime_request
    return execute(request, endpoint_dir, session_id=session_id, pid=pid)
