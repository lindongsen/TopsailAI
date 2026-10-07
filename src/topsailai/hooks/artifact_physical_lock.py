"""Exact-token non-blocking serialization for physical artifact operations."""

from __future__ import annotations

import threading


class ExactPhysicalLock:
    """Track physical-operation ownership by an immutable caller token."""

    def __init__(self, coordination_lock: threading.RLock) -> None:
        """Create an unlocked serializer coordinated by the manager lock."""
        self._coordination_lock = coordination_lock
        self._owner: object | None = None
        self._legacy_owner: tuple[int, object] | None = None

    def acquire(self, blocking: bool = True, *, owner: object | None = None) -> bool:
        """Acquire immediately and bind ownership to an exact token."""
        if blocking:
            raise ValueError("ExactPhysicalLock supports only non-blocking acquisition")
        token = object() if owner is None else owner
        with self._coordination_lock:
            if self._owner is not None:
                return False
            self._owner = token
            if owner is None:
                self._legacy_owner = (threading.get_ident(), token)
            return True

    def release(self, *, owner: object | None = None) -> None:
        """Release only the exact explicit or current-thread legacy owner."""
        with self._coordination_lock:
            token = owner
            if token is None:
                legacy = self._legacy_owner
                if legacy is None or legacy[0] != threading.get_ident():
                    raise RuntimeError("release unlocked physical lock")
                token = legacy[1]
            if self._owner is not token:
                raise RuntimeError("release unowned physical lock")
            self._owner = None
            self._legacy_owner = None

    def release_if_owned(self, owner: object) -> bool:
        """Release only when the supplied exact token currently owns the lock."""
        with self._coordination_lock:
            if self._owner is not owner:
                return False
            self._owner = None
            self._legacy_owner = None
            return True

    def locked(self) -> bool:
        """Return whether any exact owner currently holds serialization."""
        with self._coordination_lock:
            return self._owner is not None
