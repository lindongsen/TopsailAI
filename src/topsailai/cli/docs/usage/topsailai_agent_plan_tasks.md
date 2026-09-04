---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_agent_plan_tasks

Plan and execute task agents for TopsailAI CLI.

## Purpose

Runs the TopsailAI sub-agent main loop continuously. The agent reads tasks from the session store and produces structured plans that the runtime can execute later.

## Invocation

```bash
./topsailai_agent_plan_tasks.py [message ...]
```

Because the script is registered in `../bin/` as `topsailai_agent_plan_tasks`, you can also run it as:

```bash
topsailai_agent_plan_tasks [message ...]
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

### Clean context per turn

Unlike `topsailai_agent_chats`, this script does **not** set
`TOPSAILAI_AGENT2LLM_KEEP_MESSAGES_ACROSS_TURNS`. Consequently the flag stays at
its default (`False`), so the Agent2LLM message list is reset at the start of
each user2agent dialogue. Every invocation therefore begins with a clean
context instead of carrying over history from a previous turn.

By contrast, `bin/topsailai_agent_chats` exports
`TOPSAILAI_AGENT2LLM_KEEP_MESSAGES_ACROSS_TURNS=1`, which preserves the
Agent2LLM history across turns so a multi-turn chat continues seamlessly.

## Examples

```bash
# Run the multi-task planner
topsailai_agent_plan_tasks

# Backward-compatible bare arguments are accepted but ignored
topsailai_agent_plan_tasks plan all pending tasks

# Show help
topsailai_agent_plan_tasks -h
```

## Notes

- Tasks are read from the active session; the agent has its own internal argument handling.
- If the session or task context is missing, the agent runtime reports the error.
- Because `TOPSAILAI_AGENT2LLM_KEEP_MESSAGES_ACROSS_TURNS` is not set, sub-agent instances are not reused across turns either; each turn gets a fresh context.
- The Manager and each Subagent build their own system/tool prompt. Shared Skill and Memory startup context is not propagated as a user-session observation, avoiding duplicate nested-agent context.
