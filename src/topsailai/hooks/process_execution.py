"""Shared isolated execution transaction with per-call protocol selection.

Author: DawsonLin. Process and cleanup authority remain in the backend lease.
"""
from __future__ import annotations
import os
import secrets
import time
import uuid
from topsailai.hooks.contracts import HookContext, ValidationError
from topsailai.hooks.module_invocation_protocol import (
    ModuleInvocation, build_module_request, validate_module_response,
)
from topsailai.hooks.process_state import LaunchRecord as _LaunchRecord, WorkerResult
from topsailai.hooks.worker_protocol import build_request, decode_frame, encode_frame


class ProcessExecutionMixin:
    """Reuse one deadline, transport and cleanup transaction for v1 and v2."""

    def _execute_delivery(self, handler_ref, context, timeout_ms, *, module=False,
                          args=(), kwargs=None) -> WorkerResult:
        """Admit a local codec and publish only through the existing cleanup owner."""
        unsupported = self._preflight(timeout_ms)
        if unsupported is not None:
            return unsupported
        interpreter = self._resolve_interpreter()
        if interpreter is None:
            return WorkerResult("unsupported_backend", error_category="missing_interpreter")
        try:
            os.makedirs(self._temp_root, exist_ok=True)
        except OSError:
            return WorkerResult("unsupported_backend", error_category="invalid_temp_root")

        deadline = time.monotonic() + timeout_ms / 1_000
        correlation_id = uuid.uuid4().hex
        channel_token = secrets.token_urlsafe(32)
        if not module:
            request = build_request(
                correlation_id=correlation_id, channel_token=channel_token,
                handler_ref=handler_ref, context=context,
            )
        try:
            if module:
                invocation = ModuleInvocation(args, {} if kwargs is None else kwargs)
                request = build_module_request(
                    correlation_id=correlation_id, channel_token=channel_token,
                    handler_ref=handler_ref, context=context, invocation=invocation,
                    limits=self._limits,
                )
            request_frame = encode_frame(request, self._limits.request_bytes)
        except ValidationError:
            return WorkerResult("invalid_request", error_category="invalid_request")

        record = _LaunchRecord(uuid.uuid4().hex)
        lease = None
        try:
            spawned = self._spawn(interpreter, deadline, record)
            if isinstance(spawned, WorkerResult):
                return spawned
            lease = spawned
            process, result_fd = lease.resources()
            buffers = {"result": bytearray(), "stdout": bytearray(), "stderr": bytearray()}
            dropped = {"stdout": 0, "stderr": 0}
            transferred = False
            try:
                self._before_launch_lease_release(record)
                lease.release_to_caller()
                transferred = True
                read_status = self._exchange(
                    record, process, result_fd, request_frame, buffers, dropped, deadline
                )
                if read_status != "result":
                    if read_status == "timeout":
                        status, category = "timeout", "deadline"
                    elif read_status in ("invalid_output", "worker_lost"):
                        status, category = read_status, "protocol_error"
                    else:
                        status, category = "worker_lost", "transport_error"
                    return lease.finish(status, buffers, dropped, category)
                try:
                    response = decode_frame(bytes(buffers["result"]), self._limits.response_bytes)
                    validator = validate_module_response if module else self._validate_terminal
                    validation_limits = {"limits": self._limits} if module else {}
                    terminal = validator(
                        response,
                        correlation_id=correlation_id,
                        channel_token=channel_token,
                        delivery_id=context.delivery_id,
                        **validation_limits,
                    )
                except ValidationError:
                    return lease.finish(
                        "invalid_output", buffers, dropped, "protocol_error"
                    )
                if self._deadline_expired(deadline):
                    return lease.finish("timeout", buffers, dropped, "deadline")
                metadata = {}
                if module:
                    returned = terminal["returned"]
                    metadata = {"returned": returned,
                                "transport_diagnostic": terminal["transport_diagnostic"]}
                    value = returned.value
                else:
                    value = terminal["value"]
                return lease.finish(
                    str(terminal["status"]),
                    buffers,
                    dropped,
                    terminal["error_category"],
                    value,
                    **metadata,
                )
            finally:
                if transferred:
                    try:
                        lease.finish(
                            "worker_lost", buffers, dropped, "host_interrupted"
                        )
                    finally:
                        lease.close_after_finish()
        except BaseException:
            if lease is not None:
                lease.cleanup()
            else:
                self._abandon_launch(record)
            raise
