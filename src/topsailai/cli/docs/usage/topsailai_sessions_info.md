---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_sessions_info

Display detailed information about multiple sessions in one invocation.

## Purpose

Queries the session storage for every requested session ID and prints the same
per-session content as [`topsailai_session_info`](topsailai_session_info.md): the
same card fields in text mode and the same JSON record in JSON mode. The only
difference is that one invocation accepts many session IDs and resolves them with
a single storage query.

## Cost

Two costs are bounded independently of the number of requested identifiers:

- All identifiers are resolved with **one** storage query, not one query per
  session.
- Every running status is derived from **one** scan of the session stdout
  directory under `{TOPSAILAI_HOME}/workspace/task/`. The single-session command
  scans that directory once per session, so calling it in a loop costs
  O(sessions x directory entries); this command pays one scan for the whole
  batch.

The per-session rendering itself is linear in the number of sessions, so a very
large batch still costs proportionally more to format and print.

## Invocation

```bash
./topsailai_sessions_info.py <session_id> [<session_id> ...]
./topsailai_sessions_info.py <session_id> [<session_id> ...] --json
```

Because the script is registered in `../bin/` as `topsailai_sessions_info`, you can
also run it as:

```bash
topsailai_sessions_info <session_id> [<session_id> ...]
```

## Options

| Option | Description |
|--------|-------------|
| `session_ids` | Positional argument: one or more session identifiers to look up. At least one is required. |
| `--db-conn <string>` | Optional database connection string (default: use session manager default). |
| `--home <path>` | Override `TOPSAILAI_HOME` directory. |
| `--no-color` | Disable colored output. |
| `--json` | Output the session information as a JSON array. |

## Output

Text mode prints one card per found session, separated by a blank line. Each card
is byte-identical to the card printed by `topsailai_session_info` for the same
session, including the `Session Information` title, the field labels, and the
wrapped task text.

JSON mode prints a JSON array whose elements are byte-identical to the objects
printed by `topsailai_session_info --json`. The array shape does not change with
the number of identifiers, so a single identifier still produces a one-element
array.

The per-session fields are the same as `topsailai_session_info`; see
[`topsailai_session_info`](topsailai_session_info.md) for the field table.

## Ordering and duplicates

- Sessions are printed in the order the identifiers were given on the command
  line, not in the storage default `create_time` order.
- A repeated identifier is queried and printed once, at its first occurrence.
- Empty or whitespace-only identifiers are ignored.

## Missing sessions and exit codes

| Situation | stdout | stderr | Exit code |
|-----------|--------|--------|-----------|
| Every requested session found | cards or JSON array | empty | `0` |
| Some requested sessions missing | cards or JSON array of the found sessions | `[INFO] Session not found: <id>` per missing identifier | `1` |
| Every requested session missing, text mode | empty | `[INFO] Session not found: <id>` per identifier | `1` |
| Every requested session missing, JSON mode | `[]` | `[INFO] Session not found: <id>` per identifier | `1` |
| Storage error | empty | `[ERROR] <message>` | `1` |
| No identifier given | empty | `[ERROR] No session identifier provided` or argparse usage error | `2` |

Every diagnostic is written to stderr in both output modes, so stdout stays
machine-parseable: a partial batch still yields a valid JSON array of the found
sessions, and a storage error yields empty stdout rather than an `[ERROR]` line
that would make the payload unparseable. `--no-color` also applies to these
diagnostics, so stderr carries no ANSI escape sequences when it is set.

## Examples

```bash
# Display cards for three sessions
topsailai_sessions_info s1 s2 s3

# JSON array for two sessions
topsailai_sessions_info s1 s2 --json

# Use a custom database and home directory
topsailai_sessions_info s1 s2 --db-conn sqlite:///custom.db --home /path/to/home
```
