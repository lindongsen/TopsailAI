---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Memory Sync To An External Index

How to mirror every successful memory write into a separate index that other tooling reads, without
editing the memory tool and without letting the index grow without limit.

## Why This Exists

A team keeps its durable notes in the agent's memory. A second system needs to find those notes: a
search service, a review dashboard, or a nightly digest. That second system cannot read the memory
folder directly, because the memory folder is the agent's private store with its own layout, and
because the index needs a different retention rule than the notes themselves.

The obvious place to add the mirror is inside `write_memory`. That is the wrong place. The memory
tool owns one job — persist a note — and a mirror is an external side effect with its own failure
mode, its own credentials, and its own owner. Adding it to the tool means every deployment that does
not want an index carries the code, and a second consumer means editing the tool again.

The memory sync Hook is the natural solution because it fires **after** a successful write, from
outside the tool, with a stable JSON contract on stdin. The consumer is a separate executable that
the operator points an environment variable at, so the memory tool stays untouched and the index can
be replaced without a code change.

The second requirement is what makes this more than a log line: the index must be **bounded**. A
memory folder grows for as long as the team uses it, so an index that appends one row per write grows
forever. The example keeps the most recent entries and rewrites one small document atomically.

| Aspect | This recipe |
|--------|-------------|
| Extension point | `TOPSAILAI_MEMORY_SYNC_HOOKS` |
| Fires when | After a memory create or update has already succeeded |
| Consumer contract | One JSON object on stdin, `schema_version` 1 |
| Consumer output | Discarded; only the exit code is inspected |
| Growth | One document, most recent 50 entries, replaced atomically |
| Memory tool changed | None |
| Failure isolation | A failing consumer is logged; the memory write still succeeds |

## Quick Start

The example folder is `docs/cookbook/hook/examples/memory_sync`, and the variable points at the
consumer script itself:

```bash
export TOPSAILAI_HOME=/tmp/memory-sync-demo/home
export TOPSAILAI_MEMORY_WORKSPACE=/tmp/memory-sync-demo/memory
export TOPSAILAI_DISABLE_ROOT_LOGGER_CONFIG=1
export TOPSAILAI_COOKBOOK_INDEX_FILE=/tmp/memory-sync-demo/index.json
export TOPSAILAI_MEMORY_SYNC_HOOKS='{"create":[{"script":"/TopsailAI/src/topsailai/docs/cookbook/hook/examples/memory_sync/index_memory.py","timeout":30,"env_keys":["TOPSAILAI_COOKBOOK_INDEX_FILE"]}],"update":[{"script":"/TopsailAI/src/topsailai/docs/cookbook/hook/examples/memory_sync/index_memory.py","timeout":30,"env_keys":["TOPSAILAI_COOKBOOK_INDEX_FILE"]}]}'
mkdir -p /tmp/memory-sync-demo/home /tmp/memory-sync-demo/memory
```

`TOPSAILAI_COOKBOOK_INDEX_FILE` is this example's own variable, not a framework setting. The
consumer reads it and refuses to write anywhere else. `TOPSAILAI_HOME` and
`TOPSAILAI_MEMORY_WORKSPACE` only keep the demo out of your real memory folder, and
`TOPSAILAI_DISABLE_ROOT_LOGGER_CONFIG` keeps the transcript readable.

One write is enough to produce the index:

```bash
uv run python -c "
from topsailai.tools.story_memory_tool import write_memory

print(write_memory('checkout latency runbook', 'p99 above 4s means the payment pool is saturated').splitlines()[0])
" 2>&1
echo "--- index.json"
cat /tmp/memory-sync-demo/index.json
```

```text
new_memory_file=/tmp/memory-sync-demo/memory/story/2026-11-04/20261104170600.checkout_latency_runbook.md
--- index.json
{
  "entries": [
    {
      "event": "create",
      "memory_id": "20261104170600.checkout_latency_runbook.md",
      "timestamp": "2026-11-04 17:06:00 +08:00",
      "title": "checkout latency runbook",
      "version": 1
    }
  ],
  "schema_version": 1
}
```

The memory file name carries a `YYYYMMDDHHMMSS` prefix, so your run prints a different one. The
index entry mirrors whatever the write produced; the recipe guarantees the shape, not the timestamp.

