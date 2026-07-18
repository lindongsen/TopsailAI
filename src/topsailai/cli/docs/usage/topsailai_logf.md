---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_logf

Follow (tail) a session or task log file.

## Purpose

Streams the contents of a session or task stdout/stderr file in real time, similar to `tail -f`. It is useful when you want to watch a log without entering the interactive `topsailai.py` UI.

## Invocation

```bash
./topsailai_logf.py <file>
./topsailai_logf.py --session-id <session_id>
```

Because the script is registered in `../bin/` as `topsailai_logf`, you can also run it as:

```bash
topsailai_logf /path/to/session.stdout
topsailai_logf --session-id my-session
```

## Options

| Option | Description |
|--------|-------------|
| `file` | Path to the log file to follow. |
| `--session-id <id>` | Discover the most recent stdout file for the session and follow it. |
| `--stderr` | Follow the stderr file instead of stdout. |
| `--lines <n>` | Number of lines to print from the end before streaming (default: 10). |
| `--poll-interval <seconds>` | Polling interval when native inotify is unavailable (default: 0.5). |
| `--no-color` | Disable colored output. |

## Examples

```bash
# Follow a specific log file
topsailai_logf /tmp/my-session.1234.session.stdout

# Follow the latest stdout for a session
topsailai_logf --session-id my-session

# Follow stderr and show the last 50 lines
topsailai_logf --session-id my-session --stderr --lines 50

# Plain output
topsailai_logf --session-id my-session --no-color
```

## Notes

- The script exits when the watched file is removed or when interrupted with `Ctrl+C`.
- If `--session-id` matches multiple files, the most recently modified one is selected.
