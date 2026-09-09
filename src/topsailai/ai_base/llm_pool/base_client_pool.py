"""Provider-neutral lifecycle management for reusable SDK clients."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from topsailai.logger.log_chat import logger

DEFAULT_CLIENT_POOL_CAPACITY = 32
_POOL_LOCK = threading.RLock()


def normalize_base_url(
    base_url: str | None,
    default: str = "",
) -> str:
    """Return the effective base URL with conservative trailing-slash cleanup."""
    normalized = (base_url or default).strip()
    while normalized.endswith("/") and not normalized.endswith("://"):
        normalized = normalized[:-1]
    return normalized or default


def _fingerprint(value: str) -> str:
    """Return a stable SHA-256 fingerprint without retaining the input in a key."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _options_fingerprint(options: tuple[tuple[str, Any], ...]) -> str:
    """Return a deterministic fingerprint for client-construction options."""
    encoded = json.dumps(
        options,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda value: {
            "type": f"{type(value).__module__}.{type(value).__qualname__}",
            "repr": repr(value),
        },
    )
    return _fingerprint(encoded)


def _normalize_options(
    options: Mapping[str, Any] | tuple[tuple[str, Any], ...] | None,
) -> tuple[tuple[str, Any], ...]:
    """Convert supported option collections into an immutable ordered tuple."""
    if options is None:
        return ()
    items = options.items() if isinstance(options, Mapping) else options
    return tuple(sorted(items, key=lambda item: item[0]))


@dataclass
class ClientPoolEntry:
    """Mutable pool-owned state for one client generation."""

    client: Any
    key: Any
    generation: int
    creator_pid: int
    ref_count: int
    last_used: float
    invalidated: bool = False
    closed: bool = False


@dataclass
class _HandleReleaseState:
    """Mutable synchronization state retained inside an immutable handle."""

    released: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass(frozen=True)
