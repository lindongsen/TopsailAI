---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# External Tool Execution Audit

How to record which tools ran, how long they took, and how they failed, without editing the tools
and without keeping the data they touched.

## Why This Exists

An operations review needs one answer: did the agent actually call the tools it claims it called,
and did any of them fail? The evidence must come from the runtime, not from the model's own
narrative, because a model can describe a call it never made.

The obvious place to add that evidence is inside each tool. That is the wrong place. A tool is a
function the LLM chooses to call, so its body belongs to the capability, not to the audit; adding
logging to every tool duplicates the same code, and a tool added later silently escapes the audit.
A decorator around the tool has the same problem in a different shape: it changes the callable the
registry publishes, and it must be applied to every tool by hand.

The tool-execution Hook Points are the natural solution because they observe the call from outside
the tool, at the one place every tool call passes through. The audit Module is a separate file that
the operator points an environment variable at, so the tools stay untouched and a new tool is
audited automatically.

The second requirement is what makes this more than a log line: the audit must be **bounded and
non-retaining**. Argument values, tool results, and exception messages can contain customer data,
credentials, or file contents, so the record keeps only metadata — the tool name, how many
arguments were passed, and their key names. Each phase overwrites one small JSON file, so the audit
cannot grow without limit.

| Aspect | This recipe |
|--------|-------------|
| Extension point | `TOPSAILAI_HOOK_POINTS` with the three `hook__aibase__*__tool_execute` points |
| What is recorded | Tool name, argument count, argument key names, duration, exception class name |
| What is never recorded | Argument values, tool result, exception object or message |
| Growth | One file per phase, replaced atomically; no append-only log |
| Tool code changed | None |

## Quick Start

The example folder is `docs/cookbook/hook/examples/tool_audit`, and it is pointed at directly:

```bash
export TOPSAILAI_HOOK_POINTS='{"hook__aibase__before__tool_execute":{"modules":["/TopsailAI/src/topsailai/docs/cookbook/hook/examples/tool_audit"]},"hook__aibase__after__tool_execute":{"modules":["/TopsailAI/src/topsailai/docs/cookbook/hook/examples/tool_audit"]},"hook__aibase__error__tool_execute":{"modules":["/TopsailAI/src/topsailai/docs/cookbook/hook/examples/tool_audit"]}}'
export TOPSAILAI_COOKBOOK_HOOK_AUDIT_DIR=/tmp/hook-audit-demo/audit
export TOPSAILAI_PRINT_COLOR_ENABLED=0
export TOPSAILAI_ENABLE_TOOL_STAT=0
export TOPSAILAI_PRINT_TOOL_STAT=0
export TOPSAILAI_DISABLE_ROOT_LOGGER_CONFIG=1
export TOPSAILAI_INTERACTIVE_MODE=0
mkdir -p /tmp/hook-audit-demo/audit
```

`TOPSAILAI_COOKBOOK_HOOK_AUDIT_DIR` is this example's own variable, not a framework setting. The
Module reads it and refuses to write anywhere else. The other exports only keep the transcript
readable: no colors, no tool statistics, no logger configuration, no interactive prompts.

A headless run through `topsailai_simulate_agent_execute` shows the whole path, with the agent
reading one incident report:

```bash
printf 'incident-42\nservice: checkout-api\nsymptom: p99 latency 4.2s for 11 minutes\n' > /tmp/hook-audit-demo/report.txt
printf 'topsailai.thought\nThe review needs the incident report.\ntopsailai.action\n{"tool_call": "file_tool-read_file", "tool_args": {"file_path": "/tmp/hook-audit-demo/report.txt"}}\ntopsailai.final_answer\nCheckout latency spiked for eleven minutes.\n' > /tmp/hook-audit-demo/response.txt
rm -f /tmp/hook-audit-demo/audit/*.json
uv run python cli/topsailai_simulate_agent_execute.py --file /tmp/hook-audit-demo/response.txt --only-tools file_tool
echo "--- audit folder"
ls -1 /tmp/hook-audit-demo/audit
for f in /tmp/hook-audit-demo/audit/*.json; do echo "--- $(basename "$f")"; cat "$f"; done
```

