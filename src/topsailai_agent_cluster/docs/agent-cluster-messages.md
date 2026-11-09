---
maintainer: AI
author: DawsonLin
status: active
created: 2026-11-09
---

# Session Messages Abstraction

## Purpose and scope

This document describes the abstraction layer for the `messages` command. It is written
from the cluster's point of view: what the cluster must model, what it must parse, and
how it addresses a session that is not running.

The command answers one question the cluster could not answer before: **what did this
session actually say?** Every existing read surface needs a live target. `logs` requires a
generation, `ctl` requires a live control socket, and `send` requires a routable session.
A stopped session could only be resumed, never read.

Human requirement that defines this layer:

> 我要增加history.messages指令，workspace/endpoint scope 可以使用 `history.messages 序号/session_id`去获得session的messages, session scope不带参数，获得messages。

The command was implemented under the name `messages` rather than `history.messages`,
because its permission and its scope set both differ from `history`. See
"Name and permission" below.

## The problem this layer solves

Provider conversation data is **persisted**, but every existing delivery channel required
a **live process**:

| Surface | Needs a live process | Reads persisted data |
|---|---|---|
| `runtime control get_session_messages` | yes, a UDS socket | yes |
| `runtime logs` | yes, a generation | yes |
| `session history` | **no** | yes |

The mismatch was the whole gap. The provider already stores the messages; only the
transport demanded a running agent. `session history` is the one entry point that reads
the database directly, so it works for a session that stopped months ago.

`messages` therefore needs no generation, no liveness check and no inventory join. It is
the only read command that treats a live row and a stopped row identically.

## Provider contract

The adapter invokes two provider commands, both with `--json`:

```text
topsailai session info <session_id> --json
topsailai session history <session_id> --json [--max-chars N]
```

`session info` is the existence pre-check. It is required because `session history`
returns a successful empty document for a session that does not exist, so the two cases
are otherwise indistinguishable:

| Case | `session info --json` | Exit |
|---|---|---|
| Session exists | full fields, no `error_code` | 0 |
| Session missing | `{"session_id":"...","error_code":"session_not_found","message":"..."}` | 1 |
| Storage failure | `error_code: lookup_failed` | 1 |

`lookup_failed` is deliberately distinct from `session_not_found`. A provider fault must
never be reported as a deleted session, because the operator would then stop looking for
data that still exists.

`session history` returns:

```json
{
  "ok": true,
  "exit_code": 0,
  "action": "history",
  "session_id": "20261013131753",
  "message_count": 16,
  "messages": [
    {"content": "...", "create_time": "2026-10-13 13:18:48.450", "role": "user"}
  ],
  "error_code": null,
  "message": null
}
```

`create_time` is local wall-clock time without a zone, because the provider formats a
stored timestamp. The adapter interprets it in the endpoint's local zone, which is the
zone the provider ran in, and leaves the value zero when it cannot parse it. A missing
time is never presented as a real observation.

The adapter never passes `--db-conn`. That flag lets the caller choose the database, so
forwarding it would let a remote payload select which store is read. The provider's own
configured database is the only one the adapter may reach.

## Name and permission

The command is `messages`, not `history.messages`, for two reasons that are both
consequences of the project's own command-surface rules:

- **Different permission.** `history` requires `view`, because a history row carries only
  the session name, the task text and the workspace. `messages` carries conversation
  content, which is the most sensitive payload the cluster serves, so it requires
  `read_output`. A command that needs a stronger permission is a different command, not a
  spelling of the weaker one.
- **Different scope set.** `history` is unavailable in session scope, because it is an
  endpoint-scoped query. `messages` is available in session scope, where it takes no
  argument. A command available in a scope the other is not is a different command.

The dotted `ctl.<action>` spelling is a family prefix with a variable action name, so
`history.messages` would read as a member of a family that does not exist. `history.foo`
would then be an unknown command while `ctl.foo` is a valid family member, which is an
inconsistent grammar.

`ctl.session.messages` remains available as the provider-level spelling. It is a different
surface: it requires a live control socket, so it cannot read a stopped session. The two
do not conflict and neither replaces the other.

## Scope and argument matrix

