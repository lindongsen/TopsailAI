# TopsailAI Events Module

## 1. Overview

The `events` module is an independent, lightweight event-recording subsystem for the TopsailAI agent. It captures discrete events that occur during agent execution — such as tool calls, tool-approval decisions, and LLM chat interactions — and persists them to a configurable backend.

### Design Goals

- **Non-intrusive**: Event recording is optional and disabled cheaply when turned off.
- **Buffered**: Events are batched in memory and flushed periodically to reduce backend pressure.
- **Bounded**: The in-memory buffer has a fixed capacity; oldest events are dropped when it is full.
- **Pluggable**: Storage is abstracted behind an adapter interface. The default adapter writes JSON Lines to a file, but database and webhook adapters can be added.
- **Thread-safe**: Multiple threads can record events concurrently without manual synchronization.

---

## 2. Core Concepts

| Concept | Module | Responsibility |
|---------|--------|----------------|
| `Event` | `models.py` | Immutable data object representing a single event. |
| `EventBuffer` | `buffer.py` | Thread-safe bounded queue that drops oldest events on overflow. |
| `EventBackend` | `backends/base.py` | Abstract adapter interface for durable storage. |
| `EventCollector` | `collector.py` | Owns the buffer, backend, and background flush thread. |
| `EventBus` (public API) | `__init__.py` / `collector.py` | Module-level helpers such as `record_event()` and `get_event_collector()`. |

---

## 3. Event Model

An event is represented by the `Event` dataclass in `events/models.py`.

| Field | Type | Description |
|-------|------|-------------|
| `event_id` | `str` | Unique identifier (UUID4). |
| `event_type` | `str` | Dot-separated type, e.g. `tool_call.start`, `tool_call.end`. |
| `timestamp` | `datetime` | UTC creation time. |
| `session_id` | `str \| None` | Optional session identifier, usually from `env_tool.get_session_id()`. |
| `trace_id` | `str \| None` | Optional correlation/trace id for distributed tracing. |
| `source` | `str \| None` | Optional source component, e.g. `ai_base.tool`. |
| `payload` | `dict` | Arbitrary event-specific data. |

Serialization:

- `Event.to_dict()` returns a plain dictionary with ISO-8601 timestamp.
- `Event.to_json_line()` returns a compact JSON Lines string.
- Non-JSON-serializable objects are converted via a safe fallback (`set` → sorted list, `bytes` → hex, `Exception` → string, etc.).

---

## 4. Buffer Mechanism

`EventBuffer` (`events/buffer.py`) is a thread-safe wrapper around `collections.deque`.

| Property | Default | Description |
|----------|---------|-------------|
| Capacity | `1000` | Maximum number of events kept in memory. |
| Overflow policy | Drop oldest | When full, the oldest event is removed to make room for the newest. |
| Operations | `append`, `extend`, `prepend`, `drain`, `snapshot`, `peek`, `clear` | All operations are guarded by a `threading.Lock`. |

The buffer is used by `EventCollector` to absorb bursts of events without blocking the caller.

---

## 5. Background Flush

`EventCollector` starts a daemon thread (`BackgroundFlusher`) that periodically drains the buffer and writes events to the backend.

| Property | Default | Description |
|----------|---------|-------------|
| Interval | `100 ms` | Configured via `TOPSAILAI_EVENTS_FLUSH_INTERVAL_MS`. |
| On failure | Re-queue | If the backend write fails, drained events are prepended back to the buffer. |
| On close | Final flush | `EventCollector.close()` stops the flusher and attempts one last flush. |

When events are disabled, a `NoOpFlusher` is used so no background thread is started.

---

## 6. Backend Adapters

All backends implement `EventBackend` (`events/backends/base.py`):

```python
class EventBackend(ABC):
    @abstractmethod
    def write(self, events: List[Event]) -> bool: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def cleanup(self) -> None: ...
```

### 6.1 FileEventBackend (`backends/file.py`) — Default

