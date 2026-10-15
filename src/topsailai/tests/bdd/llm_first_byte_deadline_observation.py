"""Test-side provenance and callback completion observation for U3."""

from __future__ import annotations

import contextvars
import threading
from dataclasses import dataclass
from typing import Any, Callable


_CURRENT_INVOCATION = contextvars.ContextVar("u3_invocation", default=None)


@dataclass
class Invocation:
    """Identify one decorated model attempt and its sealed timing ticket."""

    token: object
    owner: Any = None
    expected_ticket: Any = None


class ProvenanceLedger:
    """Record callback provenance without deriving it from target tickets."""

    def __init__(self) -> None:
        """Initialize an isolated, thread-safe ledger."""
        self._lock = threading.RLock()
        self.invocations: list[Invocation] = []
        self.records: list[dict[str, Any]] = []

    def begin(self) -> Invocation:
        """Register an invocation before entering the decorated call."""
        invocation = Invocation(object())
        with self._lock:
            self.invocations.append(invocation)
        return invocation

    def bind(self, invocation: Invocation):
        """Bind an invocation to the current synchronous execution."""
        return _CURRENT_INVOCATION.set(invocation)

    def reset(self, token) -> None:
        """Restore the prior invocation after decorated finalization completes."""
        _CURRENT_INVOCATION.reset(token)

    def register_owner(self, owner: Any) -> None:
        """Associate an owner with the independently active invocation."""
        invocation = _CURRENT_INVOCATION.get()
        if invocation is None:
            raise AssertionError("owner registration lacks invocation")
        with self._lock:
            if not any(item is invocation for item in self.invocations):
                raise AssertionError("invocation does not belong to this ledger")
            if invocation.owner is not None:
                raise AssertionError("invocation has multiple owners")
            if any(item.owner is owner for item in self.invocations):
                raise AssertionError("owner was reused")
            invocation.owner = owner

    def seal_ticket(self, ticket: Any, owner: Any) -> None:
        """Seal the expected ticket from the independently registered owner."""
        invocation = self._invocation_for_owner(owner)
        with self._lock:
            if invocation.expected_ticket is not None:
                raise AssertionError("invocation has multiple timing tickets")
            invocation.expected_ticket = ticket

    def _invocation_for_owner(self, owner: Any) -> Invocation:
        """Return the unique invocation independently registered for an owner."""
        with self._lock:
            matches = [item for item in self.invocations if item.owner is owner]
        if len(matches) != 1:
            raise AssertionError("owner provenance is missing or ambiguous")
        return matches[0]

    def resolve(self, owner: Any = None) -> tuple[Invocation | None, str]:
        """Resolve provenance without suppressing observation of bad callbacks."""
        active = _CURRENT_INVOCATION.get()
        with self._lock:
            active_is_registered = any(item is active for item in self.invocations)
        if not active_is_registered:
            active = None
        if owner is not None:
            try:
                by_owner = self._invocation_for_owner(owner)
            except AssertionError:
                return None, "UNATTRIBUTED"
            if active is not None and by_owner is not active:
                return None, "CONFLICT"
            return by_owner, "owner"
        if active is not None and active.owner is not None:
            return active, "invocation"
        return None, "UNATTRIBUTED"

    def observe_callback(
        self,
        operation: str,
        delegate: Callable[[Any], Any],
        ticket: Any,
        *,
        on_completion: Callable[[dict[str, Any]], None] | None = None,
        owner_override: Any = ...,
    ) -> Any:
        """Delegate exactly once and record return or the exact exception."""
        raw_owner = _current_owner() if owner_override is ... else owner_override
        invocation, source = self.resolve(raw_owner)
        initiator = None if invocation is None else invocation.owner
        abandoned_before = bool(getattr(initiator, "_abandoned", False))
        record = {
            "operation": operation,
            "invocation": invocation,
            "source": source,
            "raw_initiator": raw_owner,
            "initiator": initiator,
            "expected_ticket": None if invocation is None else invocation.expected_ticket,
            "ticket": ticket,
            "abandoned_before": abandoned_before,
            "abandoned_after": abandoned_before,
            "completed": False,
            "error": None,
        }
        with self._lock:
            self.records.append(record)
        try:
            result = delegate(ticket)
        except BaseException as error:
            with self._lock:
                record["abandoned_after"] = bool(getattr(initiator, "_abandoned", False))
                record["error"] = error
            raise
        with self._lock:
            record["abandoned_after"] = bool(getattr(initiator, "_abandoned", False))
            record["completed"] = True
        if on_completion is not None:
            on_completion(dict(record))
        return result

    def record_start(self, owner: Any, ticket: Any) -> None:
        """Record the independently observed request-start checkpoint."""
        invocation = self._invocation_for_owner(owner)
        record = {
            "operation": "start",
            "invocation": invocation,
            "source": "owner",
            "raw_initiator": owner,
            "initiator": owner,
            "expected_ticket": ticket,
            "ticket": ticket,
            "abandoned_before": False,
            "abandoned_after": bool(getattr(owner, "_abandoned", False)),
            "completed": True,
            "error": None,
        }
        with self._lock:
            self.records.append(record)

    def validate(self, records: list[dict[str, Any]] | None = None) -> None:
        """Reject unattributed, conflicting, incomplete, or wrong-ticket records."""
        for record in self.snapshot() if records is None else records:
            if record["source"] in {"UNATTRIBUTED", "CONFLICT"}:
                raise AssertionError("callback provenance is not independently attributed")
            if not record["completed"]:
                raise AssertionError("callback did not complete successfully")
            expected = record["expected_ticket"]
            if expected is not None and record["ticket"] is not expected:
                raise AssertionError("callback targeted a different timing ticket")

    def snapshot(self) -> list[dict[str, Any]]:
        """Return an atomic snapshot of callback evidence."""
        with self._lock:
            return [dict(record) for record in self.records]


def _current_owner():
    """Import the production context lookup only when observing a callback."""
    from topsailai.ai_base.llm_control.response_ownership import current_response_owner
    return current_response_owner()


def current_invocation() -> Invocation | None:
    """Return the invocation registered for the current decorated call."""
    return _CURRENT_INVOCATION.get()