```text
[0] thought
The review needs the incident report.
Checkout latency spiked for eleven minutes.

[1] action
{"tool_call": "file_tool-read_file", "tool_args": {"file_path": "/tmp/hook-audit-demo/report.txt"}}
-> observation: {'step_name': 'observation', 'raw_text': 'incident-42\nservice: checkout-api\nsymptom: p99 latency 4.2s for 11 minutes\n'}

Final answer:
Checkout latency spiked for eleven minutes.
--- audit folder
tool-after.json
tool-before.json
--- tool-after.json
{
  "argument_count": 1,
  "argument_keys": [
    "file_path"
  ],
  "duration_sec": 0.007630645297467709,
  "phase": "after",
  "tool_name": "file_tool-read_file"
}
--- tool-before.json
{
  "argument_count": 1,
  "argument_keys": [
    "file_path"
  ],
  "phase": "before",
  "tool_name": "file_tool-read_file"
}
```

The tool result is unchanged: the agent still received the report text. The audit is a side
channel, not a filter.

`duration_sec` is a real measurement, so your run prints a different number; the field's presence and
its meaning are what the recipe guarantees. Everything else in that transcript is stable.

## Folder Layout

```text
tool_audit/                    <- point TOPSAILAI_HOOK_POINTS at this folder
└── tool_execution_audit.py    <- one Module, registered at three points
```

The same folder is listed for all three points because one Module handles all three phases; it
decides which phase it is in from the payload it receives.

## The Three Points and Their Payloads

| Point | Emitted when | Extra keyword |
|-------|--------------|---------------|
| `hook__aibase__before__tool_execute` | Before the tool body runs | none |
| `hook__aibase__after__tool_execute` | The tool returned normally | `duration_sec` |
| `hook__aibase__error__tool_execute` | The tool raised an ordinary exception | `error_category` |

All three receive `tool_name`, `argument_count`, and `argument_keys`. `argument_keys` is a sorted
tuple of the argument names, which is why the example converts it to a list before serializing.

`error_category` is the exception class name, truncated to 128 characters. The exception object and
its message are deliberately absent, so a `PermissionError` carrying a path never reaches the audit
file.

Two lifecycle facts decide what the audit can and cannot see:

- **Approval runs first.** A tool call denied by the approval gate never reaches the tool body, so
  none of the three points fire and the audit folder stays empty.
- **A terminal exception is not an ordinary failure.** `AgentToolCallException` propagates out of
  `exec_tool_func` without an error observation, so only the `before` record exists.

## The Example Module

`docs/cookbook/hook/examples/tool_audit/tool_execution_audit.py`:

```python
"""Write bounded tool-execution audit snapshots for an operations review.

During an incident review an operator must decide whether the agent really called
the tools it claims it called, and must not retain argument values, results, or
exception messages while collecting that evidence. Each Hook phase overwrites one
small JSON file, so the example cannot create an unbounded audit log.
"""

import json
import os
from pathlib import Path

AUDIT_FOLDER_ENV = "TOPSAILAI_COOKBOOK_HOOK_AUDIT_DIR"
ALLOWED_COMMON_FIELDS = ("tool_name", "argument_count", "argument_keys")


def _phase(payload: dict) -> str:
    """Identify the tool lifecycle phase from its point-specific metadata."""
    if "error_category" in payload:
        return "error"
    if "duration_sec" in payload:
        return "after"
    return "before"


def _audit_folder() -> Path:
    """Return the existing absolute folder selected by the operator."""
    raw_path = os.getenv(AUDIT_FOLDER_ENV, "")
    path = Path(raw_path)
    if not raw_path or not path.is_absolute() or not path.is_dir():
        raise ValueError(f"{AUDIT_FOLDER_ENV} must name an existing absolute directory")
    return path


def _safe_record(payload: dict) -> dict:
    """Project the Hook payload onto the documented metadata allowlist."""
    phase = _phase(payload)
    record = {"phase": phase}
    for field in ALLOWED_COMMON_FIELDS:
        value = payload.get(field)
        record[field] = list(value) if field == "argument_keys" else value
    if phase == "after":
        record["duration_sec"] = payload["duration_sec"]
    elif phase == "error":
        record["error_category"] = payload["error_category"]
    return record


def main(**payload):
    """Atomically replace the bounded audit snapshot for this lifecycle phase."""
    record = _safe_record(payload)
    destination = _audit_folder() / f"tool-{record['phase']}.json"
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return record
```

