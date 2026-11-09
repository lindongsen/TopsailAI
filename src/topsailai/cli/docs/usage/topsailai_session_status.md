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
| `--json` | Emit one structured JSON result instead of a bare status word. |

## Output

Without `--json`, the script prints one of the following strings to stdout:

- `idle` — the session lock was acquired; no task is currently working.
- `processing` — the session lock was not acquired; a task is running.

With `--json`, the script prints exactly one JSON object:

```json
{"session_id": "my-session", "status": "idle", "error_code": null, "message": null}
```

`status` is `idle` or `processing` on success and `null` on failure. `error_code` is `null` on success, `missing_session_id` when no session ID is available, and `status_unavailable` when the lock backend raises an error. `message` carries the human-readable detail for a failure and is `null` on success. A failure still emits one parseable object, so a caller never has to parse stderr to tell success from failure.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | The status was determined and printed. |
| 1 | No session ID was available, or the session lock could not be checked. |

## Examples

```bash
# Check a specific session
topsailai_session_status -s my-session

# Use the environment session ID
export TOPSAILAI_SESSION_ID=my-session
topsailai_session_status

# Emit one structured JSON result
topsailai_session_status -s my-session --json
```

## Notes

- If neither `--session` nor `TOPSAILAI_SESSION_ID` is set, the script exits with an error.
- Without `--json`, a failure is reported on stderr and stdout stays empty.