Appends events as JSON Lines to a file under `TOPSAILAI_HOME/workspace/task`.

| Property | Default | Description |
|----------|---------|-------------|
| File naming | session-aware | `{session_id}.{pid}.session.events` when `SESSION_ID` is set, otherwise `topsailai.{pid}.session.events`. |
| Retention | `7` days | Removes `.events` files older than `TOPSAILAI_EVENTS_FILE_RETENTION_DAYS`. |
| Max count | `0` (unlimited) | Keeps only the newest `N` `.events` files when set > 0. |
| Delete on exit | `False` | When `True`, registers an `atexit` handler to delete the current process's events file. |
| fsync | `True` | Calls `os.fsync()` after each write for durability. |

### 6.2 DBEventBackend (`backends/db.py`) — Stub

Placeholder backend. `write()` raises `NotImplementedError`. Future implementations can persist events to SQL/NoSQL databases and implement `cleanup()` to prune or archive old records.

### 6.3 WebhookEventBackend (`backends/webhook.py`) — Stub

Placeholder backend. `write()` raises `NotImplementedError`. Future implementations can push events to an HTTP endpoint and implement `cleanup()` to retry or discard undelivered events.

### 6.4 Factory

`events/backends/__init__.py::create_backend(config)` selects the backend based on `EventConfig.backend`:

- `file` → `FileEventBackend`
- `db` → `DBEventBackend`
- `webhook` → `WebhookEventBackend`
- unknown values fall back to `FileEventBackend`

---

## 7. Configuration

All configuration is read from environment variables via `events/config.py::EventConfig.from_env()`.

| Variable | Default | Description |
|----------|---------|-------------|
| `TOPSAILAI_EVENTS_ENABLED` | `1` | Master switch. `1` = enabled, `0` = disabled. |
| `TOPSAILAI_EVENTS_BUFFER_SIZE` | `1000` | In-memory buffer capacity. |
| `TOPSAILAI_EVENTS_FLUSH_INTERVAL_MS` | `100` | Background flush interval in milliseconds. |
| `TOPSAILAI_EVENTS_BACKEND` | `file` | Backend adapter: `file`, `db`, or `webhook`. |
| `TOPSAILAI_EVENTS_FILE_PATH` | `""` | Optional override for the file backend output path. |
| `TOPSAILAI_EVENTS_FILE_RETENTION_DAYS` | `7` | Age-based retention for event files. |
| `TOPSAILAI_EVENTS_FILE_MAX_COUNT` | `0` | Maximum number of event files to keep. `0` = unlimited. |
| `TOPSAILAI_EVENTS_FILE_DELETE_ON_EXIT` | `0` | Delete the current process's events file on shutdown. |
| `TOPSAILAI_EVENTS_FILE_FSYNC` | `1` | Call `os.fsync()` after each file write. |

---

## 8. Usage

### 8.1 Direct Public API

```python
from topsailai.events import record_event, get_event_collector

# Record a custom event.
record_event(
    "custom.event",
    payload={"key": "value"},
    session_id="my-session",
)

# Access the global collector.
collector = get_event_collector()
print(collector.events)  # snapshot of buffered events as dicts
```

Public API exports (`from topsailai.events import ...`):

- `record_event`
- `get_event_collector`
- `reset_event_collector`
- `Event`, `EventConfig`, `EventCollector`
- `EventBackend`, `FileEventBackend`, `DBEventBackend`, `WebhookEventBackend`
- `record_tool_call_events`, `record_approval_events`, `record_llm_chat_events`

### 8.2 Decorators

#### Tool Call Events

```python
from topsailai.events import record_tool_call_events

@record_tool_call_events
def my_tool(x: int) -> int:
    return x * 2
```

Emits:

- `tool_call.start` with `tool_name` and `args`.
- `tool_call.end` with `tool_name`, `args`, `success`, `result`, `duration_ms`, and `error_type`.

#### Tool Approval Events

