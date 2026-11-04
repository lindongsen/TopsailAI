---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_session_add_message

Add a persistent message to the user-to-agent context store.

## Purpose

This command records a user message in the persistent session context. The message is not visible to a currently running agent; it will be picked up the next time the agent starts for that session.

## Invocation

```bash
./topsailai_session_add_message.py -s <session_id> -m "message"
```

Because the script is registered in `../bin/` as `topsailai_session_add_message`, you can also run it as:

```bash
topsailai_session_add_message -s <session_id> -m "message"
```

## Options

| Option | Description |
|--------|-------------|
| `-s`, `--session_id <id>` | Target session ID. Required. If empty, falls back to the current `TOPSAILAI_SESSION_ID` environment value. |
| `-m`, `--message <text>` | Message text to store. Required. |

## Examples

```bash
# Add a message to a session
topsailai_session_add_message -s my-session -m "remember to update the docs"

# Use the current environment session ID
topsailai_session_add_message -s "" -m "follow up tomorrow"
```

## Notes

- This command targets the `user2agent` conversation layer.
- For immediate delivery to a running agent, use `topsailai_session_add_agent2llm_message` instead.

## Choosing Between the Two Message Commands

These two commands append messages to a session, but they target different conversation layers and have different lifecycles.

| Command | Conversation layer | When it takes effect | Use case |
|---|---|---|---|
| `topsailai_session_add_message` | `user2agent` — user and agent conversation | Only after the agent restarts; not visible to a running agent | Record a user message or context for the next agent run |
| `topsailai_session_add_agent2llm_message` | `agent2llm` — agent and LLM conversation | Immediately; the running agent reads it on the fly | Leave a "by the way" note for the currently running agent |

In short: use `topsailai_session_add_message` for persistent user-to-agent context, and `topsailai_session_add_agent2llm_message` when you want a running agent to pick up extra instruction right now.
