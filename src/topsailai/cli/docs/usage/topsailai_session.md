---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai session

Inspect and update one session without entering session scope.

## Purpose

Session scope is a stateful interactive context: it remembers the current
session, loads its own readline history, and changes the prompt. A one-shot
subcommand cannot enter it, so this subcommand provides the stateless
equivalents of the session-scope commands.

The boundary with `topsailai runtime` is deliberate:

- `topsailai runtime` acts on a **live** session: send, btw, control, logs.
- `topsailai session` reads and updates the session's **stored record**.

Operations that already exist under `topsailai runtime` are not duplicated
here.

## Invocation

```bash
topsailai session <ACTION> [OPTIONS]
```

A bare `topsailai session` and `topsailai session --help` both print the help
and exit with status 0.

## Actions

| Action | Description |
|--------|-------------|
| `info <SESSION_ID> [<SESSION_ID> ...]` | Show one session's detail, or several sessions' detail in one call. One identifier uses the single-session renderer; two or more use the batch renderer. |
| `list [OPTIONS]` | List stored sessions from the session database. |
| `status <SESSION_ID>` | Report the lock-based `idle` or `processing` state of one session. |
| `history <SESSION_ID> [--max-chars N] [--json]` | Print the stored context messages of one session. |
| `search <SESSION_ID> <KEYWORD>` | Search one session's context by keyword. |
| `add-msg <SESSION_ID> -m <TEXT>` | Append one persistent user-to-agent message to a session. |
| `delete <SESSION_ID> <PID>` | Delete exactly one invalid session stdout file. |

### `info`

```bash
topsailai session info 20261107021807
topsailai session info 20261107021807 20261106093012 --json
```

Options: `--json`, `--no-color`, `--db-conn <string>`, `--home <path>`.

### `list`

```bash
topsailai session list --limit 20
topsailai session list --has-project --sort desc --json
topsailai session list --included-categories agent,chat
topsailai session list --excluded-categories agent_driver
topsailai session list --excluded-categories agent_driver,agent --limit 5
```

Options: `--json`, `--no-color`, `--has-project`, `--category <name>`,
`--included-categories <names>`, `--excluded-categories <names>`, `--limit <N>`,
`--offset <N>`, `--sort asc|desc`, `--db-conn <string>`.

`--category` accepts exactly one value made of lowercase letters, digits, and
underscores, or an empty value for uncategorized sessions; a repeated option or
any other character is rejected with exit code `2`.

`--included-categories` and `--excluded-categories` accept comma-separated names
and may be repeated; an empty value selects or excludes uncategorized sessions,
and an invalid name is rejected with exit code `1`. Both are applied in the
database, so `--offset` and `--limit` select a page of surviving rows. See
`ai_list_sessions.md` for the full semantics.

### `status`

```bash
topsailai session status 20261107021807
topsailai session status 20261107021807 --json
```

Options: `--json`.

`status` and `info` answer different questions and may disagree:

- `status` reads the **session lock**. It reports whether a task currently
  holds the session, as `idle` or `processing`.
- `info` reports **process liveness** derived from the session stdout file and
  the owning process.

A session can be `idle` while a process still exists, or `processing` while no
stdout file is present. Use `status` for "is a task running" and `info` for
"what is this session".

### `history`

```bash
topsailai session history 20261107021807
topsailai session history 20261107021807 --max-chars 200
topsailai session history 20261107021807 --json
```

Options: `--max-chars <N>`, `--json`, `--db-conn <string>`.

`--max-chars` keeps one meaning in both modes: each message `content` is
limited to N characters and an ellipsis is appended when truncation happens.
In `--json` mode the limit is applied to the message objects before they are
serialized, so a machine consumer sees exactly the truncation a human sees.

A session with no stored messages is an empty array with `message_count` `0`,
not an error.

### `search`

```bash
topsailai session search 20261107021807 timeout
```

This invokes the registered `/ctx.search` instruction, which runs one agent
turn. It is not a read-only database query.

### `add-msg`

```bash
topsailai session add-msg 20261107021807 -m 'please retry'
topsailai session add-msg 20261107021807 -m 'please retry' --json
```

Options: `-m/--message <TEXT>` (required), `--json`.

The message is persistent and is delivered on the session's next agent run. An
empty or whitespace-only message is rejected as a usage error.

### `delete`