Four design points are worth copying:

- **The allowlist is explicit.** `_safe_record()` copies three named fields instead of serializing
  the payload, so a future payload field cannot leak into the audit file by accident.
- **The phase is derived, not passed.** One Module serves three points, so it reads the
  point-specific keyword instead of requiring three near-identical files.
- **The write is atomic.** A temporary file is renamed over the destination, so a reader never sees
  a half-written document.
- **The return value is ignored.** Returning the record is convenient for debugging, but the
  framework discards it; no veto, rewrite, or approval bypass is possible from here.

## The Failure Path

A tool that raises an ordinary exception produces a `before` record and an `error` record, and the
agent still receives the error text as the tool result. The response file now names a report that
does not exist:

```bash
printf 'topsailai.thought\nThe review needs the incident report.\ntopsailai.action\n{"tool_call": "file_tool-read_file", "tool_args": {"file_path": "/tmp/hook-audit-demo/absent-report.txt"}}\ntopsailai.final_answer\nThe report is not readable.\n' > /tmp/hook-audit-demo/response.txt
rm -f /tmp/hook-audit-demo/audit/*.json
uv run python cli/topsailai_simulate_agent_execute.py --file /tmp/hook-audit-demo/response.txt --only-tools file_tool
echo "--- audit folder"
ls -1 /tmp/hook-audit-demo/audit
for f in /tmp/hook-audit-demo/audit/*.json; do echo "--- $(basename "$f")"; cat "$f"; done
```

```text
[0] thought
The review needs the incident report.
The report is not readable.

[1] action
{"tool_call": "file_tool-read_file", "tool_args": {"file_path": "/tmp/hook-audit-demo/absent-report.txt"}}
-> observation: {'step_name': 'observation', 'raw_text': "[Errno 2] No such file or directory: '/tmp/hook-audit-demo/absent-report.txt'"}

Final answer:
The report is not readable.
--- audit folder
tool-before.json
tool-error.json
--- tool-before.json
{
  "argument_count": 1,
  "argument_keys": [
    "file_path"
  ],
  "phase": "before",
  "tool_name": "file_tool-read_file"
}
--- tool-error.json
{
  "argument_count": 1,
  "argument_keys": [
    "file_path"
  ],
  "error_category": "FileNotFoundError",
  "phase": "error",
  "tool_name": "file_tool-read_file"
}
```

The observation text contains the path, because that is the tool's own result and the agent needs
it. The audit file does not: it records `FileNotFoundError` and nothing else. That difference is the
whole point of the recipe — the agent keeps what it needs to work, the audit keeps only what a
reviewer needs to count.

## Bounded Growth

Three consecutive calls leave exactly two files, because each phase replaces its own snapshot:

```bash
rm -f /tmp/hook-audit-demo/audit/*.json
uv run python -c "
from topsailai.ai_base.agent_types.tool import exec_tool_func

def review_incident(report: str = '', limit: str = '20') -> str:
    return f'reviewed:{report}:{limit}'

for index in range(3):
    exec_tool_func(review_incident, {'report': f'incident-{index}', 'limit': '20'}, 'incident-review')
"
ls -1 /tmp/hook-audit-demo/audit
```

