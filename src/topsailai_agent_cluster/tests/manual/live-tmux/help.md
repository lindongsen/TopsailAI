---
maintainer: AI
author: DawsonLin
---

# Help and command contracts

## HELP-01 Scope overview

In workspace, endpoint and session respectively type `help` then Enter. Expect `Current scope: <scope>`, `Commands:`, descriptions and `Run help all for every command and scope.` No commands executable only in another scope may appear as available.

| Scope | Commands in display order |
| --- | --- |
| workspace | list, endpoints, cd, show, start, stop, status, refresh, watch, help, quit |
| endpoint | list, cd, show, start, stop, logs, status, refresh, watch, help, quit |
| session | list, cd, show, resume, stop, inject, interrupt, ctl, drive, logs, send, status, refresh, help, quit |

Workspace/endpoint help must explain starting a project and navigation; session help must explain bare cd/root, parent endpoint, internal selectors, adapter capability and freshness. A legacy start form may be documented but must not obscure supported wizard behavior.

## HELP-02 Detailed help

For **each** of list, endpoints, cd, show, start, resume, stop, inject, interrupt, ctl, drive, logs, send, status, refresh, watch, help, quit, enter `help <command>` in all three scopes. Capture complete output, not only its first line. Expect command name, Syntax, Available in and Description; Parameters and Examples appear where applicable. An unavailable command may have detailed help but Available in must not authorize that scope. Verify every displayed example against actual parsing and provider contract; do not approve merely because help renders.

| Command | Required syntax/semantics |
| --- | --- |
| list | `list [endpoint] [--clean]`; scoped filter must match current endpoint; --clean omits failed endpoints, diagnostics remain |
| endpoints | `endpoints [endpoint-id]`; workspace scope only; lists every registered endpoint with connection state, observation time and capability revision; an unknown filter renders an empty table, not an error; it never changes the `list` row numbers used by `cd <number>` |
| cd | `cd [target]`; empty and / return workspace, .. moves parent, latest row number/hostname/endpoint/internal session/provider session selectors supported |
| show | `show [endpoint-or-session]`; omitted target uses selected scope target; a bare row number or the displayed provider session ID is accepted; workspace without target must report required selection and name `show <number>` |
| start | wizard `start [endpoint]`; without an endpoint argument it prints a numbered endpoint list and accepts a bare number, so no endpoint identifier has to be typed; folder/project and task prompts; legacy explicit endpoint/resource/profile/revision syntax documented separately |
| resume | `resume`; selected stopped historical session, confirmation; complete fresh inventory must prove no live generation before and after confirmation |
| stop | `stop`; confirmation, pinned resource and generation |
| inject | `inject <text>`; literal context text, confirmation; no JSON is required |
| interrupt | `interrupt [soft\|hard] [message]`; bare `interrupt` prompts for the action then an optional soft message; verify real effect, not just admission |
| ctl | `ctl [action] [json]`; bare `ctl` renders the action list from the capabilities the endpoint advertises and accepts a number or a name, so no action has to be typed; an unadvertised action must be refused before admission; the payload is an optional JSON object and an empty payload sends `{}`; confirmation is required; verify the durable receipt, not just admission |
| drive | `drive [start\|stop\|status]`; omitted action reports status; `drive stop` stops only the driver controller and must leave the agent running |
| logs | `logs [session]`; selected session by default; a bare row number or the displayed provider session ID is accepted; bounded stdout body, not just metadata |
| send | `send <text>`; literal message text, confirmation; no JSON is required |
| status | `status [command-id]`; explicit result, otherwise the last command submitted in this CLI, otherwise selected session state; with no retained command it explains the short form instead of demanding an identifier |
| refresh | `refresh`; reload server inventory, not a promise of synchronous provider discovery |
| watch | `watch [interval] [--force]`; re-renders on a timer until any key is pressed; `--force` needs at least 10s because each tick launches one provider discovery per endpoint; unavailable in session scope |
| help | `help [command]`, all, scope/scopes and aliases |
| quit | `quit`; restores terminal and exits without stopping agent |

## HELP-03 Global help and aliases

Enter `help all`, `help scope`, `help scopes`, `?`, `help btw`, `help control`, `help q`, `help unknown-command`. Expect all 18 canonical commands with scope lists, seven aliases (`?=help`, `btw=inject`, `control=interrupt`, `exit=quit`, `q=quit`, `r=refresh`, `w=watch`), workspace/endpoint/session model and every cd form; aliases resolve to canonical detailed help. Unknown help reports error and leaves scope unchanged. Run `logs --help` and `start --help`: if REPL rejects option-style help, error must explicitly direct to `help logs`/`help start`; standalone --help support does not prove REPL support.

Capture full actual help output as the run-specific reference. A discrepancy between prose, syntax, example and actual action is a defect even when all are separately printable.

## HELP-04 Short input forms

Every command that takes a session or endpoint target accepts a short form, so an operator never has to type a long identifier.

| Command | Short form | Long form still accepted |
| --- | --- | --- |
| `cd` | `cd <row>` | `cd <hostname>/<endpoint>`, `cd <hostname>/<endpoint>/<session>` |
| `show` | `show <row>` | `show <endpoint-id>`, `show <resource-id>`, `show <provider-session-id>` |
| `logs` | `logs <row>` | `logs <resource-id>`, `logs <provider-session-id>` |
| `status` | `status` (no argument) | `status <command-id>` |
| `start` | `start` then a bare endpoint number | `start <endpoint-id>` |
| `ctl` | `ctl` then a bare action number or name | `ctl <action> <json>` |

The interactive `!` prefix is a short form of its own: `!<argv>` runs one allowlisted command in the selected session without any endpoint, resource or generation argument, because the current session supplies them. It has no `help <command>` entry; see `control-and-exec.md`.

Actionable errors must name the short form: a missing session reports `use cd <number> to select a session row`, and a workspace-scope `show` reports `use show <number> for a session row or show <endpoint-id>`.
