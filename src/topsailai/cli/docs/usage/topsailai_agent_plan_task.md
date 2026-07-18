---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_agent_plan_task

Plan and execute a single task agent for TopsailAI CLI.

## Purpose

Runs the TopsailAI sub-agent main loop once (`times=1`). The agent reads its task from the session store and produces a structured plan that the runtime can execute later.

## Invocation

```bash
./topsailai_agent_plan_task.py [message ...]
```

Because the script is registered in `../bin/` as `topsailai_agent_plan_task`, you can also run it as:

```bash
topsailai_agent_plan_task [message ...]
```

## Arguments

| Argument | Description |
|----------|-------------|
| `message` | Optional arguments accepted for backward compatibility. They are parsed but not forwarded to the agent; the agent resolves its task internally. |

## Options

| Option | Description |
|--------|-------------|
| `-h`, `--help` | Show the help message and exit. |

## Configuration

The script is configured through environment variables and the session store:

- `TOPSAILAI_ENABLED_TOOLS` — the script appends `subagent_tool` to the enabled tools list.
- `SESSION_ID` / session manager — the agent resolves its target session at runtime.

## Examples

```bash
# Run the single-task planner
topsailai_agent_plan_task

# Backward-compatible bare arguments are accepted but ignored
topsailai_agent_plan_task summarize the latest session

# Show help
topsailai_agent_plan_task -h
```

## Notes

- The task is read from the active session; the agent has its own internal argument handling.
- If the session or task context is missing, the agent runtime reports the error.
