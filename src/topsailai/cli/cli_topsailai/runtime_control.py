"""Exact bounded JSONL control transport with lazy runtime dependencies.

Author: DawsonLin
"""

import errno
import json
import math
import socket
import stat
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

RESPONSE_LIMIT = 1024 * 1024
_clock = time.monotonic


def get_control_actions() -> list[str]:
    """Query the live handler registry without importing it at module load."""
    from topsailai.workspace.control_channel.handler import ControlHandlerRegistry
    from topsailai.workspace.control_handlers import register_control_handlers

    registry = ControlHandlerRegistry()
    register_control_handlers(registry)
    return registry.list_actions()


def build_socket_path(task_folder: str, session_id: str, pid: str) -> str:
    """Delegate path construction to the existing runtime path authority."""
    from topsailai.workspace.folder_utils import get_control_socket_path

    return get_control_socket_path(task_folder, session_id, pid)


@dataclass(frozen=True)
class ControlDeliveryResult:
    """A correlated acknowledgement, not proof of final business completion."""

    request_id: str
    response: dict
    delivery_unknown: bool = False


class ControlDeliveryError(Exception):
    """Structured failure retaining correlation and possible delivery evidence."""

    def __init__(self, message, error_code, exit_code, request_id="",
                 delivery_unknown=False, response=None):
        """Store facts independently of diagnostic message text."""
        super().__init__(message)
        self.error_code = error_code
        self.exit_code = exit_code
        self.request_id = request_id
        self.delivery_unknown = delivery_unknown
        self.response = response


def _new_socket():
    """Create one socket through a module-local testing seam."""
    return socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)


def _lstat(path):
    """Observe endpoint type without following its final symlink."""
    return path.lstat()


def _request_id():
    """Generate a unique request correlation identifier."""
    return uuid.uuid4().hex


def _remaining(deadline, request_id, sent):
    """Reject exhausted budgets before and after every transport operation."""
    remaining = deadline - _clock()
    if remaining <= 0:
        raise ControlDeliveryError("control request timed out", "timeout", 5,
                                   request_id, sent)
    return remaining


def _io_error(exc, request_id, sent):
    """Classify filesystem/transport facts without inspecting error strings."""
    if isinstance(exc, TimeoutError):
        return ControlDeliveryError("control request timed out", "timeout", 5,
                                    request_id, sent)
    if isinstance(exc, PermissionError):
        return ControlDeliveryError("control endpoint permission denied",
                                    "permission_denied", 4, request_id, sent)
    if isinstance(exc, FileNotFoundError) or getattr(exc, "errno", None) in (errno.ENOENT, errno.ENOTDIR):
        return ControlDeliveryError("control endpoint missing", "endpoint_missing",
                                    4, request_id, sent)
    if getattr(exc, "errno", None) in (errno.EAFNOSUPPORT, errno.EPROTONOSUPPORT):
        return ControlDeliveryError("control transport unsupported",
                                    "unsupported_transport", 4, request_id, sent)
    return ControlDeliveryError(f"control transport failed: {exc}",
                                "transport_error", 5, request_id, sent)


def _operation(call, deadline, request_id, sent):
    """Observe deadline on both success and failure while retaining causes."""
    _remaining(deadline, request_id, sent)
    try:
        value = call()
    except OSError as exc:
        try:
            _remaining(deadline, request_id, sent)
        except ControlDeliveryError as late:
            raise late from exc
        raise _io_error(exc, request_id, sent) from exc
    _remaining(deadline, request_id, sent)
    return value


def _invalid(message, request_id, response=None):
    """Represent an untrusted response after a possible request delivery."""
    return ControlDeliveryError(message, "invalid_response", 6, request_id,
                                True, response)


def _decode(frame, request_id):
    """Validate a complete UTF-8 object response and exact correlation."""
    try:
        response = json.loads(frame.decode("utf-8"))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise _invalid("invalid json or UTF-8 response", request_id) from exc
    if not isinstance(response, dict):
        raise _invalid("response is not a json object", request_id)
    if response.get("request_id") != request_id:
        raise _invalid("response request_id mismatch", request_id)
    if response.get("status") not in ("ok", "error"):
        raise _invalid("response has unknown status", request_id)
    if response["status"] == "error":
        raise ControlDeliveryError("control request rejected", "control_rejected",
                                   6, request_id, False, response)
    return ControlDeliveryResult(request_id, response)


