---
maintainer: AI
author: DawsonLin
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: AGENT_CLUSTER
programming_language: go
---

# AI-added capabilities

Capabilities added autonomously during implementation, recorded so the feature
inventory stays complete. Each entry names the capability, why it exists, the key
logic, and its effect on the system.

## Operator permission scopes

`internal/security/scopes.go` adds the five operator scopes `view`, `read_output`,
`send_message`, `control` and `endpoint_admin`, and `AuthorizeOperation` decides
whether a scope set may perform an operation. Command admission in
`internal/server/commands.go` now reads the permission each capability declares and
returns 403 `permission_denied` when the caller does not hold it. An empty scope set
means unrestricted, preserving the single-administrator deployment, and any `ctl.*`
operation that declares no permission is rejected so a sensitive action cannot
become reachable because an Endpoint omitted the declaration.

## Endpoint command allowlist

`internal/endpoint/allowlist.go` gates the `command.exec` operation behind a
line-based policy file, matched as a prefix of the argv array, with the 16 programs
that can execute other programs requiring at least two tokens. `allowlist_file.go`
loads the file at startup and reloads it on `SIGHUP`, parsing the whole document
before swapping so a malformed edit keeps the previous policy in force. A missing
file disables the operation with an explicit error rather than falling back to an
unrestricted shell, and the deployment scripts install a default policy so a fresh
node starts with the feature available. That default is the common operational set
an operator needs to inspect a node and prepare a workspace: read-only inspection
(`ls`, `cat`, `grep`, `du`, `df`, `free`, `ps`, `uname`, `id`, `date`, `lscpu`,
`lsblk`, `hostname` and similar), network diagnostics (`ping`, `nc`, `ss`,
`netstat`), filesystem mutation confined to the session directory (`mkdir`,
`touch`), and the git entries needed to publish work. Destructive programs (`rm`,
`mv`, `cp`, `dd`, `kill`, `truncate`, package managers) are deliberately absent.
That default is not a sandbox: it includes `git push`, `git pull`, `git fetch`,
`hostname`, `nc` and `ping`, whose permissive forms are recorded in
`conf/command-allowlist.conf.example`.

## Allowlisted command execution

`internal/adapter/topsailai/exec_*.go` implements `command.exec`: it confines the
argv array, resolves the session directory from `project_workspace` then `pwd`,
runs the program without a shell in its own process group with a minimal
environment, and bounds both output and lifetime. A non-zero exit is reported as a
legitimate result, while a timeout reports unknown effects because the program may
have acted. The receipt distinguishes `not_started`, `submitted` and `acknowledged`
so a transport acknowledgement is never presented as task completion.

## Provider control channel

`internal/adapter/topsailai/ctl_actions.go` advertises the ten reviewed provider
control actions as `ctl.<action>` operations, each with its own required
permission, so the operator reaches the provider's control surface through the
standard API instead of a provider-specific passthrough. The reviewed list is
static because `Describe` is called per command and a live registry query would
spawn a provider subprocess each time; a test parses the provider's own fallback
registry so drift is caught rather than silently ignored.

## Dotted control spelling in session scope

`internal/tui/interactive_ctl.go` accepts `ctl.<action>` as a form of the `ctl`
command, so the operator names the action in the command word and skips the action
prompt. The dotted word is resolved before alias and scope resolution and rewritten
to `ctl`, so it inherits the session-only scope rule, the confirmation gate and the
capability preflight instead of becoming a second command. The spaced `ctl <action>`
and bare prompting forms are unchanged, and `help ctl.<action>` resolves to the `ctl`
entry.

## Guided control parameters instead of interactive JSON

The interactive `ctl` surface never asks for a JSON document. After the action is
resolved, `promptCtlParameters` asks for `key=value` pairs separated by spaces, and an
empty answer sends the empty object, which is what an action without arguments
expects. `ctlParameterValue` keeps a JSON scalar type when the value parses as one, so
`timeout_seconds=300` reaches the provider as a number, while a double-quoted value is
sent as literal text. `ctlParameterSummary` echoes the parameters in the same guided
form at the confirmation gate, so the operator verifies what will be sent without
reading JSON.

The prompt is offered only when no parameter was supplied on the command line, and it
runs after the capability preflight, so an action the Endpoint never advertised is
refused before the operator is asked to fill anything. The prompt is always offered
when parameters are missing because the Endpoint advertises no per-action field
schema, so the client cannot know which actions take arguments and must not guess. The
standalone `agent-cluster-cli ctl` surface keeps its explicit `[json]` argument, which
is the non-interactive-first contract; only the interactive convenience layer changed.

## Drive command in workspace and endpoint scope

`internal/tui/interactive_drive.go` accepts `drive [start|stop|status] [session]` in
workspace, endpoint and session scope, so an operator can manage a session driver
from a fleet or endpoint listing instead of first entering the session. The first
token is read as an action only when it names one, so `drive <row>` and
`drive <session-id>` are the literal target form and report controller state. A
target is required outside session scope and rejected inside it, matching `stop`.
The exact-target resolver moved into `internal/tui/session_target.go` so `stop` and
`drive` share one authority check; workspace scope resolves the row's own endpoint
and rejects a token matching several endpoints rather than guessing. `status`
remains a read of the persisted projection and never admits a command, while
`start` and `stop` keep the confirmation gate and revalidate the exact generation.

## Multi-row interactive input block

