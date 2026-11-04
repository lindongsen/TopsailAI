---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Post Final Answer Notification

How to deliver every finished answer to an external queue that other people read, without editing the
agent loop and without letting the queue grow without limit.

## Why This Exists

An on-call engineer asks the agent to triage a production alert. The answer is useful only if it
reaches the ticket queue that the rest of the rotation reads, because the engineer may close the
terminal before reading it, and the next person on shift needs the same conclusion. The queue is an
external system with its own credentials and its own retention, so the agent must not embed a client
for it.

The obvious place to add the delivery is inside the chat loop, right after the answer is printed. That
is the wrong place. The loop owns one job — run the turn and produce an answer — and delivery is an
external side effect with its own failure mode, its own owner, and its own retention rule. Adding it
to the loop means every deployment that does not want a queue carries the code, and a second consumer
means editing the loop again.

The post-final-answer Hook is the natural solution because it fires **after** the answer exists, from
outside the loop, with the answer handed to a separate executable through the environment. The
operator points one environment variable at that executable, so the loop stays untouched and the
queue can be replaced without a code change.

The second requirement is what makes this more than a log line: the queue must be **bounded**. A
rotation produces answers for as long as the service runs, so a queue that appends one record per
answer grows forever. The example keeps the most recent records and rewrites one small file
atomically.

| Aspect | This recipe |
|--------|-------------|
| Extension point | `TOPSAILAI_HOOK_SCRIPTS_POST_FINAL_ANSWER` |
| Fires when | After a turn produced an answer, before the success hooks run |
| Consumer contract | The answer text in `TOPSAILAI_FINAL_ANSWER`, plus selected environment keys |
| Consumer output | Captured as `(code, stdout, stderr)` and logged; never shown to the user |
| Growth | One file, most recent 200 records, replaced atomically |
| Chat loop changed | None |
| Failure isolation | A failing consumer is logged; the answer is still produced and printed |

## Quick Start

The example folder is `docs/cookbook/hook/examples/final_notify`, and the variable points at the
consumer script itself:

```bash
export TOPSAILAI_HOME=/tmp/final-notify-demo/home
export TOPSAILAI_ENABLE_SESSION_TEE_OUT=0
export TOPSAILAI_COOKBOOK_TICKET_QUEUE_FILE=/tmp/final-notify-demo/queue.jsonl
export TOPSAILAI_HOOK_SCRIPTS_POST_FINAL_ANSWER='/TopsailAI/src/topsailai/docs/cookbook/hook/examples/final_notify/publish_answer.py env_keys=TOPSAILAI_COOKBOOK_TICKET_QUEUE_FILE'
mkdir -p /tmp/final-notify-demo/home
```

The consumer needs one operator-chosen variable, so the binding names it in `env_keys`. The child
does not inherit the parent environment, so a variable that is not named here never arrives.

## Folder Layout

```text
docs/cookbook/hook/
├── Post_Final_Answer_Notification.md
└── examples/
    └── final_notify/
        └── publish_answer.py
```

The variable names the **script file**, not the folder. This is the difference from the Hook Point
recipe, which names a folder of Modules.

## Consumer Contract

The consumer receives the answer as plain text in `TOPSAILAI_FINAL_ANSWER`. It is not JSON, because
the loop stores the answer as a string and the serializer returns a string unchanged:

```python
>>> from topsailai.utils import json_tool
>>> json_tool.safe_json_dump("hello")
'hello'
>>> json_tool.safe_json_dump(None)
'null'
```

That second line matters. When a turn ends without an answer, the value is the four-character string
`null`, not an empty string, so a consumer that only checks for emptiness will publish the word
`null`. The example checks `answer.strip()` and therefore still publishes it; the document states the
boundary instead of hiding it.

| Field | Source | Meaning |
|-------|--------|---------|
| `TOPSAILAI_FINAL_ANSWER` | The turn's answer | Plain text; `null` when the turn produced no answer |
| `SESSION_ID` | Always passed | Session identifier, empty when unset |
| `TOPSAILAI_SESSION_ID` | Always passed | Session identifier, empty when unset |
| `TOPSAILAI_TASK_ID` | Always passed | Task identifier, empty when unset |
| `env_keys` entries | The binding | Extra variables the consumer needs |
| `TOPSAILAI_CMD_ENV_KEYS` | Process environment | Extra variables for every command, not only this Hook |

## Example Consumer

The committed file is `examples/final_notify/publish_answer.py`:

```python
#!/usr/bin/env python3
"""Publish one agent final answer to an on-call ticket queue.

Scenario: an on-call engineer asks the agent to triage an alert. The answer is
useful only if it reaches the ticket queue that the rest of the rotation reads,
because the engineer may close the terminal before reading it. The queue is an
external system with its own credentials and its own retention, so the agent
must not embed a client for it. This consumer receives the answer through the
environment and appends one bounded record to a queue file.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

QUEUE_ENV = "TOPSAILAI_COOKBOOK_TICKET_QUEUE_FILE"
ANSWER_ENV = "TOPSAILAI_FINAL_ANSWER"
MAX_RECORDS = 200
MAX_ANSWER_CHARS = 4000


def _queue_path() -> Path:
    """Return the absolute queue path selected by the operator.

    Returns:
        The queue file path.

    Raises:
        ValueError: When the variable is unset or not absolute.
    """
    raw = os.getenv(QUEUE_ENV, "").strip()
    if not raw or not os.path.isabs(raw):
        raise ValueError(f"{QUEUE_ENV} must name an absolute file path")
    return Path(raw)


def _read_records(path: Path) -> list[dict]:
    """Load existing queue records, tolerating a missing or broken file.

    Args:
        path: The queue file path.

    Returns:
        The stored records, or an empty list when the file cannot be used.
    """
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def main() -> int:
    """Append the current final answer to the bounded ticket queue.

    Returns:
        0 on success, 2 when the answer or configuration is unusable.
    """
    answer = os.getenv(ANSWER_ENV, "")
    if not answer.strip():
        print(f"error: {ANSWER_ENV} is empty; nothing to publish", file=sys.stderr)
        return 2

    try:
        path = _queue_path()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    truncated = len(answer) > MAX_ANSWER_CHARS
    record = {
        "published_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "answer": answer[:MAX_ANSWER_CHARS],
        "truncated": truncated,
        "session_id": os.getenv("TOPSAILAI_SESSION_ID") or os.getenv("SESSION_ID") or "",
        "task_id": os.getenv("TOPSAILAI_TASK_ID", ""),
    }

    records = _read_records(path)
    records.append(record)
    records = records[-MAX_RECORDS:]

    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in records),
        encoding="utf-8",
    )
    temporary.replace(path)
    print(f"published answer_chars={len(record['answer'])} truncated={truncated} records={len(records)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

The consumer is bounded in three ways: it keeps at most `MAX_RECORDS` records, it truncates the
answer at `MAX_ANSWER_CHARS`, and it replaces the file atomically so a reader never sees a partial
write. It refuses a relative queue path, so the write cannot land in whatever directory the agent
happened to start in.

## Running It Through The Agent

The Hook fires from the chat loop, so the run needs a model endpoint. A local mock server keeps the
run reproducible and offline:

```bash
python3 tests/mock/llm_mock_server.py --host 127.0.0.1 --port 8731 \
  --reply "The checkout pool is saturated; escalate to payments on-call."
```

```bash
env -i HOME=/root PATH=/usr/local/bin:/usr/bin:/bin \
  OPENAI_API_BASE=http://127.0.0.1:8731/v1 OPENAI_API_KEY=mock OPENAI_MODEL=topsailai-mock \
  LLM_RESPONSE_STREAM=0 TOPSAILAI_INTERACTIVE_MODE=0 \
  TOPSAILAI_HOME=/tmp/final-notify-demo/home TOPSAILAI_ENABLE_SESSION_TEE_OUT=0 \
  TOPSAILAI_COOKBOOK_TICKET_QUEUE_FILE=/tmp/final-notify-demo/queue.jsonl \
  TOPSAILAI_HOOK_SCRIPTS_POST_FINAL_ANSWER='/TopsailAI/src/topsailai/docs/cookbook/hook/examples/final_notify/publish_answer.py env_keys=TOPSAILAI_COOKBOOK_TICKET_QUEUE_FILE' \
  uv run python cli/agent_chat.py "triage the checkout alert"
```

```text
The checkout pool is saturated; escalate to payments on-call.
```

```bash
cat /tmp/final-notify-demo/queue.jsonl
```

```text
{"answer": "The checkout pool is saturated; escalate to payments on-call.", "published_at": "2026-11-04T17:19:24+08:00", "session_id": "", "task_id": "", "truncated": false}
```

The answer still reaches the terminal. The queue is an addition, not a replacement.

## Several Consumers In One Variable

Entries are separated by `;` and each entry is parsed with `shlex.split`, so a path containing spaces
can be quoted. A non-zero exit does not stop the remaining entries:

```bash
env -i HOME=/root PATH=/usr/local/bin:/usr/bin:/bin \
  TOPSAILAI_COOKBOOK_TICKET_QUEUE_FILE=/tmp/final-notify-demo/multi.jsonl \
  TOPSAILAI_HOOK_SCRIPTS_POST_FINAL_ANSWER="/tmp/final-notify-demo/fail.py;/TopsailAI/src/topsailai/docs/cookbook/hook/examples/final_notify/publish_answer.py env_keys=TOPSAILAI_COOKBOOK_TICKET_QUEUE_FILE" \
  uv run python -c "
