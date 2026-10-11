"""Execute one normalized runtime operation without CLI or discovery fallbacks.

Author: DawsonLin
"""

from dataclasses import dataclass
import json
import math
from pathlib import Path

from cli_topsailai import runtime_control, runtime_pipe, runtime_target

MESSAGE_LIMIT = 1024 * 1024


@dataclass
class RuntimeRequest:
    """Describe normalized input; mutable payloads are detached at execution."""

    action: str
    message: str | None = None
    control_action: str | None = None
    payload: dict | None = None
    timeout: float = 5.0


@dataclass
class RuntimeResult:
    """Report delivery boundaries, not final receiver consumption."""

    ok: bool
    exit_code: int
    action: str
    session_id: str | None = None
    pid: int | None = None
    delivery_state: str = "not_delivered"
    error_code: str | None = None
    message: str = ""
    bytes_written: int | None = None
    request_id: str | None = None
    response: dict | None = None
    delivery_unknown: bool = False
    cause: Exception | None = None


def write_injection(path: str, message: str) -> bool:
    """Load only the public append API; it has no hard timeout guarantee."""
    from topsailai.workspace.agent.runtime_message_sources.file import write_message

    return write_message(path, message)


def _usage() -> runtime_target.RuntimeTargetError:
    """Produce a safe diagnostic without echoing untrusted request content."""
    return runtime_target.RuntimeTargetError("usage_error", "Invalid runtime request")


def _validate(request, control_actions):
    """Validate all request-dependent facts before any target enumeration."""
    if not isinstance(request, RuntimeRequest):
        raise _usage()
    if not isinstance(request.action, str) or request.action not in ("send", "btw", "control"):
        raise _usage()
    if type(request.timeout) not in (int, float):
        raise _usage()
    try:
        timeout = float(request.timeout)
    except OverflowError as exc:
        raise _usage() from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise _usage()
    if request.action != "control":
        if request.control_action is not None or request.payload is not None:
            raise _usage()
        if not isinstance(request.message, str) or not request.message.strip():
            raise _usage()
        try:
            size = len(request.message.encode("utf-8"))
        except UnicodeError as exc:
            raise _usage() from exc
        if size > MESSAGE_LIMIT:
            raise _usage()
        if request.action == "send":
            runtime_pipe.format_pipe_payload(request.message)
        return None
    if request.message is not None or not isinstance(request.control_action, str):
        raise _usage()
    if request.payload is not None and not isinstance(request.payload, dict):
        raise _usage()
    try:
        encoded = json.dumps(request.payload if request.payload is not None else {},
                             allow_nan=False, ensure_ascii=False)
        encoded.encode("utf-8")
        payload = json.loads(encoded)
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise _usage() from exc
    if request.control_action == "call_instruction":
        instruction = payload.get("instruction")
        if not isinstance(instruction, str) or not instruction.strip():
            raise _usage()
    if not request.control_action or request.control_action not in control_actions():
        raise _usage()
    return payload


def _failure(action, exc, target=None, *, unknown=False, injection=False):
    """Map structured facts and retain the original failure for inspection."""
    uncertain = unknown or getattr(exc, "delivery_unknown", False)
    return RuntimeResult(
        False, 5 if injection else getattr(exc, "exit_code", 5), action,
        target.session_id if target else None, target.pid if target else None,
        "delivery_unknown" if uncertain else "not_delivered",
        "injection_failed" if injection else getattr(exc, "error_code", "transport_error"),
        "Runtime operation failed", getattr(exc, "bytes_written", None),
        getattr(exc, "request_id", None), getattr(exc, "response", None),
        uncertain, exc,
    )


def _endpoint(target, action, socket_path_builder):
    """Derive only the endpoint belonging to the resolved session and PID."""
    prefix = f"{target.session_id}.{target.pid}.session"
    if action == "control":
        path = Path(socket_path_builder(str(target.task_dir), target.session_id, str(target.pid)))
        kind = "socket"
    elif action == "send":
        path, kind = target.task_dir / f"{prefix}.pipe", "fifo"
    else:
        path = target.task_dir / f"{prefix}.agent2llm_inject_messages.jsonl"
        kind = "injection"
    return runtime_target.validate_runtime_endpoint(target, endpoint_path=path, endpoint_kind=kind)


def execute_runtime_request(
    request: RuntimeRequest,
    task_dir: Path,
    *,
    session_id: str | None = None,
    pid: int | None = None,
    process_probe=runtime_target.probe_process,
    pipe_sender=None,
    control_sender=None,
    injection_writer=None,
    control_actions=None,
    socket_path_builder=None,
) -> RuntimeResult:
    """Validate, select, revalidate and deliver once; host interrupts propagate.

    Injection may block beyond timeout and pathname checks cannot authenticate
    receivers or eliminate races with a subsequent external writer open.
    """
    target = None
    action = request.action if isinstance(request, RuntimeRequest) and isinstance(request.action, str) else ""
    try:
        payload = _validate(request, control_actions or runtime_control.get_control_actions)
        target = runtime_target.resolve_runtime_target(
            task_dir, session_id=session_id, pid=pid, process_probe=process_probe)
        if request.action == "control" and request.control_action == "get_session_messages":
            payload.setdefault("session_id", target.session_id)
        runtime_target.revalidate_runtime_target(target, process_probe=process_probe)
        endpoint = _endpoint(target, request.action,
                             socket_path_builder or runtime_control.build_socket_path)
        if request.action == "send":
            result = (pipe_sender or runtime_pipe.send_to_pipe)(
                endpoint, request.message, timeout=request.timeout)
            return RuntimeResult(True, 0, action, target.session_id, target.pid,
                                 "pipe_written", bytes_written=result.bytes_written)
        if request.action == "control":
            result = (control_sender or runtime_control.send_to_control)(
                str(endpoint), request.control_action, payload, timeout=request.timeout)
            return RuntimeResult(True, 0, action, target.session_id, target.pid,
                                 "control_acknowledged", request_id=result.request_id,
                                 response=result.response, delivery_unknown=result.delivery_unknown)
        try:
            written = (injection_writer or write_injection)(str(endpoint), request.message)
        except Exception as exc:
            return _failure(action, exc, target, unknown=True, injection=True)
        if not written:
            return _failure(action, RuntimeError("Injection writer did not confirm append"),
                            target, unknown=True, injection=True)
        return RuntimeResult(True, 0, action, target.session_id, target.pid, "injection_queued")
    except (runtime_target.RuntimeTargetError, runtime_pipe.PipeDeliveryError,
            runtime_control.ControlDeliveryError) as exc:
        return _failure(action, exc, target)