class ClientPoolHandle:
    """Immutable caller lease for one pooled client."""

    client: Any
    key: Any
    generation: int
    _release_callback: Callable[[], None] = field(repr=False, compare=False)
    _release_state: _HandleReleaseState = field(
        default_factory=_HandleReleaseState,
        repr=False,
        compare=False,
    )

    def release(self) -> None:
        """Release this lease exactly once, including under concurrent calls."""
        with self._release_state.lock:
            if self._release_state.released:
                return
            self._release_state.released = True
        self._release_callback()

    def __enter__(self) -> "ClientPoolHandle":
        """Return this handle for deterministic context-managed ownership."""
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Release this handle when leaving a context manager."""
        self.release()


class BaseClientPool:
    """Thread-safe, process-local pool of reusable provider clients."""

    handle_class = ClientPoolHandle
    pool_name = "client"

    def __init__(
        self,
        capacity: int = DEFAULT_CLIENT_POOL_CAPACITY,
        client_factory: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        pid_getter: Callable[[], int] = os.getpid,
    ) -> None:
        """Initialize an isolated pool with injectable deterministic dependencies."""
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        if client_factory is None:
            raise ValueError("client_factory is required")
        self._capacity = capacity
        self._client_factory = client_factory
        self._clock = clock
        self._pid_getter = pid_getter
        self._pid = pid_getter()
        self._entries: dict[Any, ClientPoolEntry] = {}
        self._retired_entries: dict[int, ClientPoolEntry] = {}
        self._next_generation = 0
        self._closed = False

    def get_or_create(self, config) -> ClientPoolHandle:
        """Acquire a lease for the current client matching the configuration."""
        return self.acquire(config)

    def acquire(self, config) -> ClientPoolHandle:
        """Acquire a reference-counted handle, creating one client when absent."""
        key = self._key_for_config(config)
        clients_to_close: list[ClientPoolEntry] = []
        with _POOL_LOCK:
            self._ensure_current_process_locked()
            if self._closed:
                self._closed = False

            entry = self._entries.get(key)
            if entry is None:
                client = self._client_factory(**self._constructor_kwargs(config))
                generation = self._next_generation
                self._next_generation += 1
                entry = ClientPoolEntry(
                    client=client,
                    key=key,
                    generation=generation,
                    creator_pid=self._pid,
                    ref_count=0,
                    last_used=self._clock(),
                )
                self._entries[key] = entry
                logger.debug(
                    "%s pool miss: %s",
                    self.pool_name,
                    self._log_identity(key),
                )
            else:
                logger.debug(
                    "%s pool hit: %s",
                    self.pool_name,
                    self._log_identity(key),
                )

            entry.ref_count += 1
            entry.last_used = self._clock()
            clients_to_close.extend(self._evict_to_capacity_locked())
            handle = self.handle_class(
                client=entry.client,
                key=entry.key,
                generation=entry.generation,
                _release_callback=lambda entry=entry: self._release_entry(entry),
            )

        self._close_entries(clients_to_close)
        return handle

    def release(self, handle: ClientPoolHandle) -> None:
        """Release a handle idempotently."""
        handle.release()

    def invalidate(self, config_or_key) -> bool:
        """Retire the current generation so the next acquire creates a new one."""
        key = (
            self._key_for_config(config_or_key)
            if self._is_config(config_or_key)
            else config_or_key
        )
        clients_to_close: list[ClientPoolEntry] = []
        with _POOL_LOCK:
            self._ensure_current_process_locked()
            entry = self._entries.pop(key, None)
            if entry is None:
                return False
            entry.invalidated = True
            if entry.ref_count == 0:
                clients_to_close.append(entry)
            else:
                self._retired_entries[id(entry)] = entry
            logger.debug(
                "%s pool invalidated: %s",
                self.pool_name,
                self._log_identity(key),
            )

        self._close_entries(clients_to_close)
        return True

    def close_idle(self, idle_seconds: float = 0.0) -> int:
        """Close current clients that are unleased and idle for the given duration."""
        if idle_seconds < 0:
            raise ValueError("idle_seconds must not be negative")
        clients_to_close: list[ClientPoolEntry] = []
        with _POOL_LOCK:
            self._ensure_current_process_locked()
            now = self._clock()
            for key, entry in list(self._entries.items()):
                if entry.ref_count != 0 or now - entry.last_used < idle_seconds:
                    continue
                del self._entries[key]
                clients_to_close.append(entry)

        self._close_entries(clients_to_close)
        return len(clients_to_close)

    def close_all(self) -> int:
        """Remove and close every client owned by the current process exactly once."""
        with _POOL_LOCK:
            self._ensure_current_process_locked()
            entries = list(self._entries.values()) + list(self._retired_entries.values())
            self._entries.clear()
            self._retired_entries.clear()
            self._closed = True

        self._close_entries(entries)
        return len(entries)

    def _key_for_config(self, config):
        """Build a hashable provider-owned key from one client configuration."""
        return config.to_key()

    def _constructor_kwargs(self, config) -> dict[str, Any]:
        """Build provider-owned keyword arguments for the client factory."""
        return config.constructor_kwargs()

    def _is_config(self, value) -> bool:
        """Return whether a value follows the provider configuration contract."""
        return callable(getattr(value, "to_key", None))

    def _release_entry(self, entry: ClientPoolEntry) -> None:
        """Release one entry and close it when its retired generation becomes idle."""
        clients_to_close: list[ClientPoolEntry] = []
        with _POOL_LOCK:
            self._ensure_current_process_locked()
            if entry.creator_pid != self._pid or entry.closed or entry.ref_count == 0:
                return
            entry.ref_count -= 1
            entry.last_used = self._clock()
            if entry.invalidated and entry.ref_count == 0:
                self._retired_entries.pop(id(entry), None)
                clients_to_close.append(entry)
            clients_to_close.extend(self._evict_to_capacity_locked())

        self._close_entries(clients_to_close)

    def _ensure_current_process_locked(self) -> None:
        """Abandon inherited transports after fork without closing parent resources."""
        current_pid = self._pid_getter()
        if current_pid == self._pid:
            return
        self._entries = {}
        self._retired_entries = {}
        self._next_generation = 0
        self._pid = current_pid
        self._closed = False
        logger.debug("%s pool reset after PID change", self.pool_name)

    def _evict_to_capacity_locked(self) -> list[ClientPoolEntry]:
        """Remove least-recent idle entries until the configured capacity is met."""
        evicted: list[ClientPoolEntry] = []
        while len(self._entries) > self._capacity:
            idle_entries = [entry for entry in self._entries.values() if entry.ref_count == 0]
            if not idle_entries:
                break
            entry = min(idle_entries, key=lambda candidate: candidate.last_used)
            self._entries.pop(entry.key, None)
            evicted.append(entry)
            logger.debug(
                "%s pool evicted: %s",
                self.pool_name,
                self._log_identity(entry.key),
            )
        return evicted

    def _close_entries(self, entries: list[ClientPoolEntry]) -> None:
        """Close removed clients without holding the registry lock."""
        for entry in entries:
            with _POOL_LOCK:
                if entry.closed or entry.creator_pid != self._pid:
                    continue
                entry.closed = True
            try:
                self._close_client(entry.client)
            except Exception as error:
                logger.warning(
                    "failed to close %s (%s); error_type=%s",
                    self.pool_name,
                    self._log_identity(entry.key),
                    type(error).__name__,
                )

    def _close_client(self, client) -> None:
        """Close one provider client; subclasses may override the close contract."""
        client.close()

    @staticmethod
    def _log_identity(key) -> str:
        """Return non-sensitive default identity text for diagnostics."""
        return f"key_type={type(key).__module__}.{type(key).__qualname__}"