```python
from topsailai.events import record_approval_events

@record_approval_events
def approve_tool_call(tool_name: str) -> bool:
    return True
```

Emits `tool_approval.decision` with the decision value.

#### LLM Chat Events

```python
from topsailai.events import record_llm_chat_events

@record_llm_chat_events
def chat_with_llm(prompt: str) -> str:
    return "hello"
```

Emits `llm.request.start`, `llm.response.success`, or `llm.response.error`.

### 8.3 Custom Backend Adapter

```python
from typing import List
from topsailai.events.backends.base import EventBackend
from topsailai.events.models import Event

class MyBackend(EventBackend):
    def write(self, events: List[Event]) -> bool:
        for event in events:
            print(event.to_json_line())
        return True

    def close(self) -> None:
        pass

    def cleanup(self) -> None:
        pass
```

---

## 9. Current Instrumentation Points

### 9.1 Mounted

| File | Function | Decorator | Event Types |
|------|----------|-----------|-------------|
| `ai_base/agent_types/tool.py` | `exec_tool_func()` | `@record_tool_call_events` (innermost) | `tool_call.start`, `tool_call.end` |

Decorator stack on `exec_tool_func` (outer → inner):

```python
@tool_stat.detect_duplicate_tool_call
@with_tool_response_safe
@with_tool_approval
@record_tool_call_events
def exec_tool_func(tool_func, args, tool_name:str=None):
```

Because `@record_tool_call_events` is the innermost decorator, it measures the actual tool execution time and captures the raw result before `with_tool_response_safe` truncates it.

### 9.2 Not Mounted

| Intended Location | Decorator | Status |
|-------------------|-----------|--------|
| Tool approval decision | `record_approval_events` | Decorator exists but not mounted in `ai_base/tool_approval/decorator.py` or `instance.py`. |
| LLM chat response / exceptions | `record_llm_chat_events` | Decorator exists but not mounted in `ai_base/llm_base.py`. |

No production code calls `record_event()` directly outside of the mounted decorator.

---

## 10. Thread Safety and Performance

- `EventBuffer` uses a single `threading.Lock`; all public methods are thread-safe.
- `EventCollector.record()` only appends to the buffer and returns immediately; it does not perform I/O on the caller thread.
- `EventCollector.flush()` acquires a dedicated flush lock to serialize backend writes.
- The background flusher is a daemon thread; it will not block process exit.
- When disabled (`TOPSAILAI_EVENTS_ENABLED=0`), decorators and `record_event()` are cheap no-ops after reading the collector's `enabled` flag.
- Result payloads larger than 10 KB are truncated by `record_tool_call_events` to avoid buffering huge objects.

---

## 11. Tests

Unit tests are located under `tests/unit/events/`:

| Test File | Coverage |
|-----------|----------|
| `test_public_api.py` | Public API exports and `record_event()` / `get_event_collector()`. |
| `test_collector.py` | `EventCollector` lifecycle, flush, re-queue on failure, close. |
| `test_buffer.py` | `EventBuffer` bounded behavior, drain, snapshot, prepend. |
| `test_models.py` | `Event` serialization and JSON fallback. |
| `test_config.py` | `EventConfig.from_env()` parsing. |
| `test_backends_file.py` | `FileEventBackend` write, cleanup, retention, max-count, atexit, fsync. |
| `test_decorators.py` | All three decorators. |
| `test_agent_types_tool_events.py` | Real `exec_tool_func` event emission. |

Run the events tests:

```bash
python tests/run_tests.py tests/unit/events
```

Or run a single test file:

```bash
pytest tests/unit/events/test_decorators.py
```

---

## 12. Future Work

- Implement `DBEventBackend.write()` for persistent database storage.
- Implement `WebhookEventBackend.write()` for outbound event streaming.
- Add correlation `trace_id` propagation through the agent call stack.
- Mount `record_approval_events` and `record_llm_chat_events` at the intended production locations once required.