## Folder Layout

```text
memory_sync/          <- the script named by TOPSAILAI_MEMORY_SYNC_HOOKS
└── index_memory.py   <- one consumer, executable, with a shebang
```

The variable names the **script**, not the folder. That is different from the Hook Point recipes,
which name a folder of Modules; here each binding is one executable.

## The Consumer Contract

The consumer receives exactly one JSON object on stdin. This is the payload captured from a real
write by a probe consumer that dumped its own stdin:

```json
{
  "content": "show the exact stdin contract",
  "event": "create",
  "memory_file": "/tmp/memory-sync-demo/memory/story/2026-11-04/20261104170516.payload_probe.md",
  "memory_id": "20261104170516.payload_probe.md",
  "schema_version": 1,
  "timestamp": "2026-11-04 17:05:16 +08:00",
  "title": "payload probe",
  "version": 1,
  "workspace": "/tmp/memory-sync-demo/memory"
}
```

| Field | Meaning |
|-------|---------|
| `schema_version` | Always `1` for this contract. |
| `event` | `create` or `update`; the same value selects which binding list ran. |
| `memory_id` | Stable identity of the note, derived from the memory file name. |
| `title` | The title as the caller passed it, before the timestamp prefix was added. |
| `content` | The note body, verbatim. |
| `memory_file` | Absolute path of the written note. |
| `workspace` | The memory workspace the note was written into. |
| `timestamp` | Local time with a numeric offset, at the moment the event was built. |
| `version` | The note's version after this write; `1` on create, incremented on update. |

`content` is the whole note body, so a consumer that forwards it elsewhere is forwarding user data.
The example deliberately does not copy it into the index; it keeps identity and title only.

## The Example Consumer

`docs/cookbook/hook/examples/memory_sync/index_memory.py`:

```python
#!/usr/bin/env python3
"""Mirror one successful memory write into a team knowledge index.

Scenario: a team keeps its durable notes in the agent's memory, but the same
notes must be discoverable from a shared index that other tooling reads. The
index is a separate artifact with its own retention rule, so it cannot live
inside the memory folder. This consumer receives one memory event on stdin and
rewrites a bounded index document, so the index never grows without limit.
"""

import json
import os
import sys
from pathlib import Path

INDEX_ENV = "TOPSAILAI_COOKBOOK_INDEX_FILE"
MAX_ENTRIES = 50
REQUIRED_FIELDS = ("schema_version", "event", "memory_id", "title", "timestamp")


def _index_path() -> Path:
    """Return the absolute index path selected by the operator.

    Returns:
        The index file path.

    Raises:
        ValueError: When the variable is unset or not absolute.
    """
    raw = os.getenv(INDEX_ENV, "").strip()
    if not raw or not os.path.isabs(raw):
        raise ValueError(f"{INDEX_ENV} must name an absolute file path")
    return Path(raw)


def _read_index(path: Path) -> list[dict]:
    """Load the existing index entries, tolerating a missing or broken file.

    Args:
        path: The index file path.

    Returns:
        The stored entries, or an empty list when the file cannot be used.
    """
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = data.get("entries") if isinstance(data, dict) else None
    return entries if isinstance(entries, list) else []


def _validate(event: dict) -> str:
    """Return an error message when the event cannot be indexed.

    Args:
        event: The decoded stdin payload.

    Returns:
        An empty string when the payload is usable, otherwise the reason.
    """
    missing = [name for name in REQUIRED_FIELDS if name not in event]
    if missing:
        return f"missing fields: {','.join(missing)}"
    if event["event"] not in ("create", "update"):
        return f"unsupported event: {event['event']}"
    return ""


def main() -> int:
    """Read one memory event and rewrite the bounded index document.

    Returns:
        0 on success, 2 when the payload or configuration is unusable.
    """
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"error: invalid stdin JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(event, dict):
        print("error: stdin must contain one JSON object", file=sys.stderr)
        return 2

    reason = _validate(event)
    if reason:
        print(f"error: {reason}", file=sys.stderr)
        return 2

    try:
        path = _index_path()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    entries = [item for item in _read_index(path) if item.get("memory_id") != event["memory_id"]]
    entries.append(
        {
            "memory_id": event["memory_id"],
            "title": event["title"],
            "event": event["event"],
            "version": event.get("version"),
            "timestamp": event["timestamp"],
        }
    )
    entries = entries[-MAX_ENTRIES:]

    document = {"schema_version": 1, "entries": entries}
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    print(f"indexed memory_id={event['memory_id']} entries={len(entries)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Four design points are worth copying:

- **The consumer is idempotent per note.** Entries are filtered by `memory_id` before the new one is
  appended, so an update replaces the previous row instead of adding a second one.
- **The write is atomic.** A temporary file is renamed over the destination, so a reader never sees a
  half-written document.
- **The bound is explicit.** `MAX_ENTRIES` truncates the list, so the index cannot grow with the
  memory folder.
- **The exit code is the only signal.** The framework inspects the return code and discards stdout,
  so the consumer reports failure by exiting non-zero, not by printing.

## The Update Path

`event` is `update` only when the note already exists at the same timestamped path. Because the
prefix has one-second resolution, two writes of the same title in the same second collide, and the
second one is an update. Pinning the clock makes that reproducible:

```bash
uv run python -c "
from unittest.mock import patch
from topsailai.tools.story_memory_tool import write_memory

