"""Provider-neutral first-byte timeout orchestration."""

import logging
import threading
import time

from .first_byte_deadline import (
    FirstBytePhase, current_first_byte_budget, resolve_first_byte_budget,
)
from .response_ownership import (
    AttemptResponseOwner,
    ClosingTimedIterator,
    bind_response_owner,
    current_response_owner,
)


def _safe_warn_once(budget, callback, elapsed):
    """Keep warning-hook failures out of request outcome control flow."""
    try:
        budget.warn_once(callback, elapsed)
    except Exception:
        try:
            logging.getLogger(__name__).warning(
                "first-byte timeout warning failed elapsed=%s", elapsed, exc_info=True
            )
        except Exception:
            pass


def _wait_for_events(events, budget=None, poll_interval=0.05):
    """Wait for one of several events using the supplied absolute budget."""
    while not any(event.is_set() for event in events):
        if budget is None:
            timeout = poll_interval
        else:
            remaining = budget.remaining()
            if remaining <= 0:
                return False
            timeout = min(remaining, poll_interval)
        events[0].wait(timeout=timeout)
    return True


class FirstByteTimeoutMixin:
    """Coordinate request creation and stream first-item timeout handling."""

    def _create_with_first_byte_timeout(
        self, messages, tools=None, tool_choice="auto", stream=False,
        first_byte_timeout=180, raise_on_timeout=False, *, budget=None,
    ):
        """Create a response using one absolute creation/first-item budget."""
        owner = current_response_owner() or AttemptResponseOwner()
        budget = resolve_first_byte_budget(
            first_byte_timeout, explicit=budget or current_first_byte_budget()
        )
        if budget is None:
            params = self._build_first_byte_request_parameters(
                messages, tools=tools, tool_choice=tool_choice, stream=stream
            )
            return self._create_without_first_byte_timeout(params, stream=stream, owner=owner)
        if raise_on_timeout and budget.expired():
            _safe_warn_once(budget, self._log_first_byte_timeout, first_byte_timeout)
            owner.abandon()
            raise self._make_first_byte_timeout_error(first_byte_timeout)
        creation_started_at = time.monotonic()
        try:
            params = self._build_first_byte_request_parameters(
                messages, tools=tools, tool_choice=tool_choice, stream=stream
            )
        except BaseException as error:
            owner.abandon(error)
            raise
        # This is the consumer-side admission gate: no worker, ticket, or
        # provider operation may start after a raising-mode expiry observed
        # immediately after preparation.
        if raise_on_timeout and budget.expired():
            owner.abandon()
            _safe_warn_once(
                budget, self._log_first_byte_timeout,
                budget.clock() - (budget.deadline - budget.timeout),
            )
            raise self._make_first_byte_timeout_error(first_byte_timeout)
        phase = FirstBytePhase(budget)
        ticket_box = [None]
        started = threading.Event()
        ready = threading.Event()
        start_error = [None]

        def create():
            """Run creation and publish a terminal phase decision."""
            ticket = None
            finalized = False
            with bind_response_owner(owner):
                try:
                    ticket = self._start_first_byte_request()
                    ticket_box[0] = ticket
                    started.set()
                    if raise_on_timeout and budget.expired():
                        phase.expire()
                        self._finish_ticket(ticket, owner)
                        finalized = True
                        return
                    response = self._create_first_byte_response(params)
                    phase.completed()
                    if not owner.publish_response(response):
                        phase.expire()
                        self._finish_ticket(ticket, owner)
                        finalized = True
                        return
                    if not owner.publish_outcome(response, phase="create"):
                        phase.expire()
                        self._finish_ticket(ticket, owner)
                        finalized = True
                        return
                    committed = phase.publish(allow_late=not raise_on_timeout)
                    if not committed:
                        owner.abandon()
                        self._finish_ticket(ticket, owner)
                        finalized = True
                        return
                    if not raise_on_timeout and budget.warning_required_for(phase):
                        self._warn_first_byte_timeout_once(budget, budget.timeout)
                except BaseException as error:
                    if ticket is None:
                        start_error[0] = error
                    staged = owner.publish_error(error, phase="create")
                    if staged and phase.publish(allow_late=not raise_on_timeout):
                        pass
                    else:
                        phase.expire()
                        owner.abandon(error)
                    if ticket is not None and phase.state != "COMMITTED":
                        self._finish_ticket(ticket, owner, error)
                        finalized = True
                finally:
                    if ticket is not None and not finalized and phase.state != "COMMITTED":
                        self._finish_ticket(ticket, owner)
                    owner.worker_finished(phase="create")
                    ready.set()

        try:
            worker = threading.Thread(target=create, daemon=True)
            owner.create_thread = worker
            worker.start()
        except BaseException:
            owner.abandon()
            raise

        ticket = None
        ticket_published = False
        # Observe terminal/start-failure state while waiting for the initial
        # ticket; never wait indefinitely for a ticket that cannot be created.
        _wait_for_events((started, ready), budget)
        if not started.is_set() and not ready.is_set():
            if raise_on_timeout:
                expired = phase.expire()
                if expired:
                    owner.abandon()
                    _safe_warn_once(
                        budget, self._log_first_byte_timeout,
                        budget.clock() - (budget.deadline - budget.timeout),
                    )
                    raise self._make_first_byte_timeout_error(first_byte_timeout)
            else:
                self._warn_first_byte_timeout_once(budget, budget.timeout)
                # Warning mode continues the same request after the shared budget.
                _wait_for_events((ready,), poll_interval=0.05)
        ticket = ticket_box[0]
        if ticket is not None:
            self._publish_first_byte_request_ticket(ticket)
            ticket_published = True

        if not ready.is_set():
            if not _wait_for_events((ready,), budget):
                if raise_on_timeout:
                    expired = phase.expire()
                    if expired:
                        owner.abandon()
                        _safe_warn_once(
                            budget, self._log_first_byte_timeout,
                            budget.clock() - (budget.deadline - budget.timeout),
                        )
                        raise self._make_first_byte_timeout_error(first_byte_timeout)
                else:
                    self._warn_first_byte_timeout_once(budget, budget.timeout)
                    # Continue the original operation after warning threshold.
                    _wait_for_events((ready,), poll_interval=0.05)
        if ticket is None:
            ticket = ticket_box[0]
        if ticket is not None and not ticket_published:
            self._publish_first_byte_request_ticket(ticket)
        creation_elapsed = time.monotonic() - creation_started_at
        self._safe_log_first_byte_phase_elapsed("creation", creation_elapsed)
        if raise_on_timeout and not phase.committed():
            if ready.is_set():
                ready_outcome = owner.take_outcome(phase="create")
                if ready_outcome.kind == "ERROR":
                    if ticket is not None:
                        self._finish_ticket(ticket, owner)
                    raise ready_outcome.value
            expired = phase.expire()
            if start_error[0] is not None:
                raise start_error[0]
            if expired:
                owner.abandon(start_error[0])
                raise self._make_first_byte_timeout_error(first_byte_timeout)

        outcome = owner.take_outcome(phase="create")
        if outcome.kind == "ERROR":
            if ticket is not None:
                self._finish_ticket(ticket, owner)
            raise outcome.value
        if outcome.kind in {"ABANDONED", "NOT_READY"}:
            if start_error[0] is not None:
                raise start_error[0]
            raise RuntimeError("first-byte creation completed without an outcome")
        if ticket is not None:
            self._complete_ticket(ticket, stream=stream, owner=owner)
        create_timed_out = (
            phase.published_at is not None
            and phase.published_at >= budget.deadline
        )
        return self._format_first_byte_create_result(
            outcome.value, stream=stream, create_timed_out=create_timed_out
        )

    def _complete_ticket(self, ticket, *, stream, owner):
        """Complete accepted bookkeeping while preserving primary failures."""
        try:
            self._complete_first_byte_request(ticket, stream=stream)
        except BaseException as error:
            try:
                owner.abandon(error)
            except BaseException as abandon_error:
                owner._record_cleanup_failure(abandon_error, error, context="ticket")
            raise

    def _finish_ticket(self, ticket, owner, primary=None):
        """Finish one exact timing ticket and retain cleanup failures."""
        try:
            self._finish_first_byte_request(ticket)
        except BaseException as error:
            owner._record_cleanup_failure(error, primary, context="ticket")

    def iter_stream_with_first_byte_timeout(
        self, stream, first_byte_timeout=180, raise_on_timeout=False,
        create_timed_out=False,
    ):
        """Yield a stream while applying the shared budget to its first item."""
        owner = current_response_owner()
        timed_stream = ClosingTimedIterator(stream, owner) if owner else stream
        timing_ticket = self._get_llm_request_timing_ticket()
        budget = current_first_byte_budget()
        if budget is None:
            yield from self._iter_first_byte_timeout(
                stream, first_byte_timeout, raise_on_timeout, create_timed_out,
                on_timeout=self._log_first_byte_timeout,
                make_timeout_error=self._make_first_byte_timeout_error,
            )
            return
        yield from self._iter_first_byte_timeout(
            timed_stream, first_byte_timeout, raise_on_timeout, create_timed_out,
            on_timeout=self._log_first_byte_timeout,
            make_timeout_error=self._make_first_byte_timeout_error,
            owner=owner, budget=budget, timing_ticket=timing_ticket,
            resume=self._resume_llm_request, pause=None,
            phase_logger=self._safe_log_first_byte_phase_elapsed,
        )

    def _iter_first_byte_timeout(self, stream, *args, **kwargs):
        """Apply the stream timeout helper through the host adapter."""
        return iter_with_first_byte_timeout(stream, *args, **kwargs)

    def _warn_first_byte_timeout_once(self, budget, timeout):
        """Emit one warning for the shared attempt budget."""
        if budget.warning_emitted:
            return
        _safe_warn_once(
            budget, self._log_first_byte_timeout, budget.clock() - (budget.deadline - budget.timeout)
        )

    def _safe_log_first_byte_phase_elapsed(self, phase_name, elapsed):
        """Keep ordinary diagnostic failures from replacing request outcomes."""
        try:
            self._log_first_byte_phase_elapsed(phase_name, elapsed)
        except Exception:
            try:
                logging.getLogger(__name__).warning(
                    "first-byte phase diagnostic failed: phase=%s elapsed=%s",
                    phase_name, elapsed, exc_info=True,
                )
            except Exception:
                pass

    def _log_first_byte_phase_elapsed(self, phase_name, elapsed):
        """Log phase timing diagnostics without affecting deadline decisions."""
        logger = getattr(self, "logger", None)
        if logger is not None and hasattr(logger, "debug"):
            logger.debug("first-byte %s phase elapsed %.6fs", phase_name, elapsed)

    @staticmethod
    def _format_first_byte_create_result(response, *, stream, create_timed_out):
        """Preserve established stream and non-stream return shapes."""
        if stream:
            return response, create_timed_out
        return response

    def _create_without_first_byte_timeout(self, params, *, stream, owner):
        """Run an unmonitored provider create attempt with ownership."""
        ticket = None
        finalized = False
        try:
            ticket = self._start_first_byte_request()
            self._publish_first_byte_request_ticket(ticket)
            response = self._create_first_byte_response(params)
            if not owner.publish_response(response):
                self._finish_first_byte_request(ticket)
                finalized = True
                raise RuntimeError("first-byte response ownership was abandoned")
            self._complete_first_byte_request(ticket, stream=stream)
            finalized = True
            owner.publish_outcome(response, phase="create")
            outcome = owner.take_outcome(phase="create")
            if outcome.kind == "ERROR":
                raise outcome.value
            return self._format_first_byte_create_result(
                outcome.value, stream=stream, create_timed_out=False
            )
        except BaseException as error:
            owner.publish_error(error, phase="create")
            owner.abandon(error)
            if ticket is not None and not finalized:
                try:
                    self._finish_first_byte_request(ticket)
                except BaseException as finish_error:
                    owner._record_cleanup_failure(finish_error, error, context="ticket")
            raise

    def _build_first_byte_request_parameters(self, messages, *, tools, tool_choice, stream):
        """Build provider parameters through the host adapter."""
        raise NotImplementedError

    def _create_first_byte_response(self, params):
        """Execute provider creation through the host adapter."""
        raise NotImplementedError

    def _start_first_byte_request(self):
        """Start request timing through the host adapter."""
        raise NotImplementedError

    def _pause_first_byte_request(self, ticket):
        """Pause request timing through the host adapter."""
        raise NotImplementedError

    def _finish_first_byte_request(self, ticket):
        """Finish request timing through the host adapter."""
        raise NotImplementedError

    def _publish_first_byte_request_ticket(self, ticket):
        """Publish a request ticket through the host adapter."""
        raise NotImplementedError

    def _complete_first_byte_request(self, ticket, *, stream):
        """Pause a stream request or finish a non-stream request."""
        if stream:
            self._pause_first_byte_request(ticket)
            return
        self._finish_first_byte_request(ticket)


