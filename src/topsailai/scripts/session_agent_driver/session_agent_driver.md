---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai/scripts/session_agent_driver
ProjectFolder: /TopsailAI/src/topsailai/scripts/session_agent_driver
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Session Agent Driver

A resident polling script that checks a target session and drives it with
suggested input. It starts an analysis agent (times=1) whenever the target
session is waiting for input, and exits when the session process exits or the
analysis agent requests exit.

The driver's core goal is to replace the human operator: the analysis agent
must make the "correct" decision or reply on the human's behalf, injecting the
best possible input for the target session's current state and task goal rather
than merely a plausible one. This goal is stated in the analysis prompt.

## Usage

```bash
python session_agent_driver.py --session SESSION_ID
# or
TOPSAILAI_SESSION_ID=SESSION_ID python session_agent_driver.py
```

The script loads `session_agent_driver.env` (same folder) with `override=False`
before importing topsailai, so process environment variables take precedence.

## Behavior

The polling loop checks the target session status:

| Status | Meaning | Driver action |
|---|---|---|
| `input` | process alive and holding the session pipe (waiting for input) | start analysis agent (times=1) |
| `running` | process alive but not waiting for input | wait for next poll |
| `idle` | process exited | exit the polling loop |

The analysis agent inspects the session context and calls one of the plugin
tools:

- `inject_input(session_id, content)` — inject suggested input into the target
  session. On injection failure it raises `AgentEndProcess`, which shuts the
  analysis agent down completely; the driver then continues polling.
- `exit_process(session_id=None)` — request the driver to exit its loop.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `TOPSAILAI_SESSION_ID` | *(none)* | Target session id to drive. |
| `TOPSAILAI_SESSION_DRIVER_POLL_INTERVAL` | `5` | Poll interval in seconds. |
| `TOPSAILAI_SESSION_DRIVER_TIMEOUT` | `120` | Single analysis timeout in seconds (SIGALRM). |
| `TOPSAILAI_SESSION_DRIVER_TASK_GOAL` | `Drive the target session to completion.` | Task goal injected into the analysis prompt. |
| `TOPSAILAI_SESSION_DRIVER_LOG_MAX_BYTES` | `10485760` | Positive maximum log size in bytes before rotation (10 MiB). |
| `TOPSAILAI_SESSION_DRIVER_LOG_MAX_BACKUPS` | `5` | Positive number of rotated log backups to retain. |
| `TOPSAILAI_PLUGIN_TOOLS` | `plugins.tools` | Plugin tools package (set by the script before importing topsailai). |
| `TOPSAILAI_PLUGIN_SKILLS` | `{script_dir}/plugins/skills` | Plugin skills directory (contains the `topsailai-skills` soft link to topsailai/skills, set by the script). |

## Runtime Records

After argument validation, the driver creates its records under
`{TOPSAILAI_HOME}/workspace/task/session_agent_driver/`:

- `{session_id}.lock` — cross-process lock file; deletion is attempted after release on exit.
- `{session_id}.meta` — an atomically replaced JSON snapshot of the latest driver run.
- `{session_id}.log` — driver logs retained only while the script runs.
- `{session_id}.log.1` through `.log.5` — rotated backups with default settings.

The filename uses the **target session ID**, not the temporary analysis-agent
session ID. `TOPSAILAI_HOME` follows the framework's home-directory configuration;
the record directory does not depend on the current working directory.

| Metadata field | Meaning |
|---|---|
| `version` | Record format version, currently `1`. |
| `session_id`, `run_id` | Target session ID and a unique identifier for this driver run. |
| `pid` | Driver process ID, not the target process ID. |
| `start_time`, `end_time`, `updated_at` | Local ISO timestamps with timezone offset; `end_time` is null while running. |
| `status` | `running`, `stopped` for a successful exit, or `failed` for a nonzero exit. |
| `target_status` | Latest observed target state; initially null. |
| `poll_interval` | Effective polling interval in seconds. |
| `exit_code` | Null while running; recorded on termination. |
| `stop_reason` | For example `target_exited`, `exit_requested`, `signal:15`, or an exception type. |

Normal exit, handled SIGINT/SIGTERM, and exceptional exit remove the session's
metadata, current log and numeric rotation backups after closing the log handler.
Failed lifecycle initialization also attempts cleanup. Every deletion is logged
to the remaining terminal/logging handlers. Unhandled ordinary exceptions record
a traceback before cleanup; these files are not a persistent exit history. Errors caught by the polling loop are
logged while polling continues; they do not imply the driver has stopped.

The log captures the driver's own logging, not all model responses or arbitrary
stdout/stderr from dependencies. Startup/import errors before lifecycle recording
begins cannot be captured in these files. SIGKILL, power loss, or failed metadata
writes can leave a stale `running` snapshot; verify process liveness rather than
using metadata alone as proof of a live driver.

Startup takes a nonblocking exclusive OS lock before opening logs or publishing
metadata. A competing driver for the same session is rejected without changing
or deleting the owner's records. Existing metadata with a live PID also rejects
startup; malformed or unverifiable owner evidence fails closed. Only a confirmed
dead PID permits recovery of stale metadata. Different sessions use separate locks.

The lock remains held through runtime-record cleanup. An admitted driver closes
its lock descriptor, checks whether the `.lock` file exists, and attempts to
delete it. Successful deletions are logged; missing files are harmless, and
filesystem failures warn without replacing the original termination error.
Rejected startup attempts close their descriptor without deleting the lock file.
A sequential restart recreates the lock and publishes a new `run_id`.

Release-then-delete is a best-effort cleanup tradeoff, not a race-free exclusion
protocol: a concurrent starter may open or acquire the old file before deletion,
while another starter subsequently creates and locks a new file. Avoid concurrent
restart of drivers for the same session when strict exclusion is required.
File existence alone does not prove that a driver holds the lock.

After a clean exit with successful cleanup, no session records remain. SIGKILL,
power loss, or filesystem permission/I/O failures can leave records behind;
failures are reported when the process can still execute. No other session files
are removed, and no automatic cross-target purge is provided.

## Plugin Tools

- `plugins/tools/inject_input.py` — injects input through the session FIFO pipe
  (equivalent to `topsailai runtime send`); raises `AgentEndProcess` on failure.
- `plugins/tools/exit_process.py` — sets a shared exit flag checked by the main
  loop.

## Plugin Skills

`plugins/skills` is the plugin skills directory. It contains the
`topsailai-skills` soft link to `/TopsailAI/src/topsailai/skills`, so the
analysis agent can load the `topsailai-agent-worker` skill for session query
and send instructions.

## Prompt Template

`prompts/analysis_prompt.md` is the analysis prompt template. It uses
`string.Template` placeholders (`$session_id`, `$pid`, `$status`,
`$project_workspace`, `$created_at`, `$task_goal`, `$messages_summary`). If the
template file is missing, a built-in default prompt is used.
