"""Child-process entry point for isolated hook handler execution."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import os
import signal
from typing import Any, Callable

from topsailai.hooks.contracts import ValidationError
from topsailai.hooks.validation import freeze_json
from topsailai.hooks.worker_protocol import (
    PROTOCOL_VERSION,
    ProtocolLimits,
    decode_frame,
    encode_frame,
    parse_request,
)


def _resolve_handler(handler_ref: str) -> Callable[..., Any]:
    """Import one module-level function without resolving arbitrary object chains."""
    module_name, separator, function_name = handler_ref.partition(":")
    if not separator or not module_name or not function_name or "." in function_name:
        raise ValidationError("handler_ref must identify one module-level function")
    module = importlib.import_module(module_name)
    handler = getattr(module, function_name)
    if not inspect.isfunction(handler):
        raise ValidationError("handler_ref must resolve to a function")
    return handler


async def _await_result(value: Any) -> Any:
    """Await any conforming awaitable on the worker-owned event loop."""
    return await value


def _invoke(handler: Callable[..., Any], context: Any) -> Any:
    """Invoke a sync handler or await its result on a worker-owned event loop."""
    result = handler(context)
    if inspect.isawaitable(result):
        return asyncio.run(_await_result(result))
    return result


def _safe_category(exc: BaseException) -> str:
    """Map plugin failures to bounded categories without exposing messages."""
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return "import_error"
    if isinstance(exc, ValidationError):
        return "protocol_error"
    return "handler_error"


def _reap_children(signum: int, frame: Any) -> None:
    """Reap terminated owned descendants before the worker exits on a stop signal."""
    import time

    signal.signal(signum, signal.SIG_IGN)
    try:
        os.killpg(os.getpgrp(), signum)
    except ProcessLookupError:
        pass
    end = time.monotonic() + 0.05
    while time.monotonic() < end:
        try:
            child, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break
        if child == 0:
            time.sleep(0.002)
    raise SystemExit(128 + signum)


def _install_stop_handlers() -> None:
    """Install POSIX stop handlers that reap in-group descendants."""
    if os.name == "posix":
        signal.signal(signal.SIGTERM, _reap_children)


def _read_exact(fd: int, size: int) -> bytes:
    """Read exactly size bytes or reject an early end of the request stream."""
    chunks = bytearray()
    while len(chunks) < size:
        chunk = os.read(fd, size - len(chunks))
        if not chunk:
            raise ValidationError("protocol frame ended before its declared length")
        chunks.extend(chunk)
    return bytes(chunks)


def _read_request_frame(request_limit: int) -> bytes:
    """Read one bounded length-prefixed frame across arbitrary pipe segmentation."""
    header = _read_exact(0, 4)
    declared = int.from_bytes(header, "big")
    if declared > request_limit:
        raise ValidationError("protocol frame exceeds maximum encoded size")
    return header + _read_exact(0, declared)


def run_worker(result_fd: int, request_limit: int, response_limit: int) -> int:
    """Read one request, execute one handler, and write one terminal response."""
    _install_stop_handlers()
    correlation_id = "unknown"
    channel_token = "unknown"
    delivery_id = "unknown"
    try:
        request_frame = _read_request_frame(request_limit)
        request = decode_frame(request_frame, request_limit)
        correlation_id, channel_token, handler_ref, context = parse_request(request)
        delivery_id = context.delivery_id
        try:
            value = _invoke(_resolve_handler(handler_ref), context)
        except BaseException as exc:
            detached = None
            status = "error"
            error_category = _safe_category(exc)
        else:
            try:
                detached = freeze_json(value, max_bytes=response_limit // 2)
                status = "success"
                error_category = None
            except ValidationError:
                detached = None
                status = "invalid_output"
                error_category = "protocol_error"
        response = {
            "protocol_version": PROTOCOL_VERSION,
            "correlation_id": correlation_id,
            "channel_token": channel_token,
            "delivery_id": delivery_id,
            "status": status,
            "value": detached,
            "error_category": error_category,
        }
        frame = encode_frame(response, response_limit)
    except BaseException:
        return 2
    try:
        view = memoryview(frame)
        while view:
            written = os.write(result_fd, view)
            view = view[written:]
    except OSError:
        return 3
    finally:
        os.close(result_fd)
    return 0


def main() -> int:
    """Parse the controlled worker arguments and execute one delivery."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--result-fd", required=True, type=int)
    parser.add_argument("--request-limit", required=True, type=int)
    parser.add_argument("--response-limit", required=True, type=int)
    args = parser.parse_args()
    ProtocolLimits(args.request_limit, args.response_limit)
    return run_worker(args.result_fd, args.request_limit, args.response_limit)


if __name__ == "__main__":
    raise SystemExit(main())
