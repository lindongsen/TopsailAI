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


Each analysis Agent session is explicitly created with the `agent_driver` category,
which takes precedence over `TOPSAILAI_SESSION_CATEGORY` for that analysis
session. The driver does not change the target session's category or reclassify
historical sessions.
The analysis agent inspects the session context and calls one of the plugin
tools:

- `inject_input(session_id, content)` — inject suggested input into the target
  session. Before delivery, CRLF, CR, and LF newline separators in `content`
  are replaced with `;`. On injection failure it raises `AgentEndProcess`,
  which shuts the analysis agent down completely; the driver then continues
  polling.
- `exit_process(session_id=None)` — request the driver to exit its loop.

## Analysis Session Retention Is Intentional

**Human decision — 2026-10-31. Status: intentional designed behavior, not a bug (formerly review finding P1 #2).**

Human.Topsail said:

> 这个问题不解决，我是特意为之，你记到它的文档里面。下次遇到就有依据了，避免被认为是bug。

The driver owns each analysis round and deliberately runs the analysis Agent in its own long-lived process. Finishing a round does not end that process. Analysis metadata therefore records the driver PID, and the public cleanup guard refuses deletion while that owner is alive. The driver deliberately retains the analysis session record rather than weakening the general fail-closed PID-exit protection for analysis sessions.

**Expected consequence:** analysis session DB rows/history accumulate across rounds by design. A completed analysis round whose session remains present while the driver is alive is expected retention, not a leak to fix or a defect to re-report. This is distinct from cleanup of the driver's own lock, metadata and logs described below; process exit alone does not automatically delete analysis DB/history records or guarantee cleanup authorization.

Current source evidence (paths relative to the project workspace, verified 2026-10-31):

- `scripts/session_agent_driver/session_agent_driver.py:433, 451–473` allocates a per-round analysis ID and runs the Agent in-process; `486–492` attempts cleanup, and `363–375` preserves the record when deletion is refused.
- `workspace/session_meta.py:233–241` records the current PID (`os.getpid()`).
- `context/session_cleanup.py:55–68` preserves the public authorization checks before storage deletion.
- `context/session_activity.py:115–120, 186–193` permits only STOPPED and treats a live owner as RUNNING, without trusting completion flags.

Do not bypass the public cleanup guard, add force-delete or environment bypass switches, treat `completed`/`end_ts` as process-exit evidence, delete metadata to hide a live owner, move lifecycle policy into SQL, or weaken RUNNING/UNKNOWN fail-closed semantics. Changing this retention policy requires a new explicit Human decision, not a bug fix. The earlier alternatives A/B/C and implementation units A1/A2/A3 are superseded and must not be implemented on the authority of that proposal.

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
