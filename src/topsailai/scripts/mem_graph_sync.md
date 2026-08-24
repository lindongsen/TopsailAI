---
maintainer: AI
workspace: ..
ProjectFolder: ..
ProjectRootFolder: ../../..
ProjectCode: TOPSAILAI
programming_language: python
references:
  - mem_graph_sync.env
  - mem_graph_sync.py
  - mem_graph_sync_outbox.py
---

# Mem Graph Memory Sync

`mem_graph_sync.py` is a best-effort append-only consumer for personal story-memory `create` and `update` events. It creates a new Mem Graph snapshot for every accepted event and uses a bounded local outbox when synchronization fails.

## Input Contract

`mem_graph_sync.py` takes no command-line arguments. It reads a single v1 JSON event from **stdin** and validates it against the required fields:

`schema_version`, `event`, `memory_id`, `title`, `content`, `memory_file`, `workspace`, `timestamp`, `version`.

Accepted `event` values are `create` and `update`; anything else (including `delete`) is rejected.

### Where title and content come from

The `title` and `content` originate from the caller of the story-memory write path:

1. `tools/story_memory_tool.py::write_memory(title, content)` builds an internal event carrying the caller-provided `title` (the original, untimestamped title) and `content`, then fires `memory_hooks.fire_memory_hooks(operation, event)`.
2. `tools/memory_tool_utils/memory_hooks.py` converts that internal event into the stable v1 stdin contract (`_build_sync_event`) and passes it to the configured sync script as JSON on stdin via `cmd_tool.exec_cmd(..., stdin_text=...)`. Bindings are driven by the `TOPSAILAI_MEMORY_SYNC_HOOKS` environment variable.
3. `mem_graph_sync.py::main()` parses it with `json.load(sys.stdin)`, validates it with `validate_event`, and `MemGraphTransport.create_snapshot` copies `event["title"]` and `event["content"]` verbatim into the Mem Graph request body.

So the script never inspects argv; the title and content arrive exclusively through the stdin JSON payload.

## Environment Source

The script loads `mem_graph_sync.env` from its own folder before reading configuration. Existing process environment variables are not overwritten, so source precedence is:

1. Process environment
2. `mem_graph_sync.env`
3. Built-in default

For the external account identity, key precedence within the resolved environment is `TOPSAILAI_MEMORY_SYNC_EXTERNAL_USER_ID`, then the compatible `EXTERNAL_USER_ID`, then `test`.

A missing or unreadable configuration file does not stop the consumer.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MEMGRAPH_API_BASE_URL` | `http://localhost:8004` | Mem Graph REST API base URL. |
| `TOPSAILAI_MEMORY_SYNC_EXTERNAL_USER_ID` | `test` | Preferred external account identity sent with authenticated requests; empty values fall through to `EXTERNAL_USER_ID`. |
| `EXTERNAL_USER_ID` | `test` | Compatible external account identity used when `TOPSAILAI_MEMORY_SYNC_EXTERNAL_USER_ID` is empty or unset. |
| `TOPSAILAI_MEMORY_SYNC_PORT_CHECK_ENABLED` | `1` | Enable the preflight TCP connection check. Truthy values are `1`, `true`, `yes`, `on`, and `enabled`; other non-empty values disable it. |
| `TOPSAILAI_MEMORY_SYNC_PORT_CHECK_TIMEOUT` | `0.5` | Positive TCP connection timeout in seconds; invalid or non-positive values use `0.5`. |
| `TOPSAILAI_MEMORY_SYNC_REQUEST_TIMEOUT` | `5` | Positive HTTP request timeout in seconds; invalid or non-positive values use `5`. |
| `TOPSAILAI_MEMORY_SYNC_RETRY_ATTEMPTS` | `3` | Positive retry-attempt count; invalid or non-positive values use `3`. |
| `TOPSAILAI_MEMORY_SYNC_BACKOFF_SECONDS` | `0.25` | Positive initial delay in seconds for capped exponential backoff; invalid or non-positive values use `0.25`. |
| `TOPSAILAI_MEMORY_SYNC_OUTBOX_MAX_ENTRIES` | `1000` | Positive maximum number of pending outbox events; invalid or non-positive values use `1000`. |
| `TOPSAILAI_MEMORY_SYNC_OUTBOX_MAX_BYTES` | `10485760` | Positive maximum encoded outbox size in bytes; invalid or non-positive values use `10485760`. |

`TOPSAILAI_MEMORY_SYNC_HOOKS` is not script-owned. TopsailAI's memory-hook dispatcher reads it and therefore documents it in the central environment-variable reference.