with patch('topsailai.utils.time_tool.get_current_compact_datetime', return_value='20261104170600'):
    print(write_memory('checkout latency runbook', 'p99 above 4s means the payment pool is saturated; escalate to the payments on-call').splitlines()[0])
" 2>&1
echo "--- index.json"
cat /tmp/memory-sync-demo/index.json
```

```text
new_memory_file=/tmp/memory-sync-demo/memory/story/2026-11-04/20261104170600.checkout_latency_runbook.md
--- index.json
{
  "entries": [
    {
      "event": "update",
      "memory_id": "20261104170600.checkout_latency_runbook.md",
      "timestamp": "2026-11-04 17:06:00 +08:00",
      "title": "checkout latency runbook",
      "version": 2
    }
  ],
  "schema_version": 1
}
```

The index still holds one row: the `memory_id` matched, so the entry was replaced and `version`
advanced to `2`. This is the behavior a mirror needs — an index that appended on update would show
the same note twice.

Writing the same title in a **later** second is a different story: the timestamp prefix differs, so
the path differs, so the operation is `create` and the index gains a second row. That is the memory
tool's own identity rule, not a sync defect; if a team needs one row per title regardless of time,
the consumer must key on `title` instead of `memory_id`.

## The Failure Path

A consumer that cannot reach its index must not lose the note. The binding below omits `env_keys`,
so the child process never receives `TOPSAILAI_COOKBOOK_INDEX_FILE` and the consumer refuses to
guess a path:

```bash
export TOPSAILAI_MEMORY_SYNC_HOOKS='{"create":[{"script":"/TopsailAI/src/topsailai/docs/cookbook/hook/examples/memory_sync/index_memory.py","timeout":30}]}'
rm -f /tmp/memory-sync-demo/index.json
uv run python -c "
from topsailai.tools.story_memory_tool import write_memory

print(write_memory('checkout latency runbook', 'p99 above 4s means the payment pool is saturated').splitlines()[0])
" 2>&1
echo "--- index.json"
cat /tmp/memory-sync-demo/index.json 2>/dev/null || echo "(absent)"
```

```text
memory sync hook exited non-zero: operation=create script=/TopsailAI/src/topsailai/docs/cookbook/hook/examples/memory_sync/index_memory.py code=2
new_memory_file=/tmp/memory-sync-demo/memory/story/2026-11-04/20261104170627.checkout_latency_runbook.md
--- index.json
(absent)
```

The note was written and the index was not. The warning names the operation, the script, and the
exit code, which is enough to find the binding; the memory write returned normally, so the agent
never learns that the mirror failed. That is the intended trade: a mirror is not allowed to fail the
work it observes.

The consumer's own stderr is **not** in that transcript. Only the exit code reaches the log, so a
consumer that wants its reason recorded must write it somewhere the operator reads, or exit with a
distinct code per cause.

## Rejected Inputs

Malformed configuration is ignored rather than fatal, and the note is still written:

```bash
export TOPSAILAI_MEMORY_SYNC_HOOKS='{"create": [oops'
uv run python -c "
from topsailai.tools.story_memory_tool import write_memory

