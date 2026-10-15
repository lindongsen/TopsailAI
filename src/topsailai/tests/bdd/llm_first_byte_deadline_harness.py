"""Production-boundary U3 HTTP/SSE harness."""

from __future__ import annotations

import functools
import threading
import time
import types
import sys
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.ai_base.llm_base import LLMModel
from topsailai.ai_base.llm_control.response_ownership import (
    AttemptResponseOwner,
    current_response_owner,
)
from tests.bdd.llm_first_byte_deadline_observation import ProvenanceLedger


class ScenarioPatchRecovery:
    """Retain both patch owners and require settlement before restoration."""

    def __init__(self, observation=None, owner_patch=None, settle=None):
        """Store exact patch identities and the authoritative settlement callback."""
        self.observation = observation
        self.owner_patch = owner_patch
        self.settle = settle

    def recover(self):
        """Settle exact owners before restoring patches, preserving host precedence."""
        errors = []
        host_interrupts = []
        if self.settle is not None:
            try:
                self.settle()
            except (KeyboardInterrupt, SystemExit) as error:
                host_interrupts.append(error)
            except BaseException as error:
                errors.append(error)
        if errors or host_interrupts:
            primary = host_interrupts[0] if host_interrupts else errors[0]
            for diagnostic in host_interrupts[1:] + errors[1 if not host_interrupts else 0:]:
                try:
                    primary.add_note(f"scenario patch recovery failed: {diagnostic!r}")
                except BaseException:
                    pass
            raise primary
        if self.observation is not None and not self.observation.restoration_complete:
            try:
                self.observation.stop()
            except (KeyboardInterrupt, SystemExit) as error:
                host_interrupts.append(error)
            except BaseException as error:
                errors.append(error)
        if self.owner_patch is not None:
            try:
                self.owner_patch.stop()
            except (KeyboardInterrupt, SystemExit) as error:
                host_interrupts.append(error)
            except BaseException as error:
                errors.append(error)
        primary = host_interrupts[0] if host_interrupts else (errors[0] if errors else None)
        if primary is not None:
            for diagnostic in host_interrupts[1:] + errors:
                try:
                    primary.add_note(f"scenario patch recovery failed: {diagnostic!r}")
                except BaseException:
                    pass
            raise primary


def recover_scenario_patches(observation=None, owner_patch=None, settle=None):
    """Restore both scenario patch owners after exact settlement succeeds."""
    ScenarioPatchRecovery(observation, owner_patch, settle).recover()


def should_signal_timing_completion(record: dict[str, Any], ticket: Any) -> bool:
    """Require valid provenance and exact ticket identity for timing completion."""
    return (
        record["operation"] == "finish"
        and record["completed"]
        and record["initiator"] is not None
        and record["expected_ticket"] is ticket
        and record["ticket"] is ticket
        and record["source"] in {"owner", "invocation"}
        and record["abandoned_before"]
    )


