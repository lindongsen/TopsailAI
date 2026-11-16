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
| `session_id` | `str \| None` | Session identifier. Auto-resolved from `TOPSAILAI_SESSION_ID` / `SESSION_ID` when not explicitly provided, so JSONL records match the file backend filename. |
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

### Auto-Start

`get_event_collector()` automatically creates **and starts** the global collector, so callers do not need to invoke `.start()` manually. The background flusher begins running as soon as the first event is recorded.

### Synchronous Flush

By default, events are buffered and flushed asynchronously. If an event must be durable before the caller continues, pass `flush=True`:

```python
record_event("critical.event", {"key": "value"}, flush=True)
```

This drains the buffer and writes to the backend on the caller thread. Use sparingly for high-frequency events because it adds I/O latency to every call.

### Buffer Full Behavior

The buffer never blocks the caller. When the buffer reaches its capacity, the **oldest event is dropped** and the new event is appended. A full buffer does **not** trigger an immediate flush; the background flusher remains on its configured interval.

### Process Exit Guarantee

An `atexit` handler is registered when the module is imported. It flushes any remaining events and closes the collector when the interpreter shuts down, so short-lived scripts do not lose the last buffered events.


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
| File naming | session-aware | `{session_id}.{pid}.session.events` when a session ID is resolved, otherwise `topsailai.{pid}.session.events`. The same `session_id` is written into each JSONL record. |
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
| `TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED` | `1` | Enable raw LLM response event recording. `1` = enabled, `0` = disabled. |
| `TOPSAILAI_LLM_RESPONSE_EVENTS_MAX_PAYLOAD_BYTES` | `100000` | Maximum size in bytes for the JSON-encoded event payload. Responses exceeding this limit are progressively truncated. |
| `TOPSAILAI_LLM_RESPONSE_EVENTS_INCLUDE_RAW` | `1` | Include the raw provider response object in the event payload. `1` = include, `0` = omit. |
| `TOPSAILAI_LLM_RESPONSE_EVENTS_STREAM_CHUNK_SAMPLE` | `0` | Number of stream chunks to sample into the event payload. `0` disables sampling. Positive values keep the first N and last N chunks. |

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

#### LLM Raw Response Events

When `TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED=1`, raw LLM responses are recorded
as `llm.response.raw` events from within `ai_base/llm_base.py`. The event is
emitted after the full response (or the complete stream trunk) has been received,
so streaming responses produce exactly one event per LLM call rather than one
per chunk.

The recording hook is isolated in a `try/except` block and never re-raises, so
any failure in serialization or event buffering cannot affect the original LLM
call. Tool calls are detected by inspecting the response object itself
(`message.tool_calls`) rather than relying on environment variables.

See `docs/Environment_Variables.md` for configuration variables:
`TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED`,
`TOPSAILAI_LLM_RESPONSE_EVENTS_MAX_PAYLOAD_BYTES`,
`TOPSAILAI_LLM_RESPONSE_EVENTS_INCLUDE_RAW`, and
`TOPSAILAI_LLM_RESPONSE_EVENTS_STREAM_CHUNK_SAMPLE`.

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
| `ai_base/llm_base.py` | `LLMModel.call_llm_model*` | inline safe hook | `llm.response.raw` |
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

### 9.2 Mounted Through Direct `record_event()` Calls

Several event sources are mounted by calling `record_event()` directly instead of
using the decorators above, because the decorators record too little to be
useful at those locations.

| Location | Event types | Why not the decorator |
|----------|-------------|-----------------------|
| `ai_base/tool_approval/decorator.py` | `tool_approval.request`, `tool_approval.decision` | `record_approval_events` records only `{"decision": decision}`, which serializes the whole decision object and loses the tool name, the matched rule name, and the human's actual answer. |
| `ai_base/llm_base.py` | `llm.request.start`, `llm.request.end` | `record_llm_chat_events` wraps one attempt, so an internally retried request would emit one event per attempt instead of one per logical request. |

`record_approval_events` and `record_llm_chat_events` remain available for
callers that want the coarse decorator behavior, but no production path uses
them.

**`decide()` is deliberately not instrumented.** It only answers whether a human
must be asked, so recording it would emit an event for every tool call even when
no approval rule is configured.

**One logical LLM request emits exactly one start and one terminal end.** The
terminal `outcome` is one of `success`, `exhausted`, `abandoned`, or `failed`,
and every early exit inside the retry loop records its own terminal event before
raising, so a request can never leave a dangling start event.

### 9.3 Mounted Through Hook Point Modules

Some event sources are recorded by a bundled Hook Point Module rather than by
business code. The business function calls the named Hook Point directly, and
the point-local `modules/record_event.py` performs the recording, so the event
contract stays separate from the business decision.

| Hook Point | Event types | Source |
|------------|-------------|--------|
| `hook__context__*__summary_*` (eight active Summary points) | `summary.hook.observed` | `hooks.summary_events_observer` |
| `hook__workspace__after__heavy_task_warning` | `heavy_task.warning` | `hooks.heavy_task_warning` |
| `hook__workspace__error__heavy_task_terminated` | `heavy_task.terminated` | `hooks.heavy_task_terminated` |

