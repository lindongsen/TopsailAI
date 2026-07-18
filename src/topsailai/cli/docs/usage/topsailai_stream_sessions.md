---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_stream_sessions

Stream session messages in real time, similar to `tail -f`.

## Purpose

Continuously polls the session manager for new messages and prints them immediately. Can stream a single session or all sessions.

## Invocation

```bash
./topsailai_stream_sessions.py
./topsailai_stream_sessions.py --session-id <session_id>
./topsailai_stream_sessions.py --session-id <session_id> --poll-interval 0.5
```

Because the script is registered in `../bin/` as `topsailai_stream_sessions`, you can also run it as:

```bash
topsailai_stream_sessions
topsailai_stream_sessions --session-id my-session
```

## Options

| Option | Description |
|--------|-------------|
| `--db-conn <string>` | Database connection string (default: use session manager default). |
| `--session-id <id>` | Stream a specific session. If omitted, stream all sessions. |
| `--poll-interval <seconds>` | Interval between polls (default: 1.0). |
| `--max-messages <N>` | Maximum number of historical messages to show on first run (default: 50). |
| `--log-level <LEVEL>` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` (default: `INFO`). |

## Output Format

Each message is printed with a timestamp and message ID, followed by the formatted content. Messages that contain nested `step_name`/`raw_text` JSON are unpacked for readability.

## Examples

```bash
# Stream all sessions
topsailai_stream_sessions

# Stream a specific session
topsailai_stream_sessions --session-id my-session

# Faster polling, more initial history
topsailai_stream_sessions --session-id my-session --poll-interval 0.5 --max-messages 100

# Debug logging
topsailai_stream_sessions --log-level DEBUG
```

## Notes

- Press `Ctrl+C` to stop streaming.
- The script validates that `poll-interval` and `max-messages` are positive.
