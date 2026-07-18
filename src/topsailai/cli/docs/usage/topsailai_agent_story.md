---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_agent_story

Manage or display an agent's story memory.

## Purpose

Reads and writes story-level memory entries for an agent session. Story memory is used to preserve long-term context across multiple agent runs.

## Invocation

```bash
./topsailai_agent_story.py --session-id <session_id>
./topsailai_agent_story.py --session-id <session_id> --set <key> <value>
```

Because the script is registered in `../bin/` as `topsailai_agent_story`, you can also run it as:

```bash
topsailai_agent_story --session-id my-session
topsailai_agent_story --session-id my-session --set goal "Refactor CLI"
```

## Options

| Option | Description |
|--------|-------------|
| `--session-id <id>` | Required. Target session ID. |
| `--set <key> <value>` | Store a key/value pair in story memory. |
| `--get <key>` | Retrieve the value of a single key. |
| `--delete <key>` | Remove a key from story memory. |
| `--list` | List all keys in story memory. |
| `--db-conn <string>` | Database connection string (default: use session manager default). |
| `--json` | Output results as JSON. |

## Examples

```bash
# Show all story memory for a session
topsailai_agent_story --session-id my-session

# Set a story value
topsailai_agent_story --session-id my-session --set goal "Refactor CLI tools"

# Get a story value
topsailai_agent_story --session-id my-session --get goal

# Delete a story value
topsailai_agent_story --session-id my-session --delete goal

# List keys
topsailai_agent_story --session-id my-session --list
```

## Notes

- Story memory is persisted across agent restarts.
- Values are stored as strings; complex data should be serialized to JSON before storage.