from topsailai.utils import hook_tool
r = hook_tool.call_hook_scripts('TOPSAILAI_HOOK_SCRIPTS_POST_FINAL_ANSWER', {'TOPSAILAI_FINAL_ANSWER': 'The checkout pool is saturated; escalate to payments on-call.'})
for k, v in r.items():
    print(k, '->', v)
"
```

```text
/tmp/final-notify-demo/fail.py -> (3, '', 'cannot reach the ticket API\n')
/TopsailAI/src/topsailai/docs/cookbook/hook/examples/final_notify/publish_answer.py -> (0, 'published answer_chars=61 truncated=False records=1\n', '')
```

The first consumer failed with exit code 3 and the second one still ran. The result mapping keeps
each script's `(code, stdout, stderr)`, which is how the failure becomes visible in the log.

## Failure Path

A consumer that needs a variable the binding did not name cannot do its work. The queue is never
created, and the answer is still produced:

```bash
env -i HOME=/root PATH=/usr/local/bin:/usr/bin:/bin \
  OPENAI_API_BASE=http://127.0.0.1:8731/v1 OPENAI_API_KEY=mock OPENAI_MODEL=topsailai-mock \
  LLM_RESPONSE_STREAM=0 TOPSAILAI_INTERACTIVE_MODE=0 \
  TOPSAILAI_HOME=/tmp/final-notify-demo/home TOPSAILAI_ENABLE_SESSION_TEE_OUT=0 \
  TOPSAILAI_COOKBOOK_TICKET_QUEUE_FILE=/tmp/final-notify-demo/queue.jsonl \
  TOPSAILAI_HOOK_SCRIPTS_POST_FINAL_ANSWER='/TopsailAI/src/topsailai/docs/cookbook/hook/examples/final_notify/publish_answer.py' \
  uv run python cli/agent_chat.py "triage the checkout alert"