| Scope | Accepted forms |
|---|---|
| workspace | `messages <row-number>` or `messages <endpoint> <session>` |
| endpoint | `messages <row-number>` or `messages <session>` |
| session | `messages` (no argument) |

The standalone form takes no row number, because a standalone process has no rendered
table:

```text
agent-cluster-cli messages <endpoint-id-or-hostname> <session> [--max-chars N] [--json]
```

A row number is an interactive convenience bound to the table the operator last saw. It is
never a contract, and it never appears on the standalone surface.

## Session addressing

A session token is resolved in this order:

1. A bare ASCII number in workspace or endpoint scope selects that row of the most
   recently rendered **history** table. A number is rejected when no history table is
   available, because a number with no table has no meaning.
2. A cluster resource ID is resolved through the persisted inventory to its provider
   session ID.
3. Any other token is used verbatim as a provider session ID.

The provider session ID is the only key that addresses a stopped session, because a
stopped session is absent from the inventory and therefore has no cluster resource ID.

A provider session ID may be duplicated. `docs/agent-cluster-history.md` already records
this, and `resume` refuses a bare provider session ID for the same reason. `messages`
resolves a provider session ID **within one endpoint only**, because the endpoint is always
known: workspace scope requires it as an argument, and endpoint and session scope already
name it. A token that matches several sessions inside one endpoint is rejected with the
candidate list rather than guessed.

## Read-only and namespace behaviour

`messages` is a pure read. It never mutates provider state, never submits a command and
never enters the command journal.

Unlike `history`, it does **not** clear the row-number namespace. `history` replaces the
namespace because it renders a new table, so an old number would silently mean a different
row. `messages` renders no table, so the numbers the operator is reading from stay valid
and rows 3, 4 and 5 can be read consecutively.

## Bounds and truncation

Three bounds apply, and every one of them is labelled when it is reached:

| Bound | Value | Meaning |
|---|---|---|
| `MaxMessages` | 1000 | accepted message count |
| `MaxMessageContentBytes` | 64 KiB | one message body |
| `MaxMessagesBytes` | 512 KiB | the whole accepted document |

`--max-chars` is forwarded to the provider, which truncates one message and appends an
ellipsis. The adapter applies its own byte bounds as well, because `--max-chars` bounds one
message only: a real session contained a single message of 105,871 words, so a per-message
bound alone cannot bound the document.

A truncated document is always labelled. A shortened answer must never be presented as
complete, because the operator would then believe the conversation ended where the bound
was reached.

## Rendering

Message content is untrusted. It is stripped of terminal control sequences before it is
written, using the same boundary `logs` already applies, so a message can never emit an
escape sequence that the terminal would execute.

The rendered form prints one block per message with its role and observation time, so the
operator can tell who spoke and when. The `--json` form writes the standard document
instead, so a script never has to parse the rendered text.

## Failure semantics

| Code | Status | Meaning |
|---|---|---|
| `messages_unsupported` | 501 | no configured adapter can read messages |
| `session_not_found` | 404 | the provider does not have this session |
| `messages_response_too_large` | 502 | the provider document exceeded a bound |
| `provider_error` | 502 | the provider call failed |
| `endpoint_unavailable` | 503 | the endpoint is not connected |
| `permission_denied` | 403 | the credential lacks `read_output` |

An empty message list is a successful answer, not an error. It means the session exists
and recorded no messages. It never means the session is missing, because the existence
pre-check already separated those cases.

## Authorization

The route requires `read_output`, resolved through one shared helper so a future messages
route cannot be added without the check. The check runs before the transport is consulted,
so an unauthorized caller cannot infer endpoint reachability or server capability from a
status code or a response time.

An empty scope set remains unrestricted, which models the single-credential deployment
where the one provisioned token is the administrator. Verification must narrow the scopes,
because a default deployment cannot distinguish a working check from a missing one.

## What this layer does not do

- It does not read provider files or the provider database directly. Only the provider CLI
  is invoked, so the provider keeps ownership of its own storage format.
- It does not persist messages. Nothing enters `endpoint_session_state`, and no message
  content is written to the audit log.
- It does not follow. A follow stream is a different capability with different semantics;
  `messages` returns one bounded snapshot.
- It does not resume. Reading a stopped session never starts it.