@contextmanager
def production_deadline_scenario(
    monkeypatch: Any,
    *,
    stream: bool,
    timeout: float,
    raise_on_timeout: bool,
    server_config: MockServerConfig,
    observation=None,
):
    """Run one scenario through LLMModel, the SDK adapter, and loopback HTTP."""
    server = create_server(server_config)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}/v1"
    values = {
        "OPENAI_API_BASE": base_url,
        "OPENAI_BASE_URL": base_url,
        "OPENAI_API_KEY": "u3-bdd",
        "OPENAI_MODEL": "u3-bdd-model",
        "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": str(timeout),
        "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT_RAISE": "1" if raise_on_timeout else "0",
        "LLM_RESPONSE_STREAM": "1" if stream else "0",
        "TOPSAILAI_EVENTS_ENABLED": "0",
        "TOPSAILAI_PRINT_TOOL_STAT": "0",
        "TOPSAILAI_INTERACTIVE_MODE": "0",
        "TOPSAILAI_ENABLE_PARALLEL_TOOL_CALLS": "0",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    model = None
    warnings = []
    warning_events = []
    owners = []
    timing_events = []
    callback_events = []
    timing_tickets = []
    cleanup_completed = {}
    ledger = ProvenanceLedger()
    owner_patch = None
    recovery = None
    try:
        if observation is not None:
            observation.start()
        original_owner_init = AttemptResponseOwner.__init__

        def capture_owner_init(owner):
            """Capture and independently register each production attempt owner."""
            original_owner_init(owner)
            ledger.register_owner(owner)
            owners.append(owner)
            cleanup_completed[owner] = threading.Event()

        owner_patch = patch.object(AttemptResponseOwner, "__init__", capture_owner_init)
        recovery = ScenarioPatchRecovery(
            observation,
            owner_patch,
            settle=lambda: observation.assert_settled(owners) if observation is not None else None,
        )
        if observation is not None:
            observation.scenario_patch_recovery = recovery
        owner_patch.start()
        model = LLMModel()
        if observation is not None:
            observation.attach_model(model)

        original_start = model._start_llm_request
        original_pause = model._pause_llm_request
        original_resume = model._resume_llm_request
        original_finish = model._finish_llm_request

        def record_timing_event(operation, ticket, record):
            """Copy completed recorder evidence into scenario checkpoints."""
            initiator = record["initiator"]
            callback_events.append(dict(record))
            timing_events.append((operation, initiator, ticket))
            if should_signal_timing_completion(record, ticket):
                cleanup_completed[initiator].set()

        def start_request():
            """Delegate start and seal its independently registered ticket."""
            initiator = current_response_owner()
            ticket = original_start()
            if initiator is None:
                raise AssertionError("request start has no response owner")
            ledger.seal_ticket(ticket, initiator)
            ledger.record_start(initiator, ticket)
            timing_events.append(("start", initiator, ticket))
            callback_events.append(dict(ledger.snapshot()[-1]))
            timing_tickets.append((initiator, ticket))
            return ticket

        def _delegate_callback(operation, callback, ticket):
            """Route the real callback through the actual provenance recorder."""
            def completed(record):
                record_timing_event(operation, ticket, record)

            return ledger.observe_callback(
                operation,
                callback,
                ticket,
                on_completion=completed,
            )

        def pause_request(ticket):
            """Delegate pause and record its completed outcome."""
            return _delegate_callback("pause", original_pause, ticket)

        def resume_request(ticket):
            """Delegate resume and record its completed outcome."""
            return _delegate_callback("resume", original_resume, ticket)

        def finish_request(ticket):
            """Delegate finish and record its completed outcome."""
            return _delegate_callback("finish", original_finish, ticket)

        def wrap_attempt(original):
            """Keep the decorated bound method while retaining invocation provenance."""
            @functools.wraps(original)
            def wrapped(*args, **kwargs):
                invocation = ledger.begin()
                token = ledger.bind(invocation)
                try:
                    return original(*args, **kwargs)
                finally:
                    ledger.reset(token)
            return wrapped

        model.call_llm_model = wrap_attempt(model.call_llm_model)
        model.call_llm_model_by_stream = wrap_attempt(model.call_llm_model_by_stream)
        model._start_llm_request = start_request
        model._pause_llm_request = pause_request
        model._resume_llm_request = resume_request
        model._finish_llm_request = finish_request
        def record_warning(elapsed, threshold):
            """Record warning publication time and the open-stream checkpoint."""
            warnings.append((elapsed, threshold))
            at = time.monotonic()
            warning_events.append((threading.get_native_id(), at))
            if observation is not None:
                observation._append(
                    "warning_checkpoint",
                    warning_elapsed=elapsed,
                    owner_states=[bool(getattr(owner, "_abandoned", False)) for owner in owners],
                    close_count=len(observation.events_for("stream_close_before")),
                )

        model._log_first_byte_timeout = record_warning

        result = model.chat(
            [{"role": "user", "content": "u3 production request"}],
            for_raw=True,
            for_stream=stream,
        )
        expected_body = {
            "model": "u3-bdd-model",
            "messages": [
                {"role": "system", "content": ""},
                {"role": "user", "content": "u3 production request"},
            ],
            "stream": stream,
            "max_tokens": model.max_tokens,
            "temperature": model.temperature,
            "top_p": model.top_p,
            "frequency_penalty": model.frequency_penalty,
            "n": 1,
            "parallel_tool_calls": False,
            "stop": None,
        }
        if stream:
            expected_body["stream_options"] = {"include_usage": True}
        yield {"server": server, "model": model, "result": result, "warnings": warnings,
               "owners": owners, "stream": stream, "expected_body": expected_body,
               "timing_events": timing_events, "callback_events": callback_events,
               "cleanup_completed": cleanup_completed,
               "timing_tickets": timing_tickets,
               "ledger": ledger, "observation": observation,
               "warning_events": warning_events,
               "recovery": recovery}
    finally:
        primary_failure = sys.exc_info()[1]
        cleanup_errors = []
        host_interrupt = []

        def attempt_cleanup(cleanup):
            """Attempt cleanup independently while preserving host interruption."""
            try:
                cleanup()
            except (KeyboardInterrupt, SystemExit) as error:
                host_interrupt.append(error)
            except BaseException as error:
                cleanup_errors.append(error)

        def settle_server_thread():
            """Join the server thread and reject a timed-out shutdown."""
            server_thread.join(5)
            assert not server_thread.is_alive()

        if model is not None:
            attempt_cleanup(model.close)
        for cleanup in (server.shutdown, lambda: server.stop_handlers(timeout=5),
                        server.server_close, settle_server_thread):
            attempt_cleanup(cleanup)

        settlement_ok = True
        observation_stopped = observation is None
        if observation is not None:
            try:
                observation.assert_settled(owners)
            except (KeyboardInterrupt, SystemExit) as error:
                host_interrupt.append(error)
                settlement_ok = False
            except BaseException as error:
                cleanup_errors.append(error)
                settlement_ok = False
        if observation is not None and settlement_ok:
            attempt_cleanup(observation.stop)
            observation_stopped = observation.restoration_complete
        if recovery is not None and settlement_ok:
            attempt_cleanup(recovery.recover)
        elif owner_patch is not None and observation_stopped:
            attempt_cleanup(owner_patch.stop)
        if primary_failure is not None:
            for diagnostic in host_interrupt + cleanup_errors:
                try:
                    primary_failure.add_note(f"independent cleanup failed: {diagnostic!r}")
                except BaseException:
                    pass
        elif host_interrupt:
            primary = host_interrupt[0]
            for error in host_interrupt[1:] + cleanup_errors:
                try:
                    primary.add_note(f"independent cleanup failed: {error!r}")
                except BaseException:
                    pass
            raise primary
        elif cleanup_errors:
            primary = cleanup_errors[0]
            for diagnostic in cleanup_errors[1:]:
                primary.add_note(f"independent cleanup failed: {diagnostic!r}")
            raise primary


def request_bodies(server) -> list[dict[str, Any]]:
    """Return exact JSON request bodies captured by the mock server."""
    return [
        record["body"]
        for record in server.request_body_capture.state()["request_bodies"]
    ]


def server_config(
    *,
    stream: bool,
    header_delay: float = 0.0,
    first_delay: float = 0.0,
    after_first_delay: float = 0.0,
    after_first_replies: tuple[str, ...] = ("full answer",),
    complete_delay: float = 0.0,
    replies: tuple[str, ...] = ("full answer",),
    stream_errors: tuple[str | None, ...] | None = None,
) -> MockServerConfig:
    """Build deterministic per-request transport delays for one scenario."""
    if stream:
        if after_first_delay:
            stream_replies = tuple(replies) or after_first_replies
            if stream_errors is None:
                response_chunks = (stream_replies,)
                header_delays = (header_delay,)
                first_delays = (first_delay,)
                after_delays = (after_first_delay,)
            else:
                response_chunks = (stream_replies, stream_replies)
                header_delays = (header_delay, 0.0)
                first_delays = (first_delay, 0.0)
                after_delays = (after_first_delay, after_first_delay)
            return MockServerConfig(
                port=0,
                stream_response_chunks=response_chunks,
                stream_error_messages=stream_errors,
                response_header_delays=header_delays,
                first_chunk_delays=first_delays,
                after_first_chunk_delays=after_delays,
                request_body_capacity=8,
                lifecycle_capacity=8,
            )
        return MockServerConfig(
            port=0,
            stream_response_chunks=tuple((reply,) for reply in replies),
            stream_error_messages=stream_errors,
            response_header_delays=(header_delay,)
            + (0.0,) * max(0, len(replies) - 1),
            first_chunk_delays=(first_delay,)
            + (0.0,) * max(0, len(replies) - 1),
            request_body_capacity=8,
            lifecycle_capacity=8,
        )
    return MockServerConfig(
        port=0,
        reply=replies[0],
        complete_response_replies=replies,
        complete_response_delays=(complete_delay,)
        + (0.0,) * max(0, len(replies) - 1),
        request_body_capacity=8,
        lifecycle_capacity=8,
    )