def iter_with_first_byte_timeout(
    stream, first_byte_timeout=180, raise_on_timeout=False,
    create_timed_out=False, *, on_timeout, make_timeout_error, owner=None,
    budget=None, timing_ticket=None, resume=None, pause=None,
    phase_logger=None,
):
    """Yield a first decoded entry under one absolute deadline."""
    if budget is None and current_first_byte_budget() is None and (
        first_byte_timeout is None or first_byte_timeout <= 0
    ):
        if owner is None and timing_ticket is None and resume is None and pause is None:
            yield from stream
            return
        active_owner = owner or AttemptResponseOwner()
        local_owner = owner is None
        if local_owner:
            active_owner.publish_response(stream)
        primary = None
        try:
            if resume is not None and timing_ticket is not None:
                resume(timing_ticket)
            yield from stream
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                if pause is not None and timing_ticket is not None:
                    try:
                        pause(timing_ticket)
                    except BaseException as pause_error:
                        if primary is not None:
                            try:
                                primary.add_note(f"first-byte pause failed: {pause_error!r}")
                            except BaseException:
                                pass
                        else:
                            raise
            finally:
                if local_owner:
                    active_owner.dispose(primary=primary, background=False)
        return
    if budget is None and current_first_byte_budget() is None and (
        owner is None and timing_ticket is None and resume is None and pause is None
    ):
        first_item = [None]
        first_exception = [None]
        got_result = threading.Event()

        def fetch_first():
            """Fetch the first item in a daemon thread for legacy callers."""
            try:
                first_item[0] = next(stream)
            except StopIteration:
                pass
            except Exception as error:
                first_exception[0] = error
            finally:
                got_result.set()

        start_time = time.monotonic()
        threading.Thread(target=fetch_first, daemon=True).start()
        timed_out = not got_result.wait(timeout=first_byte_timeout)
        elapsed = time.monotonic() - start_time
        if timed_out:
            if not create_timed_out:
                on_timeout(elapsed, first_byte_timeout)
            if raise_on_timeout:
                raise make_timeout_error(first_byte_timeout)
            # LEGACY COMPATIBILITY: the bare/class-wrapper seam historically
            # stops and returns [] after warning. Production owned calls do
            # not enter this branch because they carry owner/budget metadata.
            close = getattr(stream, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:
                    pass
            return
        if first_exception[0] is not None:
            raise first_exception[0]
        if first_item[0] is None:
            return
        if elapsed > first_byte_timeout and not create_timed_out:
            on_timeout(elapsed, first_byte_timeout)
        yield first_item[0]
        yield from stream
        return
    active_owner = owner or AttemptResponseOwner()
    local_owner = owner is None

    def dispose_local(primary=None):
        """Dispose a helper-owned stream on every terminal path."""
        if local_owner:
            active_owner.dispose(primary=primary, background=False)

    primary = None
    pause_attempted = False
    decision = {"kind": "VALUE", "staged": False, "error": None}

    def pause_first_result(primary_error=None):
        """Pause an explicit first-result ticket at most once before delivery."""
        nonlocal pause_attempted
        if pause_attempted or pause is None or timing_ticket is None:
            return
        pause_attempted = True
        try:
            pause(timing_ticket)
        except BaseException as pause_error:
            if primary_error is not None:
                try:
                    primary_error.add_note(f"first-byte pause failed: {pause_error!r}")
                except BaseException:
                    pass
                return
            raise

    try:
        if local_owner:
            active_owner.publish_response(stream)
        budget = resolve_first_byte_budget(
            first_byte_timeout, explicit=budget or current_first_byte_budget()
        )
        if budget is None:
            yield from stream
            return
        fetch_started_at = time.monotonic()
        phase = FirstBytePhase(budget)
        ready = threading.Event()
        decision = {"kind": "NOT_READY", "staged": False, "error": None}

        def fetch_first():
            """Perform exactly one decoded iterator operation."""
            with bind_response_owner(active_owner):
                try:
                    if raise_on_timeout and budget.expired():
                        decision["kind"] = "ABANDONED"
                        phase.expire()
                        return
                    if resume is not None and timing_ticket is not None:
                        resume(timing_ticket)
                    if raise_on_timeout and budget.expired():
                        decision["kind"] = "ABANDONED"
                        phase.expire()
                        return
                    try:
                        value = next(stream)
                    except StopIteration:
                        decision["kind"] = "EOF"
                        phase.completed()
                        decision["staged"] = active_owner.publish_eof(phase="first_item")
                        if decision["staged"] and phase.publish(allow_late=not raise_on_timeout):
                            return
                        phase.expire()
                        return
                    except BaseException as error:
                        decision["kind"] = "ERROR"
                        decision["error"] = error
                        decision["staged"] = active_owner.publish_error(error, phase="first_item")
                        if decision["staged"] and phase.publish(allow_late=not raise_on_timeout):
                            return
                        phase.expire()
                        return
                    decision["kind"] = "VALUE"
                    phase.completed()
                    decision["staged"] = active_owner.publish_outcome(value, phase="first_item")
                    if not decision["staged"]:
                        decision["kind"] = "REJECTED"
                        phase.expire()
                        return
                    if not phase.publish(allow_late=not raise_on_timeout):
                        decision["kind"] = "REJECTED"
                        phase.expire()
                        return
                except BaseException as error:
                    # StopIteration is handled only around next(stream). Any error
                    # from timing, staging, phase publication, or diagnostics is
                    # an actual worker failure, never synthetic EOF.
                    if decision["error"] is None:
                        decision["kind"] = "ERROR"
                        decision["error"] = error
                    try:
                        active_owner.publish_error(error, phase="first_item")
                    except BaseException:
                        pass
                    try:
                        phase.expire()
                    except BaseException:
                        pass
                finally:
                    active_owner.worker_finished(phase="first_item")
                    ready.set()

        worker = threading.Thread(target=fetch_first, daemon=True)
        active_owner.fetch_thread = worker
        worker.start()
        if not ready.wait(timeout=budget.remaining()):
            if phase.committed():
                pass
            elif ready.is_set() and decision["error"] is not None:
                raise decision["error"]
            elif raise_on_timeout:
                expired = phase.expire()
                if expired:
                    active_owner.abandon()
                    _safe_warn_once(
                        budget, on_timeout, budget.clock() - (budget.deadline - budget.timeout)
                    )
                    raise make_timeout_error(first_byte_timeout)
            else:
                if not create_timed_out:
                    _safe_warn_once(
                        budget, on_timeout, budget.clock() - (budget.deadline - budget.timeout)
                    )
                ready.wait()
        fetch_elapsed = time.monotonic() - fetch_started_at
        if phase_logger is not None:
            try:
                phase_logger("first_fetch", fetch_elapsed)
            except Exception:
                try:
                    logging.getLogger(__name__).warning(
                        "first-byte phase diagnostic failed: phase=first_fetch elapsed=%s",
                        fetch_elapsed, exc_info=True,
                    )
                except Exception:
                    pass
        if raise_on_timeout and not phase.committed():
            if decision["error"] is not None:
                raise decision["error"]
            expired = phase.expire()
            if expired:
                active_owner.abandon()
                raise make_timeout_error(first_byte_timeout)

        outcome = active_owner.take_outcome(phase="first_item")
        if (outcome.kind in {"VALUE", "ERROR", "EOF"}
                and not raise_on_timeout and not create_timed_out
                and phase.committed() and budget.warning_required_for(phase)):
            _safe_warn_once(
                budget, on_timeout, budget.clock() - (budget.deadline - budget.timeout)
            )
        if outcome.kind == "ERROR":
            pause_first_result(outcome.value)
            raise outcome.value
        if outcome.kind == "NOT_READY":
            if decision["kind"] == "REJECTED":
                return
            if decision["error"] is not None:
                raise decision["error"]
            raise RuntimeError("first-byte stream ended without a published outcome")
        if outcome.kind == "EOF":
            pause_first_result()
            return
        if outcome.kind == "ABANDONED":
            return
        pause_first_result()
        yield outcome.value
        yield from stream
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            if decision["kind"] in {"ERROR", "EOF", "VALUE"}:
                pause_first_result(primary)
        finally:
            dispose_local(primary)
