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
unrestricted shell, and the deployment scripts install a read-only default policy so
a fresh node starts with the feature available.

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