```text
tool-after.json
tool-before.json
```

The folder never accumulates one file per call. If a reviewer needs a history rather than a latest
state, that is a different task with a different risk, and it needs its own retention policy; this
example deliberately does not provide one.

## Terminal Exceptions and Denied Calls

A terminal exception stops the agent and produces only the `before` record:

```bash
rm -f /tmp/hook-audit-demo/audit/*.json
uv run python -c "
from topsailai.ai_base.agent_types.tool import exec_tool_func
from topsailai.ai_base.agent_types import exception as agent_exception

def end_process(report: str = '') -> str:
    raise agent_exception.AgentToolCallException('stop the agent')

try:
    exec_tool_func(end_process, {'report': 'incident-42'}, 'incident-review')
except agent_exception.AgentToolCallException as error:
    print('propagated:', type(error).__name__, error)
"
ls -1 /tmp/hook-audit-demo/audit
```

```text
propagated: AgentToolCallException stop the agent
tool-before.json
```

A call denied by the approval gate produces no record at all, because approval precedes the tool
body and all three points. With no TTY the prompt cannot be answered, so the `deny` policy decides:

```bash
rm -f /tmp/hook-audit-demo/audit/*.json
printf '[{"name": "deny-incident-review", "match": "incident-review", "mode": "require", "policy": "deny", "timeout": 1}]\n' > /tmp/hook-audit-demo/approval.json
TOPSAILAI_TOOL_APPROVAL_ENABLED=1 \
TOPSAILAI_TOOL_APPROVAL_RULES=/tmp/hook-audit-demo/approval.json \
TOPSAILAI_TOOL_APPROVAL_DEFAULT_TIMEOUT=1 \
uv run python -c "
from topsailai.ai_base.agent_types.tool import exec_tool_func
from topsailai.ai_base.tool_approval.exceptions import ToolApprovalDeniedError

def review_incident(report: str = '', limit: str = '20') -> str:
    return f'reviewed:{report}:{limit}'

try:
    print('tool result:', exec_tool_func(review_incident, {'report': 'incident-42', 'limit': '20'}, 'incident-review'))
except ToolApprovalDeniedError as error:
    print('raised:', type(error).__name__, error)
" 2>&1 < /dev/null
echo "--- audit folder"
ls -1 /tmp/hook-audit-demo/audit
```

```text
Approval timeout denied for tool [incident-review] instance=7e843848-87d8-4850-b095-63ab29001e42 policy=deny
raised: ToolApprovalDeniedError Tool 'incident-review' was not approved (status: denied).
--- audit folder
```

The request id is a fresh UUID on every run, so yours will differ. Two redirections matter here.
`< /dev/null` makes the run headless on purpose: the approval transport starts its input reader only
when stdin is a terminal, so without it the same command renders the prompt and waits. `2>&1` keeps
the `Approval timeout denied` line, which is written to stderr; a reader who keeps only stdout sees
the exception but not the reason.

Under a real terminal the same call first renders the request, and the timeout then resolves it. This
is an excerpt of that run, trimmed at both ends:

```text
[APPROVAL REQUEST] 7e843848-87d8-4850-b095-63ab29001e42
  Rule: deny-incident-review
  Pattern: incident-review
  Tool   : incident-review
  Timeout: 1.0s
  Policy : deny
  Args:
    report: incident-42
    limit: 20

  Type 'approve'(yes) or 'deny'(no): Approval timeout denied for tool [incident-review] instance=7e843848-87d8-4850-b095-63ab29001e42 policy=deny
```

The excerpt was captured by running the same command under a pseudo-terminal (`script -qec`), which is
the only way to see the prompt. Two blank lines precede `[APPROVAL REQUEST]` and the
`raised: ToolApprovalDeniedError ...` line follows the timeout message; both are trimmed here because
they repeat what the block above already shows.

