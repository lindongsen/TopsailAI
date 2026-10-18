"""Coordinator-thread Hook polling for explicitly routed requests. Author: DawsonLin."""
from dataclasses import asdict
import logging
import threading
import time

from topsailai import hooks
from .control_proposals import validated_proposals
from .control_runtime import (
    current_attempt_control, LLMControlledInterruptError, LLMRequestedRetryError,
)
from .first_byte_deadline import current_first_byte_budget
from .request_control import REQUEST_CONTROL
from .response_ownership import current_response_owner, bind_response_owner

_LOG = logging.getLogger(__name__)


def _tick(context, owner):
    """Consume only authenticated direct proposals, outside Hook catch boundaries."""
    route, authority = context[:2]
    snapshot = authority.snapshot()
    if snapshot.outcome is not None:
        return
    payload = asdict(snapshot.target)
    payload["phase"] = snapshot.phase
    budget = current_first_byte_budget()
    payload["remaining_budget"] = budget.remaining() if budget else None
    result = hooks.hook__llm__before__first_byte_wait_tick(**payload)
    for proposal in validated_proposals(result, snapshot.target, registry=REQUEST_CONTROL):
        lease = context[2]["lease"]
        if proposal.operation == "force_retry":
            signal = LLMRequestedRetryError("forced first-byte retry")
        else:
            signal = LLMControlledInterruptError("controlled hard interruption", attempts=1)
        # Arm the exact signal before a selection can commit.
        signal._control_lease = lease
        with lease.lock:
            lease.proposal = proposal
            lease.signal = signal
        with route.lock:
            status = REQUEST_CONTROL.select(snapshot.target, proposal)
            if status is None or status.state != "accepted":
                continue
        owner.abandon(signal)
        finish = context[2].get("finish")
        if finish is not None:
            finish(signal)
        raise signal



def _wait(ready, context, owner, host, timeout):
    """Preserve one deadline and one warning while polling on the caller thread."""
    budget = current_first_byte_budget()
    warned = False
    while not ready.is_set():
        publish = context[2].get("publish_ticket")
        if publish is not None:
            publish()
        _tick(context, owner)
        outcome = context[1].snapshot().outcome
        if ready.is_set():
            return
        if outcome == "timeout":
            owner.abandon()
            raise host._make_first_byte_timeout_error(timeout)
        if budget is not None and budget.expired():
            if not warned:
                from .first_byte_timeout import _safe_warn_once
                _safe_warn_once(budget, host._log_first_byte_timeout,
                                budget.clock() - (budget.deadline - budget.timeout))
                warned = True
            # A publication boundary or select observes raising expiry on the
            # same authority. No second terminal decision is maintained here.
            if context[2]["raise_timeout"]:
                context[1].created(streaming=True)
                if context[1].snapshot().outcome == "timeout":
                    owner.abandon()
                    raise host._make_first_byte_timeout_error(timeout)
        delay = 0.05
        if budget is not None and not budget.expired():
            delay = min(delay, budget.remaining())
        ready.wait(delay)


def controlled_create(host, messages, tools, tool_choice, stream, timeout):
    """Run one owned creation with a shared publication/control authority."""
    context = current_attempt_control()
    route, authority = context[:2]
    context[2]["budget"] = current_first_byte_budget()
    owner = current_response_owner()
    _tick(context, owner)
    _admit(context, owner, host, timeout)
    params = host._build_first_byte_request_parameters(
        messages, tools=tools, tool_choice=tool_choice, stream=stream,
    )
    _tick(context, owner)
    _admit(context, owner, host, timeout)
    ready = threading.Event()
    box = {}
    ticket_box = [None]
    budget = current_first_byte_budget()
    ticket_lock = threading.RLock()
    finished = [False]
    published = [False]
    phase_start = time.monotonic()

    def publish_ticket():
        """Project exact started-ticket accounting onto the coordinator context."""
        with ticket_lock:
            ticket = ticket_box[0]
            if ticket is not None and not published[0]:
                host._publish_first_byte_request_ticket(ticket)
                published[0] = True

    context[2]["publish_ticket"] = publish_ticket

    def finish(primary=None):
        """Finalize only the exact timing ticket, at most once."""
        with ticket_lock:
            ticket = ticket_box[0]
            if ticket is None or finished[0]:
                return
        try:
            host._finish_first_byte_request(ticket)
        except BaseException as error:
            owner._record_cleanup_failure(error, primary, context="ticket")
            return
        with ticket_lock:
            finished[0] = True

    context[2]["finish"] = finish

    def create():
        """Publish exact response custody before terminal arbitration."""
        ticket = None
        accepted = False
        with bind_response_owner(owner):
            try:
                ticket = ticket_box[0]
                if not _claim_operation(context, owner, host, timeout, "create"):
                    return
                response = host._create_first_byte_response(params)
                if not owner.publish_response(response):
                    return
                box["published_at"] = budget.clock() if budget else None
                accepted = authority.created(streaming=stream)
                if accepted:
                    box["value"] = response
                else:
                    owner.abandon()
            except BaseException as error:
                box["published_at"] = budget.clock() if budget else None
                if authority.publish("error"):
                    box["error"] = error
                else:
                    owner._record_cleanup_failure(error, context="late create")
            finally:
                if ticket is not None and not accepted:
                    finish(box.get("error"))
                owner.worker_finished(phase="create")
                ready.set()

    # Publish accounting on the coordinator before any SDK worker is admitted.
    ticket_box[0] = host._start_first_byte_request()
    lease = context[2]["lease"]
    lease.timing_ticket = ticket_box[0]
    lease.timing_stat = getattr(host, "llm_request_stat", None)
    publish_ticket()
    worker = threading.Thread(target=create, daemon=True)
    owner.create_thread = worker
    worker.start()
    try:
        _wait(ready, context, owner, host, timeout)
        _raise_terminal(authority, owner, host, timeout)
    except BaseException as error:
        publish_ticket()
        finish(error)
        raise
    finally:
        publish_ticket()
        host._safe_log_first_byte_phase_elapsed("creation", time.monotonic() - phase_start)
    if "error" in box:
        raise box["error"]
    ticket = ticket_box[0]
    if ticket is not None:
        publish_ticket()
        host._complete_ticket(ticket, stream=stream, owner=owner)
    with route.lock:
        route.state = "first_record" if stream else "completed"
    budget = current_first_byte_budget()
    _warn_completed(host, budget, box.get("published_at"))
    return host._format_first_byte_create_result(
        box["value"], stream=stream,
        create_timed_out=bool(budget and budget.expired()),
    )