def _receive(sock, deadline, request_id):
    """Read a bounded complete JSONL frame, counting even skipped blank lines."""
    buffer = bytearray()
    total = 0
    while True:
        _operation(lambda: sock.settimeout(_remaining(deadline, request_id, True)),
                   deadline, request_id, True)
        chunk = _operation(lambda: sock.recv(min(65536, RESPONSE_LIMIT + 1 - total)),
                           deadline, request_id, True)
        if not chunk:
            raise _invalid("server closed connection without complete response",
                           request_id)
        total += len(chunk)
        if total > RESPONSE_LIMIT:
            raise _invalid("response exceeds byte limit", request_id)
        buffer.extend(chunk)
        while b"\n" in buffer:
            frame, _, tail = buffer.partition(b"\n")
            buffer = bytearray(tail)
            if frame.strip():
                return _decode(frame, request_id)


def _validate(socket_path, action, payload, timeout):
    """Validate all arguments and JSON encoding before endpoint access."""
    if not isinstance(socket_path, (str, Path)):
        raise ControlDeliveryError("invalid socket path", "usage_error", 2)
    path = Path(socket_path)
    if not path.is_absolute() or "\0" in str(path):
        raise ControlDeliveryError("socket path must be absolute", "usage_error", 2)
    if not isinstance(action, str) or not action or action.strip() != action:
        raise ControlDeliveryError("invalid action", "usage_error", 2)
    if not isinstance(payload, dict):
        raise ControlDeliveryError("payload must be an object", "usage_error", 2)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ControlDeliveryError("invalid timeout", "usage_error", 2)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ControlDeliveryError("invalid timeout", "usage_error", 2)
    if action not in get_control_actions():
        raise ControlDeliveryError("unregistered action", "usage_error", 2)
    request_id = _request_id()
    try:
        data = json.dumps({"request_id": request_id, "action": action,
                           "payload": payload}, ensure_ascii=False,
                          allow_nan=False).encode("utf-8") + b"\n"
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ControlDeliveryError("payload cannot be encoded as JSON",
                                   "usage_error", 2, request_id) from exc
    return path, request_id, data


def send_to_control(socket_path, action, payload, *, timeout=5.0):
    """Send once to one endpoint and require a correlated ok response.

    A sendall failure is conservatively uncertain. Endpoint checks do not
    authenticate the receiving process or eliminate pathname replacement races.
    """
    path, request_id, data = _validate(socket_path, action, payload, timeout)
    if not hasattr(socket, "AF_UNIX"):
        raise ControlDeliveryError("control transport unsupported",
                                   "unsupported_transport", 4, request_id)
    deadline = _clock() + timeout
    info = _operation(lambda: _lstat(path), deadline, request_id, False)
    if not stat.S_ISSOCK(info.st_mode):
        raise ControlDeliveryError("endpoint is not a non-symlink socket",
                                   "endpoint_invalid", 4, request_id)
    _remaining(deadline, request_id, False)
    try:
        sock = _new_socket()
    except OSError as exc:
        try:
            _remaining(deadline, request_id, False)
        except ControlDeliveryError as late:
            raise late from exc
        raise _io_error(exc, request_id, False) from exc
    primary = None
    sent = False
    try:
        _remaining(deadline, request_id, False)
        _operation(lambda: sock.settimeout(_remaining(deadline, request_id, False)),
                   deadline, request_id, False)
        _operation(lambda: sock.connect(str(path)), deadline, request_id, False)
        _operation(lambda: sock.settimeout(_remaining(deadline, request_id, False)),
                   deadline, request_id, False)
        # Arm uncertainty only after the final pre-send budget check.
        _remaining(deadline, request_id, False)
        sent = True
        _operation(lambda: sock.sendall(data), deadline, request_id, sent)
        return _receive(sock, deadline, request_id)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            sock.close()
        except Exception as exc:
            if primary is not None:
                primary.add_note(f"socket cleanup failed: {exc}")
            else:
                raise _io_error(exc, request_id, sent) from exc


def send_control_request(socket_path, action, payload, timeout):
    """Retain the legacy tuple: a valid rejection is transport success."""
    try:
        result = send_to_control(socket_path, action, payload, timeout=timeout)
        return True, result.response
    except ControlDeliveryError as exc:
        if exc.error_code == "control_rejected":
            return True, exc.response
        return False, {"error": str(exc)}
