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
| `TOPSAILAI_PLUGIN_TOOLS` | `plugins.tools` | Plugin tools package (set by the script before importing topsailai). |
| `TOPSAILAI_PLUGIN_SKILLS` | `{script_dir}/plugins/skills/topsailai-skills` | Plugin skills directory (soft link to topsailai/skills, set by the script). |

## Plugin Tools

- `plugins/tools/inject_input.py` — injects input through the session FIFO pipe
  (equivalent to `topsailai runtime send`); raises `AgentEndProcess` on failure.
- `plugins/tools/exit_process.py` — sets a shared exit flag checked by the main
  loop.

## Plugin Skills

`plugins/skills/topsailai-skills` is a soft link to
`/TopsailAI/src/topsailai/skills`, so the analysis agent can load the
`topsailai-agent-worker` skill for session query and send instructions.

## Prompt Template

`prompts/analysis_prompt.md` is the analysis prompt template. It uses
`string.Template` placeholders (`$session_id`, `$pid`, `$status`,
`$project_workspace`, `$created_at`, `$task_goal`, `$messages_summary`). If the
template file is missing, a built-in default prompt is used.
