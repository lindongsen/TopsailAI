"""Process-local pool for reusable synchronous OpenAI SDK clients."""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

import openai

from topsailai.logger.log_chat import logger

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_CLIENT_POOL_CAPACITY = 32
_CLIENT_KIND_SYNC = "sync"
_POOL_LOCK = threading.RLock()


def normalize_base_url(base_url: str | None) -> str:
    """Return the effective base URL with conservative trailing-slash cleanup."""
    normalized = (base_url or DEFAULT_OPENAI_BASE_URL).strip()
    while normalized.endswith("/") and not normalized.endswith("://"):
        normalized = normalized[:-1]
    return normalized or DEFAULT_OPENAI_BASE_URL


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


@dataclass(frozen=True)
class OpenAIClientKey:
    """Secret-free identity of one reusable OpenAI SDK client generation."""

    client_type: str
    normalized_base_url: str
    api_key_fingerprint: str
    organization: str | None
    project: str | None
    client_options_fingerprint: str


@dataclass(frozen=True)
class OpenAIClientConfig:
    """Immutable effective configuration used to construct an OpenAI client."""

    api_key: str = field(default="", repr=False)
    base_url: str = DEFAULT_OPENAI_BASE_URL
    organization: str | None = None
    project: str | None = None
    client_type: str = _CLIENT_KIND_SYNC
    client_options: tuple[tuple[str, Any], ...] = ()
    model: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        """Normalize immutable configuration fields at construction time."""
        object.__setattr__(self, "base_url", normalize_base_url(self.base_url))
        object.__setattr__(self, "client_options", _normalize_options(self.client_options))
        if self.client_type != _CLIENT_KIND_SYNC:
            raise ValueError(f"unsupported OpenAI client type: {self.client_type}")

    def to_key(self) -> OpenAIClientKey:
        """Build the secret-free cache key; model is intentionally excluded."""
        return OpenAIClientKey(
            client_type=self.client_type,
            normalized_base_url=self.base_url,
            api_key_fingerprint=_fingerprint(self.api_key),
            organization=self.organization,
            project=self.project,
            client_options_fingerprint=_options_fingerprint(self.client_options),
        )

    def constructor_kwargs(self) -> dict[str, Any]:
        """Return keyword arguments for constructing the root SDK client."""
        kwargs = dict(self.client_options)
        kwargs["api_key"] = self.api_key
        kwargs["base_url"] = self.base_url
        if self.organization is not None:
            kwargs["organization"] = self.organization
        if self.project is not None:
            kwargs["project"] = self.project
        return kwargs


