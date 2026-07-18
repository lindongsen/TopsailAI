---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_session_status

Check whether a session is idle or processing.

## Purpose

This command checks the session lock for a given session ID. If the lock can be acquired, the session is considered idle; otherwise, it is processing. It is primarily used by the agent daemon to determine session state.

## Invocation

```bash
./topsailai_session_status.py -s <session_id>
./topsailai_session_status.py --session <session_id>
```

Because the script is registered in `../bin/` as `topsailai_session_status`, you can also run it as:

```bash
topsailai_session_status -s <session_id>
```

## Options

| Option | Description |
|--------|-------------|
| `-s`, `--session <id>` | Session ID to check. If omitted, the `TOPSAILAI_SESSION_ID` environment variable is used. |

## Output

The script prints one of the following strings to stdout:

- `idle` — the session lock was acquired; no task is currently working.
- `processing` — the session lock was not acquired; a task is running.

## Examples

```bash
# Check a specific session
topsailai_session_status -s my-session

# Use the environment session ID
export TOPSAILAI_SESSION_ID=my-session
topsailai_session_status
```

## Notes

- If neither `--session` nor `TOPSAILAI_SESSION_ID` is set, the script exits with an error.