The audit folder listing is empty. An audit that recorded denied calls would need a fourth point,
and there is none; if denial evidence matters, it belongs to the approval layer, not to this recipe.

## Rejected Inputs

The Module refuses a relative audit folder, and the failure is isolated: the tool still runs and
still returns its normal result. The traceback is filtered out here only to keep the block short; the
framework logs it at ERROR level with the point name and the failing handler.

```bash
TOPSAILAI_HOOK_POINTS='{"hook__aibase__before__tool_execute":{"modules":["/TopsailAI/src/topsailai/docs/cookbook/hook/examples/tool_audit"]}}' \
TOPSAILAI_COOKBOOK_HOOK_AUDIT_DIR="relative/audit" \
uv run python -c "
from topsailai.ai_base.agent_types.tool import exec_tool_func

def review_incident(report: str = '', limit: str = '20') -> str:
    return f'reviewed:{report}:{limit}'

print('tool result:', exec_tool_func(review_incident, {'report': 'incident-42', 'limit': '20'}, 'incident-review'))
" 2>&1 | grep -E "^(tool result|ValueError)"
```

```text
ValueError: TOPSAILAI_COOKBOOK_HOOK_AUDIT_DIR must name an existing absolute directory
ValueError: TOPSAILAI_COOKBOOK_HOOK_AUDIT_DIR must name an existing absolute directory
tool result: reviewed:incident-42:20
```

The message appears twice because the framework logs the Module failure and then logs the failed
handler record, each with its own traceback. The last line is the one that matters: a broken audit
must never break the work it observes, and the framework guarantees that by logging the Module
failure and continuing.

Malformed `TOPSAILAI_HOOK_POINTS` values are rejected before any Module is imported:

```bash
uv run python -c "
import topsailai.hooks as hooks

EXAMPLE = '/TopsailAI/src/topsailai/docs/cookbook/hook/examples/tool_audit'
NAME = 'hook__aibase__before__tool_execute'
for label, config in (
    ('relative Module folder', {NAME: {'modules': ['docs/cookbook/hook/examples/tool_audit']}}),
    ('unknown selection key', {NAME: {'modules': [EXAMPLE], 'extra': []}}),
    ('malformed point name', {'hook__aibase__during__tool_execute': {'modules': [EXAMPLE]}}),
):
    try:
        hooks.initialize_hook_points(config)
    except ValueError as error:
        print(f'{label}: ValueError: {error}')
"
```

```text
relative Module folder: ValueError: Hook resource paths must be absolute
unknown selection key: ValueError: Hook Point requires modules/scripts selections
malformed point name: ValueError: Invalid Hook Point name
```

A relative Module folder is rejected at configuration time, so the same mistake cannot be hidden
inside a Module. The point name grammar is `hook__<domain>__<before|after|error>__<action>`, and a
phase such as `during` is not part of it.

## Loader Behavior

These facts were read from `hooks/point_entry.py` and confirmed by running the loader, not assumed
from the mechanism's name. The probe builds throwaway folders under `/tmp/hook-audit-loader` and
prints one line per fact:

```bash
uv run python - <<'PY' 2>/dev/null
import pathlib
import shutil
import topsailai.hooks as hooks

NAME = "hook__aibase__before__tool_execute"
EXAMPLE = "/TopsailAI/src/topsailai/docs/cookbook/hook/examples/tool_audit"
DEMO = pathlib.Path("/tmp/hook-audit-loader")
shutil.rmtree(DEMO, ignore_errors=True)


def probe(config):
    hooks.initialize_hook_points(config)
    return hooks.invoke_hook_point(NAME, tool_name="probe", argument_count=0, argument_keys=())


def names(result):
    return [handler.handler.name for handler in result.handlers]


def folder(name, files):
    target = DEMO / name
    target.mkdir(parents=True, exist_ok=True)
    for filename, body in files.items():
        (target / filename).write_text(body)
    return str(target)


order = folder("order", {"zeta.py": "def main(**payload):\n    return 1\n",
                         "alpha.py": "def main(**payload):\n    return 1\n"})
print("filename order:", names(probe({NAME: {"modules": [order]}})))

veto = folder("veto", {"veto.py": "def main(**payload):\n    return {'block': True, 'rewrite': 'hijacked'}\n"})
result = probe({NAME: {"modules": [veto]}})
print("return ignored:", result.status, result.decision.action, result.handlers[0].returned.value)

nomain = folder("nomain", {"broken.py": "VALUE = 1\n"})
print("no main:", probe({NAME: {"modules": [nomain]}}).status)

dup_a = folder("dup-a", {"same.py": "def main(**payload):\n    return 1\n"})
dup_b = folder("dup-b", {"same.py": "def main(**payload):\n    return 1\n"})
result = probe({NAME: {"modules": [dup_a, dup_b]}})
print("duplicate filename:", result.status, result.cleanup.diagnostic.category)

result = probe({NAME: {"modules": [str(DEMO / "absent")]}})
print("missing folder:", result.status, result.cleanup.diagnostic.category)

print("single module file:", probe({NAME: {"modules": [EXAMPLE + "/tool_execution_audit.py"]}}).status)

scripts = DEMO / "scripts"
scripts.mkdir(parents=True, exist_ok=True)
(scripts / "audit.sh").write_text("#!/bin/sh\nexit 0\n")
(scripts / "audit.sh").chmod(0o755)
(scripts / "plain.sh").write_text("#!/bin/sh\nexit 0\n")
(scripts / "plain.sh").chmod(0o644)
result = probe({NAME: {"scripts": [str(scripts)]}})
print("non-executable script skipped:", [child.handler.name for child in result.handlers[-1].children])

print("empty selection:", names(probe({})))

nested = DEMO / "nested"
(nested / "inner").mkdir(parents=True, exist_ok=True)
(nested / "outer.py").write_text("def main(**payload):\n    return 1\n")
(nested / "inner" / "hidden.py").write_text("def main(**payload):\n    return 1\n")
(nested / "__init__.py").write_text("VALUE = 1\n")
print("direct children only:", names(probe({NAME: {"modules": [str(nested)]}})))

mixed = folder("mixed", {"beta.py": "def main(**payload):\n    return 1\n",
                         "Alpha.py": "def main(**payload):\n    return 1\n"})
print("name order is codepoint order:", names(probe({NAME: {"modules": [mixed]}})))

rediscover = pathlib.Path(folder("rediscover", {"alpha.py": "def main(**payload):\n    return 1\n"}))
hooks.initialize_hook_points({NAME: {"modules": [str(rediscover)]}})
first = hooks.invoke_hook_point(NAME, tool_name="probe", argument_count=0, argument_keys=())
(rediscover / "middle.py").write_text("def main(**payload):\n    return 2\n")
second = hooks.invoke_hook_point(NAME, tool_name="probe", argument_count=0, argument_keys=())
print("rediscovery:", names(first), "->", names(second))
PY
```

```text
filename order: ['alpha.py', 'zeta.py', 'hook_script']
return ignored: success continue {'block': True, 'rewrite': 'hijacked'}
no main: completed_with_errors
duplicate filename: unavailable discovery_failed
missing folder: unavailable discovery_failed
single module file: success
non-executable script skipped: ['audit.sh']
empty selection: ['hook_script']
direct children only: ['outer.py', 'hook_script']
name order is codepoint order: ['Alpha.py', 'beta.py', 'hook_script']
rediscovery: ['alpha.py', 'hook_script'] -> ['alpha.py', 'middle.py', 'hook_script']
```

