"""Explicit application routing and request lifetimes. Author: DawsonLin."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
import sys
from threading import RLock
from uuid import uuid4

from topsailai.ai_base.exception import LLMBackToChatError
from .attempt_control import AttemptTarget
from .request_control import REQUEST_CONTROL
from .control_recovery import RECOVERY_POOL
from .response_ownership import current_response_owner

_ROUTE = ContextVar("topsailai_llm_route", default=None)
_INVOCATION = ContextVar("topsailai_llm_invocation", default=None)
_ATTEMPT = ContextVar("topsailai_llm_attempt", default=None)


def _restore_context(variable, token, primary):
    """Restore independently without replacing an already propagating failure."""
    try:
        variable.reset(token)
    except BaseException as restoration_error:
        if primary is None:
            raise
        primary.add_note(
            "control context restoration failed: "
            + type(restoration_error).__name__ + ": " + str(restoration_error)
        )


class LLMRequestedRetryError(Exception):
    """Consume one original automatic attempt without resetting its budget."""


class LLMControlledInterruptError(LLMBackToChatError):
    """Abandon a supported interactive turn, distinct from legacy interrupt."""


class ControlRoute:
    """Bind one explicit application owner to scalar control metadata."""

    def __init__(self, session_id, pid, agent, *, interrupt_supported):
        """Mint a fresh binding capability for this application execution."""
        self.session_id = session_id
        self.pid = pid
        self.agent = agent
        self.binding_id = uuid4().hex
        self.generation = 1
        self.interrupt_supported = bool(interrupt_supported)
        self.lock = RLock()
        self.target = None
        self.state = "idle"
        self.closed = False
        self.executing = None
        self.reason = None

    def reconcile(self):
        """Drive independent exact custody without retaining predecessor Agents."""
        RECOVERY_POOL.schedule()

    def view(self):
        """Expose detached scalar state, never Agent, owner, prompt or errors."""
        self.reconcile()
        with self.lock:
            return {"state": self.state, "reason": self.reason,
                    "target": asdict(self.target) if self.target else None}


@contextmanager
def application_control_scope(route):
    """Bind explicitly on the application thread, not by ambient handler lookup."""
    with route.lock:
        route.closed = False
    token = _ROUTE.set(route)
    try:
        yield route
    finally:
        primary = sys.exception()
        try:
            _restore_context(_ROUTE, token, primary)
        finally:
            with route.lock:
                route.closed = True
                route.state = "unavailable"
            if primary is not None:
                RECOVERY_POOL.supersede(route.binding_id, None, primary)
            try:
                RECOVERY_POOL.schedule()
            except BaseException as cleanup_error:
                if primary is None:
                    raise
                primary.add_note("control route recovery remains journaled: " + type(cleanup_error).__name__)


def invocation_control(function):
    """Give each chat call a new identity without leaking it into SDK workers."""
    from functools import wraps

    @wraps(function)
    def wrapped(*args, **kwargs):
        """Scope a single chat invocation including its original backoff loop."""
        route = _ROUTE.get()
        eligible = False
        if route is not None:
            with route.lock:
                eligible = (not route.closed and
                            args[0] is getattr(route.agent, "llm_model", route.agent))
        if not eligible:
            token = _INVOCATION.set(None)
            try:
                return function(*args, **kwargs)
            finally:
                _restore_context(_INVOCATION, token, sys.exception())
        invocation = uuid4().hex
        token = _INVOCATION.set(invocation)
        try:
            return function(*args, **kwargs)
        except BaseException as primary:
            RECOVERY_POOL.supersede(route.binding_id, invocation, primary)
            raise
        finally:
            try:
                _restore_context(_INVOCATION, token, sys.exception())
            finally:
                with route.lock:
                    route.state = "idle"
    return wrapped


@contextmanager
def attempt_control_scope(budget, raise_timeout):
    """Reserve bounded custody or keep the entire attempt on the legacy path."""
    route = _ROUTE.get()
    invocation = _INVOCATION.get()
    if route is None or invocation is None or route.closed:
        token = _ATTEMPT.set(None)
        try:
            yield None
        finally:
            _restore_context(_ATTEMPT, token, sys.exception())
        return
    target = AttemptTarget(route.binding_id, route.generation, invocation, uuid4().hex)
    try:
        lease = RECOVERY_POOL.reserve(target, current_response_owner())
    except BaseException:
        # Reservation may have published before its return was interrupted.
        with RECOVERY_POOL.lock:
            retained = RECOVERY_POOL.leases.get(target)
        if retained is not None:
            with retained.lock:
                retained.active = False
                retained.superseded = True
        raise
    if lease is None:
        marker = object()
        with route.lock:
            route.executing = marker
            route.target = None
            route.state = "unavailable"
            route.reason = "control_capacity"
        token = _ATTEMPT.set(None)
        try:
            yield None
        finally:
            try:
                _restore_context(_ATTEMPT, token, sys.exception())
            finally:
                with route.lock:
                    if route.executing is marker:
                        route.executing = None
        return
    token = None
    try:
        with route.lock:
            if route.closed:
                raise RuntimeError("control route closed")
            route.executing = target
            authority = REQUEST_CONTROL.bind(
                target, deadline=budget.deadline if budget else None,
                raise_timeout=bool(raise_timeout),
                retry_available=_RETRY_AVAILABLE.get(),
                interrupt_supported=route.interrupt_supported,
            )
            lease.authority = authority
            route.target = target
            route.reason = None
            route.state = "creating"
        context = (route, authority, {"raise_timeout": bool(raise_timeout),
                                    "budget": budget, "lease": lease})
        token = _ATTEMPT.set(context)
        yield context
    finally:
        primary = sys.exception()
        try:
            if token is not None:
                _restore_context(_ATTEMPT, token, sys.exception())
        finally:
            # This lease was registered before bind and survives route closure.
            with lease.lock:
                if primary is not None and primary is not lease.signal:
                    lease.superseded = True
                lease.active = False
            with route.lock:
                if route.executing == target:
                    route.executing = None
                if route.target == target:
                    route.target = None
                    route.state = "backoff"
            try:
                RECOVERY_POOL.schedule()
            except BaseException as cleanup_error:
                if primary is None:
                    raise
                primary.add_note("control recovery remains journaled: " + type(cleanup_error).__name__)


_RETRY_AVAILABLE = ContextVar("topsailai_llm_retry_available", default=False)


def set_retry_available(value):
    """Update current invocation's remaining automatic-attempt policy."""
    _RETRY_AVAILABLE.set(bool(value))


def current_attempt_control():
    """Return only the explicitly bound coordinator context."""
    return _ATTEMPT.get()