print(write_memory('malformed config', 'the binding list is not valid JSON').splitlines()[0])
" 2>&1
```

```text
invalid TOPSAILAI_MEMORY_SYNC_HOOKS JSON: Expecting value: line 1 column 13 (char 12)
new_memory_file=/tmp/memory-sync-demo/memory/story/2026-11-04/20261104170641.malformed_config.md
```

An unsupported event key is reported and then never dispatched, because only `create` and `update`
are read:

```bash
export TOPSAILAI_MEMORY_SYNC_HOOKS='{"delete":[{"script":"/TopsailAI/src/topsailai/docs/cookbook/hook/examples/memory_sync/index_memory.py","timeout":30,"env_keys":["TOPSAILAI_COOKBOOK_INDEX_FILE"]}]}'
uv run python -c "
from topsailai.tools.story_memory_tool import write_memory

print(write_memory('delete event', 'delete is not a supported sync event').splitlines()[0])
" 2>&1
```

```text
ignoring unsupported memory sync event: delete
new_memory_file=/tmp/memory-sync-demo/memory/story/2026-11-04/20261104170641.delete_event.md
```

A relative script path is not resolved against the project; the child is executed as given, so the
shell cannot find it:

```bash
export TOPSAILAI_MEMORY_SYNC_HOOKS='{"create":[{"script":"docs/cookbook/hook/examples/memory_sync/index_memory.py","timeout":30,"env_keys":["TOPSAILAI_COOKBOOK_INDEX_FILE"]}]}'
uv run python -c "
from topsailai.tools.story_memory_tool import write_memory

print(write_memory('relative script', 'the consumer path is relative').splitlines()[0])
" 2>&1
```

```text
memory sync hook exited non-zero: operation=create script=docs/cookbook/hook/examples/memory_sync/index_memory.py code=127
new_memory_file=/tmp/memory-sync-demo/memory/story/2026-11-04/20261104170641.relative_script.md
```

Exit code `127` is the shell's "command not found", which is why an absolute path is the only
reliable form. The same applies to the interpreter: the script is executed directly, so it needs a
shebang and the executable bit. A Python file without a shebang is handed to the shell and fails with
`code=2` and a shell syntax error.

## Loader Behavior

These facts were read from `tools/memory_tool_utils/memory_hooks.py` and `utils/cmd_tool.py`, and
each was reproduced by a run.

| Requirement | Observed behavior |
|-------------|-------------------|
| Configuration shape | A JSON object keyed by `create` and `update`; each value is a list of bindings. |
| Binding fields | `script` (required), `timeout` (positive integer, default `300`), `enabled` (default `true`), `env_keys` (list of strings). |
| Invalid JSON | Logged as `invalid TOPSAILAI_MEMORY_SYNC_HOOKS JSON: ...` and treated as no configuration. |
| Non-object JSON | Logged as `TOPSAILAI_MEMORY_SYNC_HOOKS must contain a JSON object` and ignored. |
| Unknown event key | Logged as `ignoring unsupported memory sync event: <key>`; the binding never runs. |
| Invalid binding | Logged and skipped; the remaining bindings still run. |
| `enabled: false` | The binding is skipped silently, with no log line. |
| Invalid `timeout` | Logged as `memory sync binding has invalid timeout`; the binding is skipped. |
| Invalid `env_keys` | Logged as `memory sync binding has invalid env_keys`; the binding is skipped. |
| Child environment | A whitelist: `HOME`, `PYTHONPATH`, `PATH`, `HOSTNAME`, `SHELL`, `GOCACHE`, `GOPATH`, `GOMODCACHE`, plus `env_keys` and `TOPSAILAI_CMD_ENV_KEYS`. Nothing else is inherited. |
| Consumer stdout | Discarded. Only the exit code is inspected. |
| Consumer stderr | Discarded. Only the exit code is inspected. |
| Non-zero exit | Logged as `memory sync hook exited non-zero: operation=... script=... code=...`; the write still succeeds. |
| Consumer exception | Logged with a traceback as `memory sync hook failed`; the write still succeeds. |
| Load timing | The configuration is read on **every** write, so a change takes effect without a restart. |
| Dispatch order | Bindings run in list order, sequentially. |
| `delete` support | None. Only `create` and `update` exist. |

The child environment row is the one that surprises people, so it is worth showing. The variable is
set in the parent, the binding omits `env_keys`, and the consumer still finds its index because
`TOPSAILAI_CMD_ENV_KEYS` names it globally:

```bash
export TOPSAILAI_CMD_ENV_KEYS=TOPSAILAI_COOKBOOK_INDEX_FILE
export TOPSAILAI_MEMORY_SYNC_HOOKS='{"create":[{"script":"/TopsailAI/src/topsailai/docs/cookbook/hook/examples/memory_sync/index_memory.py","timeout":30}]}'
rm -f /tmp/memory-sync-demo/index.json
uv run python -c "
from topsailai.tools.story_memory_tool import write_memory

