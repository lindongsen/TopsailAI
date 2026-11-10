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
topsailai session history <session_id> --json
```

Neither command receives `--max-chars`, even when the caller asked for a display bound. The
provider would truncate the raw stored document, which cuts a structured body into invalid
JSON, so the bound is applied by the adapter after unwrapping instead.

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

Two acceptance bounds apply, and neither is a display decision:

| Bound | Value | Meaning |
|---|---|---|
| `MaxMessages` | 1000 | accepted message count |
| `MaxMessagesBytes` | 512 KiB | the whole accepted provider document |

There is deliberately no per-message byte bound. The document bound already rejects anything
larger, so a second bound could only ever cut a body that had already been accepted, and that
cut would be silent: the operator would read a shortened message as a complete one. An
over-ceiling body is a defect, not a display decision, so it fails closed at the document
check instead of being trimmed.

`--max-chars` is never forwarded to the provider. The provider truncates the raw stored
document, which cuts a structured body into invalid JSON, and the adapter would then be unable
to unwrap exactly the long messages an operator most wants to read. The bound is applied after
unwrapping, so it shortens readable text instead of corrupting the record.

The caller's bound is counted in characters and clamped to `MaxMessagesMaxChars` (100000)
rather than rejected, so a caller cannot ask for a bound the provider would silently reduce.
A shortened body always ends with an ellipsis.

Two different facts are labelled separately, because one boolean cannot carry both:

| Fact | Label |
|---|---|
| messages are missing | `conversation is a bounded window: N of M messages shown` |
| every message present, one body shortened | `one or more message bodies were shortened to the requested bound` |
| neither | no label, so the output is byte-identical to the provider |

The window case is judged first, because a report that omitted messages may also have
shortened the ones it kept, and the missing messages are the more important fact. A shortened
answer must never be presented as complete, because the operator would then believe the
conversation ended where the bound was reached.

## Rendering

Message content is untrusted. It is stripped of terminal control sequences before it is
written, using the same boundary `logs` already applies, so a message can never emit an
escape sequence that the terminal would execute. That holds with colour enabled as well:
the boundary keeps only colour-only SGR sequences and still removes cursor movement, title
changes and hyperlinks, so provider prose can never reposition the cursor or overwrite a
trusted row.

The rendered form reproduces the provider's own human-readable conversation format, so the
same conversation reads the same way here and in the provider CLI. The layout is a copy, not
an interpretation:

| Element | Exact form |
|---|---|
| Separator | 80 `=` characters, one above and one below each header |
| Block prefix | one blank line before each separator |
| Header | `#{n} - Role: {ROLE} - Words: {n} - Tokens: {n} - {timestamp}` |
| Role casing | upper case |
| Timestamp | `YYYY-MM-DD HH:MM:SS.mmm`, milliseconds included |
| Empty body | `  [No content]`, two leading spaces |
| Trailer | one blank line after the last block |

The separator is a fixed 80 characters rather than the terminal width, because the provider
uses a fixed width and a faithful copy must not reflow when the window is resized.

`Words` is the character count of the untruncated body, not a word count. The provider's own
function is named `_count_words` but counts characters, and the cluster reproduces the
observed behaviour rather than the name. Go counts runes, not bytes, because the provider
counts code points.

`Tokens` is the model token count of the untruncated body, measured with the same
`cl100k_base` encoding the provider uses. Both counts describe the whole message, because they
are measured before the display bound is applied, so shortening a body never changes its
header.

The counts are provider-derived facts, so the adapter supplies them through
`protocol.Message.WordCount` and `TokenCount`. The renderer never computes a count itself,
because a second adapter would then be unable to supply its own counting semantics.

The row number and the speaker word are styled as structural labels, and the separator,
timestamp and truncation label are dimmed. The message body is never styled, because it is
provider data rather than application structure. With colour disabled, or when the stream is
redirected, no escape sequence is emitted at all, so the plain form is byte-identical to the
provider's own output.

A record whose body is empty is rendered as `[No content]` rather than as a blank gap, so an
empty message is not mistaken for a rendering failure.

The `--json` form writes the standard document instead, so a script never has to parse the
rendered text.

## Provider step-record unwrapping

The provider stores most message bodies as its own step record rather than as plain prose: one
object or an array of them, each carrying a step name and the text the operator actually wrote.
Printing that record verbatim shows JSON to the operator, which is not a readable conversation.

The adapter unwraps the record before the body is bounded, and the order is load-bearing. Bounding
first would cut the wrapper into invalid JSON, so the unwrapper would give up on exactly the long
messages an operator most wants to read. A regression test pins the order by using a body whose
wrapper alone pushes it past the byte bound.

The unwrapped form is `topsailai.<step>` followed by the text, matching what the provider's own
human-facing surface prints. Any field the cluster does not model is preserved after the text rather
than dropped, because a step record can carry evidence the operator still needs.

The unwrapping is deliberately forgiving, and it is all-or-nothing:

- A body that is not a step record is returned unchanged, because the cluster must not invent
  structure that is absent.
- A body that no longer parses, because the provider truncated it, is returned unchanged. Losing the
  surviving text would be worse than showing it in its raw form, and a truncated body is exactly the
  case where the remaining text still matters.
- A body whose elements are not all step records is returned unchanged. Half-unwrapping it would read
  like a complete conversation while silently dropping entries.

This unwrapping belongs to the adapter, not to the renderer or the protocol. The record format is
provider detail, so it is confined to the adapter and never appears in `internal/protocol`, a Server
route, a stored document or a CLI help body. A second adapter supplies its own unwrapping, and the
cluster contract is unchanged.

## Structured-body rendering

Unwrapping removes the provider's own step record. A body can still be a JSON object or array
afterwards, because the adapter only unwraps a record it recognises, and because a provider may
store a structure the cluster does not model. Forwarding that body verbatim shows braces and
quotes to the operator, which is the same defect unwrapping exists to remove.

The renderer therefore recognises the shape of a body and renders it for a human. The rule is
generic and never names a provider field, because provider vocabulary belongs to the adapter:

| Shape | Rendering |
|---|---|
| object | one `key: value` line per entry, keys sorted |
| object, nested value | the nested block indented under its key |
| object, long or multi-line string | the text on its own indented block under its key |
| array of scalars | one bulleted line per item |
| array containing an object | numbered blocks, each rendered by the object rule |
| empty object or array | `{}` or `[]`, stated rather than left blank |
| not valid JSON | printed verbatim |
| bare JSON scalar | printed verbatim |

Rules that hold in every case:

- A structured body never prints `{`, `}`, `["` or `"]`. The `[n]` markers of a numbered list are
  the intended output, not JSON punctuation.
- Keys are sorted, so the same body renders identically on every read. An operator comparing two
  reads must not see a difference that is not a change in the data.
- Nesting is bounded at six levels. Past the bound a value is printed inline as compact JSON,
  because the alternative is indentation that pushes the text off the terminal edge.
- A body that is not valid JSON is printed verbatim. A truncated body is exactly the case where
  the surviving text still matters, so replacing it with an error would lose the only evidence.
- Every rendered body still passes the control-sequence boundary, because it is provider-derived
  text. The renderer is not a trust boundary.

Rendering happens after unwrapping and before the display bound, so a structured body is bounded
as rendered text rather than as JSON. The counts in the header are measured from the body as the
provider stored it, so they describe the whole message and never change when a body is shortened.

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
