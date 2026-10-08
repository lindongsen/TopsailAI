"""Concurrent bounded transport for one owned hook-script process."""

from __future__ import annotations

import os
import selectors
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from topsailai.hooks.hook_script_contracts import HookScriptExecutionPolicy


@dataclass(slots=True)
class ScriptTransportFacts:
    """Retain independent bounded observations for final failure arbitration."""

    stdout: bytearray = field(default_factory=bytearray)
    stderr: bytearray = field(default_factory=bytearray)
    result: bytearray = field(default_factory=bytearray)
    stdout_dropped: int = 0
    stderr_dropped: int = 0
    result_observed_bytes: int = 0
    exit_code: int | None = None
    deadline: bool = False
    cancelled: bool = False
    overflow: bool = False
    invalid_result: bool = False
    transport_error: bool = False
    settled: bool = False
    observed_bytes: int = 0
    eof: set[str] = field(default_factory=set)


def drain_script_process(
    process: subprocess.Popen[bytes],
    result_fd: int,
    stdin: bytes,
    policy: HookScriptExecutionPolicy,
    deadline: float,
    output_remaining: int,
    cancellation: threading.Event,
    close_stdin: Callable[[], None],
) -> ScriptTransportFacts:
    """Exchange one request and observe process exit plus all output-channel EOFs."""
    facts = ScriptTransportFacts()
    selector = selectors.DefaultSelector()
    stdin_offset = 0
    try:
        if process.stdin is None:
            facts.transport_error = True
            return facts
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                os.set_blocking(stream.fileno(), False)
        os.set_blocking(result_fd, False)
        selector.register(process.stdin.fileno(), selectors.EVENT_WRITE, "stdin")
        selector.register(result_fd, selectors.EVENT_READ, "result")
        for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
            if stream is not None:
                selector.register(stream.fileno(), selectors.EVENT_READ, name)
            else:
                facts.eof.add(name)

        while True:
            if _stop_before_settlement(process, facts, cancellation, deadline):
                break
            remaining = deadline - time.monotonic()
            events = selector.select(min(remaining, 0.05))
            for key, mask in events:
                name = key.data
                if name == "stdin" and mask & selectors.EVENT_WRITE:
                    stdin_offset = _write_stdin(
                        selector, key.fd, stdin, stdin_offset, close_stdin, facts
                    )
                    continue
                _read_output(
                    selector,
                    key.fd,
                    name,
                    facts,
                    policy,
                    output_remaining,
                )
            if _stop_before_settlement(process, facts, cancellation, deadline):
                break
        facts.exit_code = process.poll()
        return facts
    except OSError:
        facts.transport_error = True
        _observe_stop_facts(facts, cancellation, deadline)
        try:
            facts.exit_code = process.poll()
        except OSError:
            pass
        return facts
    finally:
        selector.close()


def _observe_stop_facts(
    facts: ScriptTransportFacts,
    cancellation: threading.Event,
    deadline: float,
) -> bool:
    """Record current cancellation and deadline facts without waiting."""
    if cancellation.is_set():
        facts.cancelled = True
        return True
    if time.monotonic() >= deadline:
        facts.deadline = True
        return True
    return False


def _stop_before_settlement(
    process: subprocess.Popen[bytes],
    facts: ScriptTransportFacts,
    cancellation: threading.Event,
    deadline: float,
) -> bool:
    """Observe cancellation and deadline before errors or complete settlement."""
    facts.exit_code = process.poll()
    if _observe_stop_facts(facts, cancellation, deadline):
        return True
    if facts.overflow or facts.invalid_result or facts.transport_error:
        return True
    if facts.exit_code is not None and {"stdout", "stderr", "result"} <= facts.eof:
        facts.settled = True
        return True
    return False


def _write_stdin(
    selector: selectors.BaseSelector,
    descriptor: int,
    stdin: bytes,
    offset: int,
    close_stdin: Callable[[], None],
    facts: ScriptTransportFacts,
) -> int:
    """Write a bounded request segment and close owned stdin after EOF delivery."""
    try:
        written = os.write(descriptor, stdin[offset : offset + 65_536])
    except BlockingIOError:
        return offset
    except BrokenPipeError:
        written = 0
        selector.unregister(descriptor)
        close_stdin()
        return offset
    except OSError:
        facts.transport_error = True
        return offset
    offset += written
    if offset == len(stdin):
        selector.unregister(descriptor)
        close_stdin()
    return offset


def _read_output(
    selector: selectors.BaseSelector,
    descriptor: int,
    name: str,
    facts: ScriptTransportFacts,
    policy: HookScriptExecutionPolicy,
    output_remaining: int,
) -> None:
    """Observe cap-plus-one while retaining only admitted channel and batch bytes."""
    channel_remaining = _channel_remaining(name, facts, policy)
    aggregate_remaining = max(0, output_remaining - facts.observed_bytes)
    read_size = min(65_536, channel_remaining + 1, aggregate_remaining + 1)
    try:
        chunk = os.read(descriptor, max(1, read_size))
    except BlockingIOError:
        return
    except OSError:
        facts.transport_error = True
        return
    if not chunk:
        selector.unregister(descriptor)
        facts.eof.add(name)
        return

    facts.observed_bytes += len(chunk)
    retention_allowance = min(len(chunk), aggregate_remaining)
    if len(chunk) > aggregate_remaining:
        facts.overflow = True
    if name == "stdout":
        _retain_diagnostic(
            chunk, facts.stdout, policy.stdout_limit_bytes, retention_allowance, facts, True
        )
    elif name == "stderr":
        _retain_diagnostic(
            chunk, facts.stderr, policy.stderr_limit_bytes, retention_allowance, facts, False
        )
    else:
        facts.result_observed_bytes += len(chunk)
        retained = min(retention_allowance, channel_remaining)
        facts.result.extend(chunk[:retained])
        if len(chunk) > channel_remaining:
            facts.overflow = True
        _classify_partial_result(facts, policy.result_limit_bytes)


def _channel_remaining(
    name: str,
    facts: ScriptTransportFacts,
    policy: HookScriptExecutionPolicy,
) -> int:
    """Return bytes remaining before the next byte proves channel overflow."""
    if name == "stdout":
        return max(0, policy.stdout_limit_bytes - len(facts.stdout))
    if name == "stderr":
        return max(0, policy.stderr_limit_bytes - len(facts.stderr))
    return max(0, policy.result_limit_bytes + 4 - len(facts.result))


def _retain_diagnostic(
    chunk: bytes,
    buffer: bytearray,
    limit: int,
    retention_allowance: int,
    facts: ScriptTransportFacts,
    stdout: bool,
) -> None:
    """Retain bytes within both caps and count every observed discarded byte."""
    available = min(max(0, limit - len(buffer)), retention_allowance)
    retained = min(len(chunk), available)
    buffer.extend(chunk[:retained])
    dropped = len(chunk) - retained
    if stdout:
        facts.stdout_dropped += dropped
    else:
        facts.stderr_dropped += dropped
    if dropped:
        facts.overflow = True


def _classify_partial_result(facts: ScriptTransportFacts, body_limit: int) -> None:
    """Reject an impossible frame as soon as its bounded header or trailing byte proves it."""
    if len(facts.result) < 4:
        return
    declared = int.from_bytes(facts.result[:4], "big")
    if not 1 <= declared <= body_limit:
        facts.invalid_result = True
        return
    if len(facts.result) > declared + 4:
        facts.invalid_result = True