The Summary observer records one event per consumed checkpoint, so a normal
summarization emits `before_summary_generate` and `after_summary_apply` and an
error path emits the matching `error_*` checkpoint instead. The heavy-task points
record metadata only: `continuous_summary_times`, `threshold`, and, for the
termination point, `fatal_offset`. The advisory prompt text and the agent object
never enter a payload.

A Hook Point Module failure is isolated: the Module logs a constant warning and
returns `{"recorded": False}`, so a recording failure never interrupts the agent
turn and never replaces `HeavyTaskError`.

No production code calls `record_event()` directly outside of the mounted
locations above, the mounted `record_tool_call_events` decorator, and the bundled
Hook Point Modules listed in 9.3.

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
pytest tests/unit/events/
```

Or use the project test runner with a specific file path:

```bash
python tests/run_tests.py events/test_decorators.py
```

Run a single test file directly:

```bash
pytest tests/unit/events/test_decorators.py
```

---

## 12. Event Channel (External Subscribers)

The event channel pushes recorded events to external subscribers over a Unix
domain socket. It is deliberately independent of the control channel: the
control channel is request/response and must never be delayed by a slow
subscriber, while this channel is server-push and tolerates loss.

### Hard invariants (bottom line)

These invariants are non-negotiable and take precedence over every other
requirement in this document. The channel is an observability facility, so it
must never be able to harm the process it observes.

- **Never a blocking point.** No code path on the producer thread may wait for a
  subscriber, a socket, a lock held by a subscriber, or a thread join. A full
  subscriber queue drops its oldest event instead of waiting, and a slow or dead
  subscriber can only delay its own writer thread.
- **Never an abnormal exit point.** No failure inside the channel may raise out
  of a CLI entry point, terminate the interpreter, or change the process exit
  code. Startup, delivery, and shutdown failures are logged and degrade to "no
  channel".
- **Startup failure is survivable.** When the socket cannot be created, bound, or
  permissioned, the channel reports the failure to its caller, leaves no partial
  state behind, and the process continues without a channel.
- **Runtime failure is survivable.** An exception in the accept loop, the reaper,
  a writer thread, the fan-out path, or the Runtime Data mirror is logged and
  contained. The affected subscriber or thread degrades; the process does not.
- **Shutdown failure is survivable.** Shutdown runs from `atexit`, so every step
  is isolated and the whole routine never raises. A thread that refuses to stop
  is logged and abandoned rather than waited on indefinitely.
- **Enabled by default.** The channel is on unless
  `TOPSAILAI_EVENT_CHANNEL_ENABLED` is explicitly false, so an operator gets
  observability without opting in. The invariants above are what make that
  default safe.

### Delivery semantics

- **Fire and forget.** The producer never waits for an acknowledgement, never
  retries, and never blocks. A failed send is not reported back to the producer.
- **No backfill.** Events recorded while a subscriber is disconnected are lost.
  A reconnect resumes from the current moment, not from the disconnect point.
- **Bounded per-subscriber queue.** Each subscriber owns a queue that drops the
  oldest event on overflow, matching the existing `EventBuffer` policy. The drop
  count is observable through `Subscriber.dropped`.
- **Subscriber isolation.** Every subscriber has its own queue and writer
  thread, so one slow or dead subscriber cannot delay the producer or its peers.
- **Contended locks drop instead of waiting.** The fan-out path runs on the
  producer thread, so it never waits for a lock. When a registry mutation holds
  the registry lock, the producer skips that event for every subscriber rather
  than waiting; when a writer holds one subscriber's queue lock, the producer
  skips that event for that subscriber only. Both cases are counted in the
  process-wide `dropped_total`, so an operator still sees the loss.
- **Per-subscriber drop counts may undercount.** A contended skip cannot
  increment `Subscriber.dropped`, because incrementing it requires the very lock
  that is busy. The process-wide counter remains accurate; only the
  per-subscriber figure can be lower than the true number of skipped events.

### Lifecycle

| Event | Result |
|-------|--------|
| Subscribe | Link established, `subscribed` confirmation sent |
| Heartbeat | `heartbeat_ack` echoes the client sequence number and refreshes liveness |
| Send failure, EOF, or heartbeat timeout | Link closed, subscriber removed, sending stops |
| Reconnect with the same id | Previous entry replaced, so no duplicate delivery |
| Unsubscribe | `unsubscribed` confirmation sent, then the link closes |

The heartbeat timeout is mandatory rather than optional: after a peer is killed
the socket can stay half-open and `sendall` keeps succeeding into the kernel
buffer, so a write failure alone would misreport a dead subscriber as alive.

### Subscriber identity

Identity is client-generated and stable across reconnects. The CLI generates one
automatically and accepts an explicit override, so a reconnect is recognised as
the same subscriber instead of a new one.

### Frames

Frames are JSON Lines, one object per line, multiplexed on one connection.

| Direction | Frame | Purpose |
|-----------|-------|---------|
| Client to server | `subscribe` | Start receiving; carries `subscriber_id` and an optional filter |
| Server to client | `subscribed` | Confirmation |
| Server to client | `event` | One pushed event |
| Client to server | `heartbeat` | Liveness signal with a client sequence number |
| Server to client | `heartbeat_ack` | Echoes the sequence number |
| Client to server | `unsubscribe` | Explicit cancellation |
| Server to client | `unsubscribed` | Confirmation before the link closes |
| Server to client | `error` | Protocol or admission failure |

Filter patterns accept `*`, an exact event type, or a trailing `.*` prefix
wildcard such as `tool_call.*`. Filtering happens on the server so a subscriber
never receives events it did not ask for.

### Socket ownership

The socket file is `{session_id}.{pid}.session.events.sock` in the task folder.
Its suffix must stay registered in `context/session_activity.py`; an
unregistered `*.session.*` suffix makes session cleanup report an unknown owner
and blocks cleanup permanently.

### Production wiring

The channel belongs to the process, not to one agent run. A subscriber attaches
to the process, so it must be able to connect before the first turn starts and
must keep receiving events across every turn, subagent, and retry inside that
process. Binding the socket inside `AgentChat._run()` would expose the endpoint
only for the duration of one `run()` call, so a subscriber that attaches between
turns would find no endpoint at all.

Every CLI entry point that runs an agent or an LLM chat therefore calls
`cli/cli_topsailai/event_channel_bootstrap.py` once at startup. That wrapper
delegates to `workspace/event_channel/process_bootstrap.py`, which starts the
server through `workspace/event_channel/lifecycle.py` and registers an `atexit`
handler that releases it on interpreter exit. The channel is enabled by default,
so an operator gets observability without opting in; setting
`TOPSAILAI_EVENT_CHANNEL_ENABLED` to a false value creates no socket. Enabling it
by default is only safe because of the hard invariants above: no startup,
delivery, or shutdown failure can block the process or change its exit code.

The bootstrap is idempotent: the first caller starts the server, later callers
receive the same instance, and one stop releases it. It never raises, because
observability must not break the process it observes; a startup failure is
logged at warning level and the CLI continues without a channel.

One server is shared per `(session_id, pid)` inside a process. Sharing is
mandatory rather than an optimization: binding the same socket path twice raises
`OSError`, and a second server would install a second subscription registry, so
the fan-out layer would only ever see one of them.

The subscription registry must be installed before `server.start()`. `fan_out()`
returns zero without logging when no registry is registered, so a server started
first would accept subscribers and deliver nothing while reporting no error. The
lifecycle module installs the registry first and rolls it back if startup fails.

`enabled` is read once per process, so changing the variable affects the next
process rather than a running one.

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TOPSAILAI_EVENT_CHANNEL_ENABLED` | `1` | Master switch; enabled by default, and hardened so enabling it can never block or terminate the process |
| `TOPSAILAI_EVENT_CHANNEL_MAX_SUBSCRIBERS` | `8` | Maximum concurrent subscribers |
| `TOPSAILAI_EVENT_CHANNEL_QUEUE_SIZE` | `1000` | Per-subscriber queue capacity |
| `TOPSAILAI_EVENT_CHANNEL_HEARTBEAT_INTERVAL` | `10` | Client heartbeat interval in seconds |
| `TOPSAILAI_EVENT_CHANNEL_HEARTBEAT_TIMEOUT` | `30` | Server idle limit before a subscriber is reclaimed |
| `TOPSAILAI_EVENT_CHANNEL_MAX_FRAME_BYTES` | `1048576` | Maximum accepted single frame size |

### Client

`bin/topsailai_event_subscribe` connects to a session's channel and prints every
pushed event as one JSON line. It exits when the link ends, when the event limit
is reached, or on interrupt.

### Drop observability

Delivery is fire-and-forget, so a full subscriber queue discards its oldest event
instead of blocking the producer. Discards are counted process-wide rather than
per subscriber, because a subscriber's own counter disappears together with the
subscriber — exactly when an operator wants to know whether events were lost.

The cumulative totals are mirrored into the executing Agent's Runtime Data under
the key `event.channel.dropped`, so `/runtime` and `/runtime.get
event.channel.dropped` report them. The published value carries `phase`,
`dropped_total`, and `delivered_total`.

Publication happens only when a drop is counted, so the healthy path performs no
Runtime Data work. The cumulative total is published rather than an increment, so
a drop counted on a thread without a bound Agent is not lost: the next
publication carries the complete total. Runtime Data stays outside conversation
context and never enters session messages or summaries.

---

## 13. Future Work

- Implement `DBEventBackend.write()` for persistent database storage.
- Implement `WebhookEventBackend.write()` for outbound event streaming.
- Add correlation `trace_id` propagation through the agent call stack.
