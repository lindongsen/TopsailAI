"""Unit tests for Agent-scoped runtime state storage.

Author: DawsonLin
"""

from concurrent.futures import ThreadPoolExecutor
import math
import threading

import pytest

from topsailai.ai_base.runtime_data import RuntimeDataLease, RuntimeDataStore


class Clock:
    """Return deterministic millisecond values for Store tests."""

    def __init__(self) -> None:
        """Initialize the deterministic clock."""
        self.value = 1000
        self._lock = threading.Lock()

    def __call__(self) -> int:
        """Return the next deterministic timestamp."""
        with self._lock:
            current = self.value
            self.value += 1
            return current


def test_activate_update_and_deactivate_one_state() -> None:
    """Preserve timestamps and revision across one complete lifecycle."""
    store = RuntimeDataStore(clock_ms=Clock())
    source_value = {"failed_attempts": 3, "nested": ["initial"]}

    lease = store.activate("llm.request.retrying", "request-1", source_value)
    source_value["nested"].append("caller mutation")
    first = store.get("llm.request.retrying")

    assert first is not None
    assert first.revision == 1
    assert first.value == {"failed_attempts": 3, "nested": ["initial"]}
    assert store.update(lease, {"failed_attempts": 4}) is True
    second = store.get("llm.request.retrying")
    assert second is not None
    assert second.revision == 2
    assert second.created_at_ms == first.created_at_ms
    assert second.updated_at_ms > first.updated_at_ms

    assert store.deactivate(lease, outcome="recovered") is True
    assert store.get("llm.request.retrying") is None
    history = store.history("llm.request.retrying")
    assert len(history) == 1
    assert history[0].revision == 2
    assert history[0].outcome == "recovered"
    assert history[0].settled_at_ms >= history[0].updated_at_ms


def test_repeated_deactivate_is_idempotent() -> None:
    """Do not duplicate history when cleanup repeats."""
    store = RuntimeDataStore()
    lease = store.activate("llm.request.retrying", "request-1", {})

    assert store.deactivate(lease, outcome="failed") is True
    assert store.deactivate(lease, outcome="failed") is False
    assert len(store.history()) == 1
    assert store.update(lease, {}) is False


@pytest.mark.parametrize(
    "key",
    ["", " ", "runtime", ".runtime.data", "runtime.data.", "Runtime.data", "a..b", 3],
)
def test_invalid_keys_are_rejected_without_mutation(key: object) -> None:
    """Reject malformed keys before retaining any state."""
    store = RuntimeDataStore()

    with pytest.raises(ValueError, match="namespaced"):
        store.activate(key, "owner", {})  # type: ignore[arg-type]

    assert store.snapshot(public_only=False) == ()
    assert store.history(public_only=False) == ()


@pytest.mark.parametrize("owner", ["", " ", 3, "x" * 257])
def test_invalid_owners_are_rejected_without_mutation(owner: object) -> None:
    """Reject invalid owner identifiers before mutation."""
    store = RuntimeDataStore()

    with pytest.raises(ValueError, match="owner_id"):
        store.activate("runtime.test", owner, {})  # type: ignore[arg-type]

    assert store.snapshot(public_only=False) == ()


@pytest.mark.parametrize(
    "value",
    [{"bad": object()}, {1: "bad"}, {"bad": math.inf}, {"bad": math.nan}],
)
def test_non_json_values_are_rejected_without_mutation(value: object) -> None:
    """Reject unsupported payloads without leaving partial state."""
    store = RuntimeDataStore()

    with pytest.raises(ValueError, match="JSON-compatible"):
        store.activate("runtime.test", "owner", value)

    assert store.snapshot(public_only=False) == ()


def test_recursive_value_is_rejected_without_mutation() -> None:
    """Reject recursive containers without retaining partial state."""
    store = RuntimeDataStore()
    value: list[object] = []
    value.append(value)

    with pytest.raises(ValueError, match="JSON-compatible"):
        store.activate("runtime.test", "owner", value)

    assert store.snapshot(public_only=False) == ()


def test_private_state_requires_internal_query() -> None:
    """Hide private active and settled state from public queries."""
    store = RuntimeDataStore()
    lease = store.activate("runtime.private", "owner", {"secret": False}, public=False)

    assert store.get("runtime.private") is None
    assert store.snapshot() == ()
    assert store.get("runtime.private", public_only=False) is not None
    assert store.deactivate(lease, outcome="done") is True
    assert store.history() == ()
    assert len(store.history(public_only=False)) == 1


def test_active_key_rejects_a_second_owner_without_overwrite() -> None:
    """Preserve the current owner when another activation uses the same key."""
    store = RuntimeDataStore()
    original = store.activate("runtime.test", "owner-1", {"owner": 1})

    with pytest.raises(RuntimeError, match="already active"):
        store.activate("runtime.test", "owner-2", {"owner": 2})

    current = store.get("runtime.test")
    assert current is not None
    assert current.owner_id == original.owner_id
    assert current.value == {"owner": 1}


