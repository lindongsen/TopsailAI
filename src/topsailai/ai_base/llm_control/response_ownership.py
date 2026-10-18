"""Ownership tracking for provider responses that may outlive a timeout."""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterator


_LOG = logging.getLogger(__name__)


class _CloseState(Enum):
    """Track one response close operation without retrying ambiguous closes."""

    NOT_STARTED = auto()
    RUNNING = auto()
    SUCCEEDED = auto()
    FAILED = auto()


@dataclass(frozen=True)
class AttemptOutcome:
    """Represent a phase outcome without using sentinel values."""

    kind: str
    value: object = None


_UNSET = object()
_CURRENT_OWNER: ContextVar["AttemptResponseOwner | None"] = ContextVar(
    "topsailai_response_owner", default=None
)


class AttemptResponseOwner:
    """Own one attempt response until it is explicitly settled."""

    def __init__(self) -> None:
        """Initialize synchronized attempt state."""
        self._lock = threading.RLock()
        self._response = _UNSET
        self._outcomes = {
            "create": AttemptOutcome("NOT_READY"),
            "first_item": AttemptOutcome("NOT_READY"),
        }
        self._claimed = {"create": False, "first_item": False}
        self._abandoned = False
        self._close_state = _CloseState.NOT_STARTED
        self.close_error: BaseException | None = None
        self.disposal_error: BaseException | None = None
        self.primary_error: BaseException | None = None
        self.fetch_thread: threading.Thread | None = None
        self.create_thread: threading.Thread | None = None
        self.cleanup_thread: threading.Thread | None = None
        self.worker_finished_event = threading.Event()
        self.create_finished_event = threading.Event()
        self.fetch_finished_event = threading.Event()
        self.close_finished_event = threading.Event()

    def control_cleanup_settled(self) -> bool:
        """Confirm exact worker exit and unambiguous response disposal for control."""
        with self._lock:
            workers = (self.create_thread, self.fetch_thread, self.cleanup_thread)
            if any(worker is not None and worker.is_alive() for worker in workers):
                return False
            if self.disposal_error is not None:
                return False
            return (self._response is _UNSET
                    or self._close_state is _CloseState.SUCCEEDED)

    def publish_response(self, response) -> bool:
        """Publish response custody before any fallible response observation."""
        with self._lock:
            self._response = response
            abandoned = self._abandoned
        if abandoned:
            self.dispose(background=True)
            return False
        return True

    def publish_outcome(self, value, *, phase="create") -> bool:
        """Publish a value unless abandonment or a prior claim already won."""
        with self._lock:
            if self._abandoned or self._claimed[phase]:
                return False
            self._outcomes[phase] = AttemptOutcome("VALUE", value)
            return True

    def publish_error(self, error: BaseException, *, phase="create") -> bool:
        """Publish an exact exception outcome when the phase is still open."""
        with self._lock:
            if self._abandoned or self._claimed[phase]:
                accepted = False
            else:
                self._outcomes[phase] = AttemptOutcome("ERROR", error)
                accepted = True
        if not accepted:
            self._record_cleanup_failure(error, self.primary_error, context="late outcome")
        return accepted

    def publish_eof(self, *, phase="first_item") -> bool:
        """Publish an explicit end-of-stream outcome."""
        with self._lock:
            if self._abandoned or self._claimed[phase]:
                return False
            self._outcomes[phase] = AttemptOutcome("EOF")
            return True

    def take_outcome(self, *, phase="create") -> AttemptOutcome:
        """Atomically claim one phase outcome; later claims see NOT_READY."""
        with self._lock:
            if self._abandoned:
                return AttemptOutcome("ABANDONED")
            if self._claimed[phase]:
                return AttemptOutcome("NOT_READY")
            outcome = self._outcomes[phase]
            if outcome.kind == "NOT_READY":
                return outcome
            self._claimed[phase] = True
            self._outcomes[phase] = AttemptOutcome("NOT_READY")
            return outcome

    def abandon(self, primary: BaseException | None = None) -> None:
        """Mark this attempt stale before making retry or error decisions."""
        with self._lock:
            self._abandoned = True
            if primary is not None and self.primary_error is None:
                self.primary_error = primary
        self.dispose(primary=primary, background=True)

    def dispose(self, primary: BaseException | None = None, *, background: bool = False) -> None:
        """Close owned response once while preserving any primary exception."""
        with self._lock:
            if primary is not None and self.primary_error is None:
                self.primary_error = primary
            response = self._response
            if response is _UNSET or self._close_state is not _CloseState.NOT_STARTED:
                return
            self._close_state = _CloseState.RUNNING

        def close_response() -> None:
            """Close the underlying response and retain cleanup failures."""
            try:
                close = getattr(response, "close", None)
                if close is not None:
                    close()
            except BaseException as error:
                with self._lock:
                    self._close_state = _CloseState.FAILED
                self._record_cleanup_failure(error, primary, context="close")
            else:
                with self._lock:
                    self._close_state = _CloseState.SUCCEEDED
            finally:
                self.close_finished_event.set()

        if not background:
            close_response()
            return
        thread = None
        try:
            thread = threading.Thread(target=close_response, daemon=True)
            with self._lock:
                self.cleanup_thread = thread
            thread.start()
        except BaseException as error:
            with self._lock:
                self.close_error = error
                self._close_state = _CloseState.FAILED
                if thread is not None and thread.is_alive():
                    self.cleanup_thread = thread
            self._record_cleanup_failure(error, primary, context="schedule")
            if thread is None or not thread.is_alive():
                self.close_finished_event.set()

    def worker_finished(self, *, phase="create") -> None:
        """Record completion of the exact phase worker."""
        event = self.fetch_finished_event if phase == "first_item" else self.create_finished_event
        event.set()
        if phase == "create":
            self.worker_finished_event.set()

    def _record_cleanup_failure(self, error: BaseException, primary=None, *, context="cleanup") -> None:
        """Retain and safely diagnose cleanup failure without replacing primary."""
        with self._lock:
            if context in {"close", "schedule"}:
                self.disposal_error = error
            self.close_error = error
            owner_id = id(self)
            target = primary or self.primary_error
        try:
            _LOG.error(
                "response cleanup failed owner=%s context=%s error=%s",
                owner_id,
                context,
                type(error).__name__,
                exc_info=error,
            )
        except BaseException:
            pass
        if target is None:
            return
        try:
            target.add_note(
                f"response cleanup failed: {type(error).__name__}; owner={owner_id}"
            )
        except BaseException:
            pass
        try:
            setattr(target, "_topsailai_response_cleanup_owner", self)
        except BaseException:
            pass


