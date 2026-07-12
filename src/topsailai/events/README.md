# TopsailAI Events Module

Independent event recording component for the TopsailAI agent framework.

## Purpose

The events module records notable occurrences during an agent's lifecycle, such as tool calls, tool approval decisions, and LLM chat responses. Events are buffered in memory and periodically flushed to a configurable backend.

## Structure

```
events/
├── __init__.py          # Public API: record_event, get_event_collector
├── models.py            # Event dataclass
├── config.py            # Environment-based configuration
├── buffer.py            # Thread-safe bounded event buffer
├── backends/            # Storage adapters
│   ├── base.py          # Abstract backend interface
│   ├── file.py          # JSONL file backend (default)
│   ├── db.py            # Database backend (stub)
│   └── webhook.py       # Webhook backend (stub)
├── collector.py         # EventCollector: buffer + BackgroundFlusher + backend
└── decorators.py        # Decorators for recording tool/approval/llm events
```

`BackgroundFlusher` is implemented inside `collector.py`.

## Configuration

All configuration is read from environment variables via `topsailai.utils.env_tool.EnvReaderInstance`.

| Variable | Default | Description |
|----------|---------|-------------|
| `TOPSAILAI_EVENTS_ENABLED` | `1` | Master switch. `1` enables event recording; `0` disables it. When disabled, `record_event()` is a cheap no-op and no background thread or backend is created. |
| `TOPSAILAI_EVENTS_BUFFER_SIZE` | `1000` | Maximum number of events held in the in-memory buffer. Oldest events are dropped when the buffer is full. |
| `TOPSAILAI_EVENTS_FLUSH_INTERVAL_MS` | `100` | Interval in milliseconds between background flush attempts. |
| `TOPSAILAI_EVENTS_BACKEND` | `file` | Backend adapter to use. Supported values: `file`, `db`, `webhook`. Unknown values fall back to `file` with a warning. |
| `TOPSAILAI_EVENTS_FILE_PATH` | (auto) | Optional full path for the file backend. When empty, the file is placed in `TOPSAILAI_HOME/workspace/task` with the same naming convention as session stdout but using the `.events` extension. |

## Usage

### Direct API
### Direct API

```python
from topsailai import events

events.record_event("my.event", {"detail": "something happened"})
```

### Decorators

```python
from topsailai.events import record_tool_call_events, record_approval_events, record_llm_chat_events

@record_tool_call_events(tool_name="my_tool")
def my_tool(x):
    return x

@record_approval_events()
def approval_decision():
    return {"action": "allow", "rule_name": "default"}

@record_llm_chat_events()
def chat():
    return "response"
```

Decorators accept an optional `collector=` argument for testing. When omitted, they use the module-level default collector.

## Event Schema

Each event is serialized as one JSON line with the following fields:

```json
{
  "event_type": "tool_call.start",
  "timestamp": "2026-07-11T14:00:00.000000+00:00",
  "session_id": "abc-123",
  "trace_id": "...",
  "source": "...",
  "payload": {...}
}
```

Non-JSON-serializable payload values are stringified automatically so that a single bad payload cannot block the flush pipeline.

## Backend Adapters

New backends can be added by subclassing `EventBackend` and implementing `write(events)` and `close()`. Register the backend name in `backends/__init__.py` and `collector.py` if you want selection via `TOPSAILAI_EVENTS_BACKEND`.