def test_stale_lease_cannot_change_replacement_generation() -> None:
    """Protect a replacement owner from delayed old-owner operations."""
    store = RuntimeDataStore()
    old_lease = store.activate("runtime.test", "owner", {"generation": "old"})
    assert store.deactivate(old_lease, outcome="done") is True
    new_lease = store.activate("runtime.test", "owner", {"generation": "new"})
    guessed = RuntimeDataLease(
        key=new_lease.key,
        owner_id=new_lease.owner_id,
        generation="guessed",
    )

    assert store.update(old_lease, {"generation": "corrupt"}) is False
    assert store.deactivate(old_lease, outcome="stale") is False
    assert store.update(guessed, {"generation": "corrupt"}) is False
    assert store.deactivate(guessed, outcome="stale") is False
    current = store.get("runtime.test")
    assert current is not None
    assert current.value == {"generation": "new"}
    assert current.revision == 1


def test_active_capacity_rejects_new_state_without_eviction() -> None:
    """Reject overflow without removing a currently owned state."""
    store = RuntimeDataStore(active_capacity=1)
    store.activate("runtime.first", "owner-1", {})

    with pytest.raises(RuntimeError, match="capacity"):
        store.activate("runtime.second", "owner-2", {})

    assert [item.key for item in store.snapshot()] == ["runtime.first"]


def test_history_retains_only_newest_configured_count() -> None:
    """Evict oldest settled records when bounded history is full."""
    store = RuntimeDataStore(history_capacity=3)

    for index in range(5):
        lease = store.activate(f"runtime.item_{index}", f"owner-{index}", {"index": index})
        assert store.deactivate(lease, outcome="done") is True

    assert [item.value["index"] for item in store.history()] == [2, 3, 4]
    assert store.snapshot() == ()


def test_zero_history_capacity_retains_no_records() -> None:
    """Allow callers to disable settled-history retention."""
    store = RuntimeDataStore(history_capacity=0)
    lease = store.activate("runtime.test", "owner", {})

    assert store.deactivate(lease, outcome="done") is True
    assert store.snapshot() == ()
    assert store.history() == ()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("active_capacity", 0),
        ("active_capacity", -1),
        ("history_capacity", -1),
        ("history_capacity", True),
        ("history_capacity", 1.5),
        ("history_capacity", 10001),
    ],
)
def test_invalid_capacities_are_rejected(name: str, value: object) -> None:
    """Reject invalid bounded capacities during construction."""
    with pytest.raises((TypeError, ValueError)):
        RuntimeDataStore(**{name: value})  # type: ignore[arg-type]


def test_returned_snapshots_cannot_mutate_store() -> None:
    """Deeply detach active and history payloads from callers."""
    store = RuntimeDataStore()
    lease = store.activate("runtime.test", "owner", {"nested": [1]})
    active = store.get("runtime.test")
    assert active is not None
    active.value["nested"].append(2)

    assert store.get("runtime.test").value == {"nested": [1]}  # type: ignore[union-attr]
    assert store.deactivate(lease, outcome="done") is True
    history = store.history()
    history[0].value["nested"].append(3)
    assert store.history()[0].value == {"nested": [1]}


def test_snapshot_order_is_deterministic() -> None:
    """Order active keys lexically and history by settlement."""
    store = RuntimeDataStore()
    second = store.activate("runtime.second", "owner-2", {})
    first = store.activate("runtime.first", "owner-1", {})

    assert [item.key for item in store.snapshot()] == ["runtime.first", "runtime.second"]
    assert store.deactivate(second, outcome="done") is True
    assert store.deactivate(first, outcome="done") is True
    assert [item.key for item in store.history()] == ["runtime.second", "runtime.first"]


def test_concurrent_updates_keep_complete_values_and_unique_revisions() -> None:
    """Serialize updates through one lease without partial payloads."""
    store = RuntimeDataStore()
    lease = store.activate("runtime.test", "owner", {"worker": -1})
    barrier = threading.Barrier(9)

    def update(index: int) -> bool:
        """Perform one synchronized update."""
        barrier.wait()
        return store.update(lease, {"worker": index, "nested": [index, index]})

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(update, index) for index in range(8)]
        barrier.wait()
        assert all(future.result() for future in futures)

    current = store.get("runtime.test")
    assert current is not None
    assert current.revision == 9
    assert current.value["nested"] == [current.value["worker"], current.value["worker"]]


def test_snapshot_during_updates_is_consistent() -> None:
    """Never expose partial nested values while another thread updates."""
    store = RuntimeDataStore()
    lease = store.activate("runtime.test", "owner", {"left": 0, "right": 0})
    started = threading.Event()
    finished = threading.Event()

    def update_many() -> None:
        """Update one complete pair repeatedly."""
        started.set()
        for index in range(200):
            assert store.update(lease, {"left": index, "right": index}) is True
        finished.set()

    thread = threading.Thread(target=update_many)
    thread.start()
    assert started.wait(timeout=2)
    while not finished.is_set():
        snapshot = store.get("runtime.test")
        assert snapshot is not None
        assert snapshot.value["left"] == snapshot.value["right"]
    thread.join(timeout=2)
    assert not thread.is_alive()
