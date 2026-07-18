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
