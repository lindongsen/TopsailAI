"""Thread-safe, Agent-scoped runtime state storage."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import json
import math
import re
import threading
import time
from typing import Any, Callable
import uuid


_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_MAX_OWNER_LENGTH = 256
_MAX_CAPACITY = 10000
_DEFAULT_ACTIVE_CAPACITY = 128
_DEFAULT_HISTORY_CAPACITY = 50


@dataclass(frozen=True)
class RuntimeDataLease:
    """Identify one exact generation of an active runtime state."""

    key: str
    owner_id: str
    generation: str


@dataclass(frozen=True)
class RuntimeDataSnapshot:
    """Describe one detached active runtime state."""

    key: str
    owner_id: str
    value: Any
    public: bool
    revision: int
    created_at_ms: int
    updated_at_ms: int


@dataclass(frozen=True)
class RuntimeDataHistorySnapshot:
    """Describe one detached settled runtime state."""

    key: str
    owner_id: str
    value: Any
    public: bool
    revision: int
    created_at_ms: int
    updated_at_ms: int
    settled_at_ms: int
    outcome: str


@dataclass
class _ActiveState:
    """Hold one mutable state generation inside the Store lock."""

    lease: RuntimeDataLease
    value: Any
    public: bool
    revision: int
    created_at_ms: int
    updated_at_ms: int


class RuntimeDataStore:
    """Manage bounded runtime state without session persistence."""

    def __init__(
        self,
        *,
        active_capacity: int = _DEFAULT_ACTIVE_CAPACITY,
        history_capacity: int = _DEFAULT_HISTORY_CAPACITY,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        """Create an empty Store with fixed active and history capacities."""
        self._active_capacity = self._validate_capacity(
            "active_capacity", active_capacity, allow_zero=False
        )
        self._history_capacity = self._validate_capacity(
            "history_capacity", history_capacity, allow_zero=True
        )
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._active: dict[str, _ActiveState] = {}
        self._history: deque[RuntimeDataHistorySnapshot] = deque(
            maxlen=self._history_capacity or None
        )
        self._lock = threading.RLock()

    @staticmethod
    def _validate_capacity(name: str, value: int, *, allow_zero: bool) -> int:
        """Validate a bounded constructor capacity."""
        minimum = 0 if allow_zero else 1
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
        if value < minimum or value > _MAX_CAPACITY:
            raise ValueError(f"{name} must be between {minimum} and {_MAX_CAPACITY}")
        return value

    @staticmethod
    def _validate_key(key: str) -> str:
        """Return a validated namespaced runtime-state key."""
        if not isinstance(key, str) or not _KEY_PATTERN.fullmatch(key):
            raise ValueError("key must be a lowercase namespaced identifier")
        return key

    @staticmethod
    def _validate_owner(owner_id: str) -> str:
        """Return a validated non-empty owner identifier."""
        if not isinstance(owner_id, str):
            raise ValueError("owner_id must be a non-empty string")
        if not owner_id.strip() or len(owner_id) > _MAX_OWNER_LENGTH:
            raise ValueError("owner_id must be a non-empty string of at most 256 characters")
        return owner_id

    @staticmethod
    def _validate_outcome(outcome: str) -> str:
        """Return a validated settlement outcome."""
        if not isinstance(outcome, str) or not outcome.strip():
            raise ValueError("outcome must be a non-empty string")
        return outcome

    @staticmethod
    def _detach_value(value: Any) -> Any:
        """Validate and detach one finite JSON-compatible value."""
        seen: set[int] = set()

        def validate(item: Any) -> None:
            """Reject values that JSON would coerce instead of preserve."""
            if item is None or isinstance(item, (str, bool, int)):
                return
            if isinstance(item, float):
                if not math.isfinite(item):
                    raise ValueError("value must be finite JSON-compatible data")
                return
            if not isinstance(item, (dict, list)):
                raise ValueError("value must be finite JSON-compatible data")
            identity = id(item)
            if identity in seen:
                raise ValueError("value must be finite JSON-compatible data")
            seen.add(identity)
            try:
                if isinstance(item, dict):
                    if any(not isinstance(key, str) for key in item):
                        raise ValueError("value must be finite JSON-compatible data")
                    for nested in item.values():
                        validate(nested)
                else:
                    for nested in item:
                        validate(nested)
            finally:
                seen.remove(identity)

        validate(value)
        try:
            encoded = json.dumps(value, allow_nan=False, separators=(",", ":"))
            return json.loads(encoded)
        except (TypeError, ValueError, OverflowError, RecursionError) as error:
            raise ValueError("value must be finite JSON-compatible data") from error

    def _now_ms(self) -> int:
        """Read and validate the injected wall-clock seam."""
        value = self._clock_ms()
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("clock_ms must return a non-negative integer")
        return value

    @staticmethod
    def _active_snapshot(state: _ActiveState) -> RuntimeDataSnapshot:
        """Build a detached snapshot from one active state."""
        return RuntimeDataSnapshot(
            key=state.lease.key,
            owner_id=state.lease.owner_id,
            value=deepcopy(state.value),
            public=state.public,
            revision=state.revision,
            created_at_ms=state.created_at_ms,
            updated_at_ms=state.updated_at_ms,
        )

    @staticmethod
    def _history_snapshot(
        state: _ActiveState, *, settled_at_ms: int, outcome: str
    ) -> RuntimeDataHistorySnapshot:
        """Build a detached settled snapshot from one active state."""
        return RuntimeDataHistorySnapshot(
            key=state.lease.key,
            owner_id=state.lease.owner_id,
            value=deepcopy(state.value),
            public=state.public,
            revision=state.revision,
            created_at_ms=state.created_at_ms,
            updated_at_ms=state.updated_at_ms,
            settled_at_ms=settled_at_ms,
            outcome=outcome,
        )

    def activate(
        self,
        key: str,
        owner_id: str,
        value: Any,
        *,
        public: bool = True,
    ) -> RuntimeDataLease:
        """Activate one unowned key and return its exact-generation lease."""
        key = self._validate_key(key)
        owner_id = self._validate_owner(owner_id)
        detached_value = self._detach_value(value)
        if not isinstance(public, bool):
            raise TypeError("public must be a boolean")
        now_ms = self._now_ms()
        with self._lock:
            if key in self._active:
                raise RuntimeError(f"runtime state is already active: {key}")
            if len(self._active) >= self._active_capacity:
                raise RuntimeError("runtime state capacity is full")
            lease = RuntimeDataLease(
                key=key,
                owner_id=owner_id,
                generation=uuid.uuid4().hex,
            )
            self._active[key] = _ActiveState(
                lease=lease,
                value=detached_value,
                public=public,
                revision=1,
                created_at_ms=now_ms,
                updated_at_ms=now_ms,
            )
            return lease

    def update(self, lease: RuntimeDataLease, value: Any) -> bool:
        """Update a matching active generation and reject stale leases."""
        if not isinstance(lease, RuntimeDataLease):
            return False
        detached_value = self._detach_value(value)
        now_ms = self._now_ms()
        with self._lock:
            state = self._active.get(lease.key)
            if state is None or state.lease != lease:
                return False
            state.value = detached_value
            state.revision += 1
            state.updated_at_ms = max(state.updated_at_ms, now_ms)
            return True

    def deactivate(self, lease: RuntimeDataLease, *, outcome: str) -> bool:
        """Settle a matching generation and retain bounded history."""
        if not isinstance(lease, RuntimeDataLease):
            return False
        outcome = self._validate_outcome(outcome)
        settled_at_ms = self._now_ms()
        with self._lock:
            state = self._active.get(lease.key)
            if state is None or state.lease != lease:
                return False
            del self._active[lease.key]
            if self._history_capacity:
                self._history.append(
                    self._history_snapshot(
                        state,
                        settled_at_ms=max(state.updated_at_ms, settled_at_ms),
                        outcome=outcome,
                    )
                )
            return True

    def get(
        self, key: str, *, public_only: bool = True
    ) -> RuntimeDataSnapshot | None:
        """Return one detached active snapshot when visible."""
        key = self._validate_key(key)
        with self._lock:
            state = self._active.get(key)
            if state is None or (public_only and not state.public):
                return None
            return self._active_snapshot(state)

    def snapshot(self, *, public_only: bool = True) -> tuple[RuntimeDataSnapshot, ...]:
        """Return detached active snapshots ordered by key."""
        with self._lock:
            return tuple(
                self._active_snapshot(state)
                for key, state in sorted(self._active.items())
                if not public_only or state.public
            )

    def history(
        self,
        key: str | None = None,
        *,
        public_only: bool = True,
    ) -> tuple[RuntimeDataHistorySnapshot, ...]:
        """Return detached settled snapshots in settlement order."""
        if key is not None:
            key = self._validate_key(key)
        with self._lock:
            return tuple(
                deepcopy(item)
                for item in self._history
                if (key is None or item.key == key)
                and (not public_only or item.public)
            )