@dataclass
class _OpenAIClientEntry:
    """Mutable pool-owned state for one client generation."""

    client: Any
    key: OpenAIClientKey
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
class OpenAIClientHandle:
    """Immutable caller lease for a pooled root OpenAI client."""

    client: Any
    key: OpenAIClientKey
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

    def __enter__(self) -> "OpenAIClientHandle":
        """Return this handle for deterministic context-managed ownership."""
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Release this handle when leaving a context manager."""
        self.release()


class OpenAIClientPool:
    """Thread-safe, process-local pool of reusable root OpenAI clients."""

    def __init__(
        self,
        capacity: int = DEFAULT_OPENAI_CLIENT_POOL_CAPACITY,
        client_factory: Callable[..., Any] = openai.OpenAI,
        clock: Callable[[], float] = time.monotonic,
        pid_getter: Callable[[], int] = os.getpid,
    ) -> None:
        """Initialize an isolated pool with injectable deterministic dependencies."""
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self._capacity = capacity
        self._client_factory = client_factory
        self._clock = clock
        self._pid_getter = pid_getter
        self._pid = pid_getter()
        self._entries: dict[OpenAIClientKey, _OpenAIClientEntry] = {}
        self._retired_entries: dict[int, _OpenAIClientEntry] = {}
        self._next_generation = 0
        self._closed = False

    def get_or_create(self, config: OpenAIClientConfig) -> OpenAIClientHandle:
        """Acquire a lease for the current client matching the configuration."""
        return self.acquire(config)

    def acquire(self, config: OpenAIClientConfig) -> OpenAIClientHandle:
        """Acquire a reference-counted handle, creating one client when absent."""
        key = config.to_key()
        clients_to_close: list[_OpenAIClientEntry] = []
        with _POOL_LOCK:
            self._ensure_current_process_locked()
            if self._closed:
                self._closed = False

            entry = self._entries.get(key)
            if entry is None:
                client = self._client_factory(**config.constructor_kwargs())
                generation = self._next_generation
                self._next_generation += 1
                entry = _OpenAIClientEntry(
                    client=client,
                    key=key,
                    generation=generation,
                    creator_pid=self._pid,
                    ref_count=0,
                    last_used=self._clock(),
                )
                self._entries[key] = entry
                logger.debug("OpenAI client pool miss: %s", self._log_identity(key))
            else:
                logger.debug("OpenAI client pool hit: %s", self._log_identity(key))

            entry.ref_count += 1
            entry.last_used = self._clock()
            clients_to_close.extend(self._evict_to_capacity_locked())
            handle = OpenAIClientHandle(
                client=entry.client,
                key=entry.key,
                generation=entry.generation,
                _release_callback=lambda entry=entry: self._release_entry(entry),
            )

        self._close_entries(clients_to_close)
        return handle

    def release(self, handle: OpenAIClientHandle) -> None:
        """Release a handle idempotently."""
        handle.release()

    def invalidate(
        self,
        config_or_key: OpenAIClientConfig | OpenAIClientKey,
    ) -> bool:
        """Retire the current generation so the next acquire creates a new one."""
        key = (
            config_or_key.to_key()
            if isinstance(config_or_key, OpenAIClientConfig)
            else config_or_key
        )
        clients_to_close: list[_OpenAIClientEntry] = []
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
            logger.debug("OpenAI client pool invalidated: %s", self._log_identity(key))

        self._close_entries(clients_to_close)
        return True

    def close_idle(self, idle_seconds: float = 0.0) -> int:
        """Close current clients that are unleased and idle for the given duration."""
        if idle_seconds < 0:
            raise ValueError("idle_seconds must not be negative")
        clients_to_close: list[_OpenAIClientEntry] = []
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

    def _release_entry(self, entry: _OpenAIClientEntry) -> None:
        """Release one entry and close it when its retired generation becomes idle."""
        clients_to_close: list[_OpenAIClientEntry] = []
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
        logger.debug("OpenAI client pool reset after PID change")

    def _evict_to_capacity_locked(self) -> list[_OpenAIClientEntry]:
        """Remove least-recent idle entries until the configured capacity is met."""
        evicted: list[_OpenAIClientEntry] = []
        while len(self._entries) > self._capacity:
            idle_entries = [entry for entry in self._entries.values() if entry.ref_count == 0]
            if not idle_entries:
                break
            entry = min(idle_entries, key=lambda candidate: candidate.last_used)
            self._entries.pop(entry.key, None)
            evicted.append(entry)
            logger.debug("OpenAI client pool evicted: %s", self._log_identity(entry.key))
        return evicted

    def _close_entries(self, entries: list[_OpenAIClientEntry]) -> None:
        """Close removed clients without holding the registry lock."""
        for entry in entries:
            with _POOL_LOCK:
                if entry.closed or entry.creator_pid != self._pid:
                    continue
                entry.closed = True
            try:
                entry.client.close()
            except Exception as error:
                logger.warning(
                    "failed to close OpenAI client (%s); error_type=%s",
                    self._log_identity(entry.key),
                    type(error).__name__,
                )

    @staticmethod
    def _log_identity(key: OpenAIClientKey) -> str:
        """Return safe, concise cache identity text for diagnostics."""
        return (
            f"type={key.client_type} base_url={key.normalized_base_url} "
            f"api_key_sha256={key.api_key_fingerprint[:8]}"
        )


default_openai_client_pool = OpenAIClientPool()


def get_or_create(config: OpenAIClientConfig) -> OpenAIClientHandle:
    """Acquire a handle from the process-wide default pool."""
    return default_openai_client_pool.get_or_create(config)


def acquire(config: OpenAIClientConfig) -> OpenAIClientHandle:
    """Acquire a handle from the process-wide default pool."""
    return default_openai_client_pool.acquire(config)


def release(handle: OpenAIClientHandle) -> None:
    """Release a handle obtained from the process-wide default pool."""
    default_openai_client_pool.release(handle)


def invalidate(config_or_key: OpenAIClientConfig | OpenAIClientKey) -> bool:
    """Invalidate a current generation in the process-wide default pool."""
    return default_openai_client_pool.invalidate(config_or_key)


def close_idle(idle_seconds: float = 0.0) -> int:
    """Close idle clients in the process-wide default pool."""
    return default_openai_client_pool.close_idle(idle_seconds)


def close_all() -> int:
    """Close all clients in the process-wide default pool."""
    return default_openai_client_pool.close_all()


atexit.register(close_all)