`internal/tui/terminal_editor.go` renders the current edit as a soft-wrapped block
instead of one horizontally scrolled row, so a long message keeps its head visible
and the operator can review the whole input. `internal/tui/line_edit_view.go`
replaced `viewport` with `wrapViewport`, which returns every wrapped row plus the
cursor row and column; the first row shares its width with the prompt and
continuation rows use the full width with one reserved column. The block is bounded
by the terminal height reported through the output boundary, so a block taller than
the screen scrolls by whole rows and the cursor row stays visible. Each redraw
erases the previously rendered block first, so a shrinking block leaves no stale
row, and submit/interrupt/EOF move the cursor to the block end before writing the
newline. A Tab completion candidate list is printed below the erased block so the
next redraw cannot erase it. Unsafe runes are dropped, matching `sanitizeTerminal`.

## Session list driver column

`internal/tui/table.go` adds a `DRIVER` column to the session list so the
controller state is visible without running a separate `drive` command. The
column is a read projection of the persisted inventory: `driveCell` renders `-`
when the provider reported no driver observation, `unverified` when a running
state was not verified alive, `unknown` for an empty state, and otherwise the
reported standard state. `SessionRow.Drive` carries the summary from
`protocol.Session.Drive`, which the adapter already populated, so no protocol,
Server, storage or adapter change was needed. The column sits directly after
`SESSION_ID`, so the controller state is read next to the session identity it
belongs to. A dash is deliberately distinct from `none`: `none`
is a confirmed absence of a controller, while a dash only means the provider said
nothing.

## Config-file-driven ctl catalog

`internal/adapter/topsailai/ctl_config.go` makes the `ctl.<action>` surface entirely
configuration-driven. The catalog file named by `AGENT_CLUSTER_CONTROL_ACTION_FILE`
is the only source of control actions: each entry defines the action name, the
permission scope, the payload schema and the provider argv template, so adding,
changing or removing an action requires no adapter rebuild and no Server change.
`ctl_actions.go` no longer carries a compiled-in action list, permission map or
schema map; `controlActionCapabilities` iterates the catalog and
`controlActionArgs` builds argv from the configured template.

The template is an argv array executed directly, never a shell string. Two
placeholders are substituted per token so a placeholder never splits into several
arguments: `{session}` becomes the provider session key and `{payload}` becomes the
JSON payload. Each may appear at most once, and an unknown or unterminated
placeholder is rejected at load time. `payload_session_field` replaces the previous
hardcoded `get_session_messages` special case, so the Endpoint fills the provider
session key from the revalidated target instead of asking the operator for a
selector it already holds.

A nil or empty catalog advertises no action and refuses every `ctl.` operation,
which reverses the earlier "nil means reviewed default set" behaviour: an Endpoint
cannot be talked into running an action nobody configured. The catalog is reloaded
on `SIGHUP`; a malformed document keeps the previous actions in force and is logged.
Whole-line `#` comments are accepted so the shipped example can explain itself.

Because the catalog decides which provider command runs, it is an authorization
surface. The Endpoint validates the configured capability list before its policy
hook runs, so an action absent from the catalog is rejected before any allowlist or
policy check. Both deployment paths install `conf/control-actions.conf.example` as
`control-actions.conf` and register it as a conffile, and
`conf/node.endpoint.conf.example` names it, so a fresh node keeps the feature.

The interactive surface renders guided prompts from the advertised
`payload_schema` (`internal/tui/interactive_ctl_schema.go`): fields are asked one at
a time in name order, optional fields accept an empty answer, required fields reject
one, enum values are offered as choices, and an action without a schema falls back
to the generic `key=value` prompt so an older Endpoint still works. No interactive
path requires hand-written JSON.

A structured field is encoded as its real JSON type rather than as a string that
merely looks like one. `args` is written as space-separated words and becomes a JSON
array, with a double-quoted word keeping its inner spaces and an unterminated quote
refused; `kwargs` is written as space-separated `key=value` pairs and becomes a JSON
object, with a pair lacking `=` and a repeated key both refused. The prompt states
the shape for a structured field, because an operator cannot guess that a list is
written on one line. This matters for `call_instruction`, whose provider payload
carries `instruction`, `args` and `kwargs`: sending `args` as a string would be
rejected by the provider even though it reads like a list to a human.

The interactive REPL renders one bounded output snapshot when the operator enters
session scope, and that snapshot now uses a 300-line budget instead of 100. The
budget is one quantity with one meaning, so the automatic entry snapshot, a bare
`logs` command and the degraded post-`send` snapshot all read the same resolved
value (`internal/tui/interactive.go`, `internal/tui/navigation.go`). Two
independent literals previously decided the same number, which let the surfaces
disagree.

The interactive REPL now starts a live tail after a completed `send` in session
scope, instead of rendering one bounded snapshot. It arms the same follow intent
that `logs -f` arms, through one shared helper, so the automatic step and the
explicit command cannot drift into two grammars, two announcements or two
capability checks (`internal/tui/interactive_ops.go`). The stream opens on the
next prompt and any key stops it, exactly like an explicit follow. A client that
cannot stream, or an input mode that cannot observe a keypress, degrades to the
previous bounded snapshot with a diagnostic that says so, because a live tail that
cannot be stopped is worse than a snapshot and a snapshot presented as a stream
would look complete while silently missing later output.

The startup `--lines` option sets the budget when entering interactive mode and is
bounded to 100-1000. An explicit value outside that window is rejected with an error
naming the range rather than silently clamped, because an operator who asked for
5000 lines and received 1000 would believe the terminal showed everything
(`resolveInteractiveLines` in `src/main/agent-cluster-cli/main.go`). The value is
validated before the editor takes the terminal, so a rejected value never leaves the
screen in raw mode. The standalone `logs` command keeps its own 100-line default and
still accepts any positive count, and a per-command `logs -n 7` inside the REPL
still wins over the startup budget.