print(write_memory('cmd env keys', 'index via TOPSAILAI_CMD_ENV_KEYS').splitlines()[0])
" 2>&1
test -f /tmp/memory-sync-demo/index.json && echo "index written via TOPSAILAI_CMD_ENV_KEYS"
```

```text
new_memory_file=/tmp/memory-sync-demo/memory/story/2026-11-04/20261104170525.cmd_env_keys.md
index written via TOPSAILAI_CMD_ENV_KEYS
```

`TOPSAILAI_CMD_ENV_KEYS` is a process-wide allowlist, so it applies to every command the agent runs,
not only to this consumer. Prefer the binding's own `env_keys` and keep the global list empty unless
several consumers need the same variable.

The load-timing row is the other one worth showing, because it differs from the Hook Point recipes:

```bash
uv run python -c "
import os
from topsailai.tools.story_memory_tool import write_memory

SCRIPT = '/TopsailAI/src/topsailai/docs/cookbook/hook/examples/memory_sync/index_memory.py'
BINDING = '{\"create\":[{\"script\":\"%s\",\"timeout\":30,\"env_keys\":[\"TOPSAILAI_COOKBOOK_INDEX_FILE\"]}]}' % SCRIPT

os.environ['TOPSAILAI_MEMORY_SYNC_HOOKS'] = ''
write_memory('before config', 'no binding configured yet')
print('index after first write:', os.path.exists('/tmp/memory-sync-demo2/index.json'))

os.environ['TOPSAILAI_MEMORY_SYNC_HOOKS'] = BINDING
write_memory('after config', 'binding added mid-process')
print('index after second write:', os.path.exists('/tmp/memory-sync-demo2/index.json'))
" 2>&1 | grep -E "index after"
```

```text
index after first write: False
index after second write: True
```

The binding was added between two writes in one process and the second write used it. No restart, no
reload call.

## What This Recipe Cannot Do

- **It cannot see a failed write.** The Hook fires after the note is persisted, so a write that
  raises produces no event.
- **It cannot block or rewrite the note.** The consumer's exit code and output are recorded, not
  acted on; the note is already on disk.
- **It cannot report through stdout.** Both streams are discarded, so a consumer that wants to
  explain itself must use its own log file or a distinct exit code.
- **It cannot rely on the parent environment.** Only the whitelist plus `env_keys` and
  `TOPSAILAI_CMD_ENV_KEYS` reach the child.
- **It cannot observe deletion.** There is no `delete` event, so an index built this way keeps rows
  for notes that were later removed. Reconciling that needs a separate sweep.
- **It is not a sandbox.** The consumer runs as an ordinary child process with the agent's own
  privileges.

## Related Documents

- [Environment Variables](../../Environment_Variables.md) — `TOPSAILAI_MEMORY_SYNC_HOOKS`,
  `TOPSAILAI_HOOK_SCRIPTS_MEMORY_WRITE`, and `TOPSAILAI_CMD_ENV_KEYS`
- [Plugin and Extension Mechanisms](../../../features/feature-plugin-mechanisms.md) — the memory
  write extension forms and their trust boundaries
- [External Tool Execution Audit](External_Tool_Execution_Audit.md) — the Hook Point recipe, which
  names a folder of Modules instead of one executable
- [Cookbook](../README.md) — requirements every entry in this folder follows