| Requirement | Observed behavior |
|-------------|-------------------|
| Absolute Module path | Required. A relative path fails with `ValueError: Hook resource paths must be absolute`. |
| Folder or single file | Both accepted. A single `.py` path loads as one Module. |
| Direct children only | Nested sub-folders are not scanned; `nested/inner/hidden.py` never appears. |
| `__init__.py` | Excluded from discovery, so a package initializer cannot run as a Module. |
| Duplicate file names | Rejected atomically. Two folders containing `same.py` make the point `unavailable` with `discovery_failed`. |
| Missing folder | The point is `unavailable` with `discovery_failed`, not an empty success. |
| Module without `main` | The point reports `completed_with_errors`; other Modules still run. |
| Module return value | Ignored. A returned `{'block': True, 'rewrite': 'hijacked'}` leaves the decision `continue`. |
| Ordering | Codepoint order of the file name, so `Alpha.py` precedes `beta.py`; Modules run before the terminal `hook_script` group. |
| Non-executable Script | Silently skipped; only the executable `audit.sh` appears as a child. |
| Empty configuration | `{}` still discovers bundled point-local resources, so `hook_script` remains. |
| Membership | Rediscovered on every invocation, so a Module added later is picked up without a restart. |
| Configuration source | `TOPSAILAI_HOOK_POINTS` is read once and cached; changing the variable mid-process has no effect until `initialize_hook_points()` is called again. |

The last row is the one that surprises people, so it is worth showing:

```bash
TOPSAILAI_HOOK_POINTS='{"hook__aibase__before__tool_execute":{"modules":["/TopsailAI/src/topsailai/docs/cookbook/hook/examples/tool_audit"]}}' \
uv run python -c "
import os
import topsailai.hooks as hooks

NAME = 'hook__aibase__before__tool_execute'
first = hooks.invoke_hook_point(NAME, tool_name='probe', argument_count=0, argument_keys=())
os.environ['TOPSAILAI_HOOK_POINTS'] = '{}'
second = hooks.invoke_hook_point(NAME, tool_name='probe', argument_count=0, argument_keys=())
print('before:', [handler.handler.name for handler in first.handlers])
print('after :', [handler.handler.name for handler in second.handlers])
"
```

```text
before: ['tool_execution_audit.py', 'hook_script']
after : ['tool_execution_audit.py', 'hook_script']
```

The variable was set to `{}` between the two calls and the second call still used the cached
configuration. Membership is rediscovered per invocation; the configuration itself is not.

## What the Audit Cannot Do

- **It cannot block a tool.** Return values are discarded, so there is no veto.
- **It cannot rewrite arguments or results.** The payload is detached metadata; the Module never
  receives the live callable, the arguments, or the result.
- **It cannot be timed out.** Modules run in-process, so an overrunning Module is not killed. Keep
  the work small, as this example does.
- **It cannot see denied calls.** Approval precedes the points.
- **It cannot see a terminal exception as an error.** `AgentToolCallException` propagates without an
  error observation.
- **It is not a sandbox.** A Module is trusted in-process code with the agent's own privileges.

Key names are still metadata that can disclose intent: an argument named `password` or
`customer_email` appears in `argument_keys`. The example keeps key names because a reviewer needs to
know which inputs a tool took, and drops values because those are the sensitive part. If even key
names are unacceptable, project the payload onto a coarser allowlist instead of copying this one.

## Related Documents

- [Hooks Python API](../../Hooks_API.md) — the direct-entry contract, payload fields, and result format
- [Environment Variables](../../Environment_Variables.md) — `TOPSAILAI_HOOK_POINTS` and the tool-approval variables
- [Unified Hook Framework](../../../features/feature-unified-hooks-design.md) — why Modules run before the terminal `hook_script`
- [External Custom Tools](../tool/External_Custom_Tools.md) — how the tools being audited are registered
- [Cookbook](../README.md) — requirements every entry in this folder follows