```bash
topsailai session delete 20261107021807 2175537
topsailai session delete '(temp)' 2175537 --json
```

Options: `--json`, `--home <path>`.

`delete` removes exactly one file:

```text
{TOPSAILAI_HOME}/workspace/task/{session_id}.{pid}.session.stdout
```

The session ID and PID together identify the target, so a different PID of the
same session and a different session with the same PID are both untouched.

The file is deleted **only** when it is provably invalid:

1. The file exists.
2. The owning process is proven dead.
3. No process holds the file open.

Liveness is checked in this order:

1. **Control-channel heartbeat (first priority).** When
   `{session_id}.{pid}.session.sock` exists, a bounded `heartbeat` request is
   sent with a 3-second timeout. Any correlated `ok` reply proves the session is
   running and the deletion is refused with `target_alive`. The reply payload is
   deliberately not inspected: the answering process may live in a sibling
   container whose PID namespace differs from the one recorded in the filename,
   so a session that answers is alive even when its recorded PID differs. This
   is the only probe that sees a session running in a sibling container that
   shares the same filesystem, because the local process table cannot observe
   that owner.
2. **Process table.** When the socket is absent, the heartbeat times out, or
   the endpoint is refused, the process-table probe decides instead.

A live owner is refused. An owner whose state cannot be verified is also
refused, because "cannot prove it is gone" is not "it is gone". A refused
connection (`ECONNREFUSED`) proves the listener is gone and falls through to the
process-table probe rather than being treated as a live session.

Related `stderr`, `pipe` and `inject` files are **not** deleted. They are
reported as `remaining_related_files` and left to the existing orphan cleanup.

Every successful deletion is logged with the removed path. In `--json` mode the
log goes to stderr so stdout stays machine-parseable.

For a temporary session, pass the display sentinel `(temp)`; it is translated to
the on-disk prefix `topsailai`.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success. |
| 1 | `history` only: the stored messages could not be read, or the retrieval command returned an unusable document. |
| 2 | Usage error: unknown action, missing or invalid argument, conflicting repeated option, empty message. |
| 3 | `delete` only: the target is not a deletable invalid stdout (`target_not_found`, `target_alive`, `target_identity_unavailable`, `file_in_use`). |
| 4 | `delete` only: the file exists and is invalid, but removal failed. |
| 127 | A required child command is not installed. |

## JSON output

`info`, `list`, `status`, `history`, `add-msg` and `delete` accept `--json`.

`delete` and `status` emit one JSON object:

```json
{
  "ok": true,
  "exit_code": 0,
  "action": "delete",
  "session_id": "20261107021807",
  "pid": 2175537,
  "path": "/root/.topsailai/workspace/task/20261107021807.2175537.session.stdout",
  "error_code": null,
  "message": null,
  "remaining_related_files": []
}
```

A refusal sets `ok` to `false` and fills `error_code` and `message`.

`history` emits one JSON object whose `messages` is the stored message array:

```json
{
  "ok": true,
  "exit_code": 0,
  "action": "history",
  "session_id": "20261107021807",
  "message_count": 2,
  "messages": [
    {"role": "user", "content": "hello"},
    {"role": "assistant", "content": "hi"}
  ],
  "error_code": null,
  "message": null
}
```

A failed read keeps stdout a single parseable object: `ok` is `false`,
`messages` and `message_count` are `null`, and `error_code` is
`history_unavailable` or `command_missing`. A child diagnostic is never mixed
into stdout.

## Relationship to session scope

| Session-scope command | Non-interactive equivalent |
|---|---|
| `/ctx.history` | `topsailai session history <id>` |
| `/ctx.search` | `topsailai session search <id> <keyword>` |
| `/ctx.add_msg` | `topsailai session add-msg <id> -m <text>` |
| `/send` | `topsailai runtime send` |
| `/ctx.btw` | `topsailai runtime btw` |
| `/control`, `/control.*` | `topsailai runtime control <action>` |
| `/cd` | none; entering a scope is interactive only |

`/git.status`, `/git.diff` and `/git {args}` have no non-interactive
equivalent here by design.

## Notes

- `search` runs one agent turn and therefore needs a usable session; it is not
  a pure read.
- `history` runs as a child process because the backing script changes its
  working directory while importing and resolves its default database relative
  to that directory.
- `delete` is a filesystem operation on the task directory. It is not a
  security boundary against a hostile task directory or other local users.
