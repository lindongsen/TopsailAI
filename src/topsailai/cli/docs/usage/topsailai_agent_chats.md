---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_agent_chats

Multi-turn interactive chat with a single AI agent.

## Purpose

Runs a continuous conversational session with one AI agent. Unlike
`topsailai_agent_chat` (single turn) or `topsailai_agent_plan_tasks`
(sub-agent orchestration), this tool keeps talking until the user exits. It is
a single-agent workflow: the `agent_tool` is disabled to prevent recursive
agent calls, and no `subagent_tool` is enabled.

## Invocation

```bash
./topsailai_agent_chats.py [message ...]
```

Because the script is registered in `../bin/` as `topsailai_agent_chats`, you
can also run it as:

```bash
topsailai_agent_chats [message ...]
```

## Arguments

| Argument | Description |
|----------|-------------|
| `message` | Optional initial chat content. |

## Options

| Option | Description |
|--------|-------------|
| `-h`, `--help` | Show the help message and exit. |

## Configuration

Configured through environment variables:

- `SESSION_ID` — session identifier for maintaining conversation history.
  Falls back to `TOPSAILAI_SESSION_ID` when not set.
- `SYSTEM_PROMPT` — a file path or inline content for the system prompt.
- `CHAT_MULTI_LINE` — enables multi-line input (set to `1` by the `bin/` wrapper).
- `DEBUG` — debug verbosity (set to `1` by the `bin/` wrapper).

### Continuing history across turns

The `bin/topsailai_agent_chats` wrapper exports
`TOPSAILAI_AGENT2LLM_KEEP_MESSAGES_ACROSS_TURNS=1`. With this flag enabled, the
Agent2LLM message list is preserved across user2agent turns (instead of being
reset), so each round inherits the previous history and the conversation
continues seamlessly.

This differs from `topsailai_agent_plan_tasks`, which does not set the flag and
therefore starts each user2agent dialogue with a clean context.

## Examples

```bash
# Start an interactive multi-turn chat
topsailai_agent_chats

# Chat with an initial message
topsailai_agent_chats "Hello, let us review the project"

# Use a persistent session and a system prompt file
SESSION_ID=my-session SYSTEM_PROMPT=/path/to/system.txt topsailai_agent_chats

# Show help
topsailai_agent_chats -h
```

## Notes

- This is a single-agent, multi-turn chat; the `agent_tool` is disabled to
  avoid recursive agent calls.
- Exit by typing `exit`, `quit`, or pressing `Ctrl+C`.
- Session history can be maintained through `SESSION_ID`.