def _admit(context, owner, host, timeout):
    """Observe raising expiry before admitting another provider operation."""
    budget = context[2].get("budget")
    if budget is not None and budget.expired() and context[2]["raise_timeout"]:
        context[1].created(streaming=True)
        _raise_terminal(context[1], owner, host, timeout)


def _claim_operation(context, owner, host, timeout, phase):
    """Linearize admission against control; SDK work runs after releasing locks.

    A winning claim admits that exact operation, not any subsequent operation.
    Control selected afterwards may abandon its result, but cannot undo I/O
    already admitted. Timing/resume is followed by a separate provider claim.
    """
    with context[0].lock:
        _admit(context, owner, host, timeout)
        if context[1].snapshot().outcome is not None:
            return False
        context[2]["admitted"] = phase
        return True


def _raise_terminal(authority, owner, host, timeout):
    """Map selected expiry after a fast worker without overriding its outcome."""
    if authority.snapshot().outcome == "timeout":
        owner.abandon()
        _warn_completed(host, current_first_byte_budget())
        raise host._make_first_byte_timeout_error(timeout)


def _warn_completed(host, budget, published_at=None):
    """Use publication time rather than delayed coordinator observation time."""
    observed_at = published_at if published_at is not None else budget.clock() if budget else None
    if budget is not None and observed_at >= budget.deadline:
        from .first_byte_timeout import _safe_warn_once
        _safe_warn_once(budget, host._log_first_byte_timeout,
                        observed_at - (budget.deadline - budget.timeout))


def controlled_stream(host, stream, timeout):
    """Control only the first decoded record, preserving all remaining entries."""
    context = current_attempt_control()
    authority = context[1]
    owner = current_response_owner()
    _tick(context, owner)
    ready = threading.Event()
    box = {}
    ticket = host._get_llm_request_timing_ticket()
    budget = current_first_byte_budget()
    phase_start = time.monotonic()

    def fetch():
        """Read exactly one record and atomically arbitrate its terminal kind."""
        with bind_response_owner(owner):
            try:
                if not _claim_operation(context, owner, host, timeout, "resume"):
                    return
                if ticket is not None:
                    host._resume_llm_request(ticket)
                if not _claim_operation(context, owner, host, timeout, "first_fetch"):
                    return
                try:
                    value = next(stream)
                except StopIteration:
                    box["published_at"] = budget.clock() if budget else None
                    if authority.publish("eof"):
                        box["eof"] = True
                except BaseException as error:
                    box["published_at"] = budget.clock() if budget else None
                    if authority.publish("error"):
                        box["error"] = error
                    else:
                        owner._record_cleanup_failure(error, context="late first record")
                else:
                    box["published_at"] = budget.clock() if budget else None
                    if authority.publish("value"):
                        box["value"] = value
            except BaseException as error:
                if authority.publish("error"):
                    box["error"] = error
            finally:
                owner.worker_finished(phase="first_item")
                ready.set()

    worker = threading.Thread(target=fetch, daemon=True)
    owner.fetch_thread = worker
    worker.start()
    try:
        _wait(ready, context, owner, host, timeout)
        _raise_terminal(authority, owner, host, timeout)
    finally:
        host._safe_log_first_byte_phase_elapsed("first_fetch", time.monotonic() - phase_start)
    _warn_completed(host, current_first_byte_budget(), box.get("published_at"))
    if "error" in box:
        raise box["error"]
    if "eof" in box:
        return
    yield box["value"]
    yield from stream