@contextmanager
def response_ownership_scope() -> Iterator[AttemptResponseOwner]:
    """Install an attempt owner for the complete provider call scope."""
    owner = AttemptResponseOwner()
    token = _CURRENT_OWNER.set(owner)
    try:
        yield owner
    except BaseException as error:
        try:
            owner.abandon(error)
        except BaseException as cleanup_error:
            owner._record_cleanup_failure(cleanup_error, error, context="scope")
        raise
    else:
        owner.dispose(background=False)
    finally:
        _CURRENT_OWNER.reset(token)


@contextmanager
def bind_response_owner(owner: AttemptResponseOwner) -> Iterator[AttemptResponseOwner]:
    """Bind an existing response owner for a worker execution context."""
    token = _CURRENT_OWNER.set(owner)
    try:
        yield owner
    finally:
        _CURRENT_OWNER.reset(token)


def current_response_owner() -> AttemptResponseOwner | None:
    """Return the response owner bound to the current execution context."""
    return _CURRENT_OWNER.get()


class ClosingTimedIterator:
    """Expose an iterator while routing close to its underlying owner."""

    def __init__(self, iterator, owner: AttemptResponseOwner) -> None:
        """Initialize a timing wrapper with the original response owner."""
        self._iterator = iterator
        self._owner = owner

    def __iter__(self):
        """Return this close-aware iterator."""
        return self

    def __next__(self):
        """Read one item from the timing wrapper."""
        return next(self._iterator)

    def close(self) -> None:
        """Dispose the underlying response rather than only this wrapper."""
        self._owner.abandon()