```

```text
The checkout pool is saturated; escalate to payments on-call.
```

```bash
cat /tmp/final-notify-demo/queue.jsonl
```

```text
(absent)
```

The consumer exited 2 with `error: TOPSAILAI_COOKBOOK_TICKET_QUEUE_FILE must name an absolute file
path` on stderr, and the run still succeeded. That message is in the log, not on the terminal.

## Rejected Inputs

Each row is a real run against the committed example.

| Input | Real result |
|-------|-------------|
| `timeout=10` in the binding | `call hook failed: [TOPSAILAI_HOOK_SCRIPTS_POST_FINAL_ANSWER], unsupported operand type(s) for +: 'float' and 'str'` at `utils/hook_tool.py:142`; the consumer still ran and the queue was written |
| An option without `=` | `ValueError: not enough values to unpack (expected 2, got 1)`; the loop logs `call hook_for_final_answer failed [...]` and the answer is still produced |
| A relative script path | `{'publish_answer.py': (127, '', '/usr/bin/bash: line 1: publish_answer.py: command not found\n')}` |
| A script without a shebang | `(2, '', 'import: unable to open X server ... syntax error near unexpected token ...')` |
| A script that is not executable | `(126, '', '/usr/bin/bash: line 1: /tmp/final-notify-demo/no_shebang.py: Permission denied\n')` |
| `enabled=false` in the binding | Ignored; the consumer still runs and the queue is written |
| The same path twice | Parsed to one key, so the consumer runs once |
| `TOPSAILAI_FINAL_ANSWER` empty | `error: TOPSAILAI_FINAL_ANSWER is empty; nothing to publish`, exit 2 |
| A relative queue path | `error: TOPSAILAI_COOKBOOK_TICKET_QUEUE_FILE must name an absolute file path`, exit 2 |

The `timeout` row is a defect, not a documented option. The value is parsed as a string and passed
straight to the process wait, so any `timeout=` entry fails after the child has already started. The
same defect affects `TOPSAILAI_HOOK_SCRIPTS_MEMORY_WRITE`. Omit `timeout=` and the default applies.

## Loader Behavior

Every row was checked against `utils/hook_tool.py` and reproduced where it could be observed.

| Behavior | Observed |
|----------|----------|
| Separator between entries | `;` |
| Entry parsing | `shlex.split`, so quoting works |
| Option syntax | `key=value`; a value containing `,` becomes a list |
| Recognized options | `timeout` and `env_keys` only |
| Unrecognized options | Silently ignored, including `enabled` |
| `timeout` type | Passed as the parsed string, which fails at the wait |
| Default timeout | `300` seconds when `timeout` is absent |
| Base environment keys | `SESSION_ID`, `TOPSAILAI_SESSION_ID`, `TOPSAILAI_TASK_ID` |
| Extra environment keys | `env_keys` on the entry, plus `TOPSAILAI_CMD_ENV_KEYS` for every command |
| Inherited environment | Whitelist only: `HOME`, `PYTHONPATH`, `PATH`, `HOSTNAME`, `SHELL`, `GOCACHE`, `GOPATH`, `GOMODCACHE` |
| Duplicate script path | Collapsed to one entry, executed once |
| Execution order | Dictionary insertion order, which follows the configured order |
| Failure of one entry | Logged; remaining entries still run |
| Consumer stdout and stderr | Captured in the result tuple and logged; never shown to the user |
| Configuration read timing | On each final answer, so a changed value applies to the next turn |
| Missing configuration | No consumer runs and no error is raised |

`TOPSAILAI_CMD_ENV_KEYS` is an alternative to `env_keys` and was verified on this path:

```bash
env -i HOME=/root PATH=/usr/local/bin:/usr/bin:/bin \
  OPENAI_API_BASE=http://127.0.0.1:8731/v1 OPENAI_API_KEY=mock OPENAI_MODEL=topsailai-mock \
  LLM_RESPONSE_STREAM=0 TOPSAILAI_INTERACTIVE_MODE=0 \
  TOPSAILAI_HOME=/tmp/final-notify-demo/home TOPSAILAI_ENABLE_SESSION_TEE_OUT=0 \
  TOPSAILAI_COOKBOOK_TICKET_QUEUE_FILE=/tmp/final-notify-demo/queue.jsonl \
  TOPSAILAI_CMD_ENV_KEYS=TOPSAILAI_COOKBOOK_TICKET_QUEUE_FILE \
  TOPSAILAI_HOOK_SCRIPTS_POST_FINAL_ANSWER='/TopsailAI/src/topsailai/docs/cookbook/hook/examples/final_notify/publish_answer.py' \
  uv run python cli/agent_chat.py "triage the checkout alert"
```

```text
{"answer": "The checkout pool is saturated; escalate to payments on-call.", "published_at": "2026-11-04T17:26:54+08:00", "session_id": "", "task_id": "", "truncated": false}
```

## What This Recipe Cannot Do

- **It cannot change the answer.** The Hook runs after the answer is final; the consumer's exit code
  and output are recorded, not acted on.
- **It cannot stop the turn.** A failing consumer is logged and the run continues.
- **It cannot show its output to the user.** Both streams are captured and logged only.
- **It cannot rely on the parent environment.** Only the whitelist plus `env_keys` and
  `TOPSAILAI_CMD_ENV_KEYS` reach the child.
- **It cannot distinguish "no answer" from the word `null`.** A turn without an answer passes the
  string `null`, so a consumer must decide how to treat it.
- **It cannot use `timeout=`.** The option fails at the wait; rely on the default instead.
- **It cannot disable one entry.** `enabled=false` is ignored, so remove the entry to disable it.
- **It is not a sandbox.** The consumer runs as an ordinary child process with the agent's own
  privileges.

## Related Documents

- [Environment Variables](../../Environment_Variables.md) —
  `TOPSAILAI_HOOK_SCRIPTS_POST_FINAL_ANSWER`, `TOPSAILAI_HOOK_SCRIPTS_MEMORY_WRITE`, and
  `TOPSAILAI_CMD_ENV_KEYS`
- [Plugin and Extension Mechanisms](../../../features/feature-plugin-mechanisms.md) — the script Hook
  forms and their trust boundaries
- [Memory Sync To An External Index](Memory_Sync_To_External_Index.md) — the sibling recipe, which
  receives a JSON object on stdin instead of the answer in the environment
- [External Tool Execution Audit](External_Tool_Execution_Audit.md) — the Hook Point recipe, which
  names a folder of Modules instead of one executable
- [Cookbook](../README.md) — requirements every entry in this folder follows
