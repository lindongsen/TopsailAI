---
maintainer: AI
author: DawsonLin
---

# Help and command contracts

## HELP-01 Scope overview

In workspace, endpoint and session respectively type `help` then Enter. Expect `Current scope: <scope>`, `Commands:`, descriptions and `Run help all for every command and scope.` No commands executable only in another scope may appear as available.

| Scope | Commands in display order |
| --- | --- |
| workspace | list, endpoints, cd, show, start, status, refresh, help, quit |
| endpoint | list, cd, show, start, logs, status, refresh, help, quit |
| session | list, cd, show, resume, stop, inject, interrupt, logs, send, status, refresh, help, quit |

Workspace/endpoint help must explain starting a project and navigation; session help must explain bare cd/root, parent endpoint, internal selectors, adapter capability and freshness. A legacy start form may be documented but must not obscure supported wizard behavior.

## HELP-02 Detailed help

For **each** of list, endpoints, cd, show, info, start, resume, stop, inject, interrupt, logs, send, status, refresh, help, quit, enter `help <command>` in all three scopes. Capture complete output, not only its first line. Expect command name, Syntax, Available in and Description; Parameters and Examples appear where applicable. An unavailable command may have detailed help but Available in must not authorize that scope. Verify every displayed example against actual parsing and provider contract; do not approve merely because help renders.

| Command | Required syntax/semantics |
| --- | --- |
| list | `list [endpoint] [--clean]`; scoped filter must match current endpoint; --clean omits failed endpoints, diagnostics remain |
| endpoints | `endpoints [endpoint-id]`; workspace scope only; lists every registered endpoint with connection state, observation time and capability revision; an unknown filter renders an empty table, not an error; it never changes the `list` row numbers used by `cd <number>` |
| cd | `cd [target]`; empty and / return workspace, .. moves parent, latest row number/hostname/endpoint/internal session/provider session selectors supported |
| show | `show [endpoint-or-session]`; omitted target uses selected scope target; a bare row number or the displayed provider session ID is accepted; workspace without target must report required selection and name `show <number>` |
| info | `info [session]`; read-only session detail; a bare row number or the displayed provider session ID is accepted; omitted target uses the current session in session scope and must report required selection in workspace and endpoint scope; endpoint scope must reject a row belonging to another endpoint; it never changes the selected session or the `list` row numbers |
| start | wizard `start [endpoint]`; without an endpoint argument it prints a numbered endpoint list and accepts a bare number, so no endpoint identifier has to be typed; folder/project and task prompts; legacy explicit endpoint/resource/profile/revision syntax documented separately |
| resume | `resume`; selected stopped historical session, confirmation; complete fresh inventory must prove no live generation before and after confirmation |
| stop | `stop`; confirmation, pinned resource and generation |
| inject | `inject <text>`; literal context text, confirmation; no JSON is required |
| interrupt | `interrupt [soft\|hard] [message]`; bare `interrupt` prompts for the action then an optional soft message; verify real effect, not just admission |
| logs | `logs [session]`; selected session by default; a bare row number or the displayed provider session ID is accepted; bounded stdout body, not just metadata |
| send | `send <text>`; literal message text, confirmation; no JSON is required |
| status | `status [command-id]`; explicit result, otherwise the last command submitted in this CLI, otherwise selected session state; with no retained command it explains the short form instead of demanding an identifier |
| refresh | `refresh`; reload server inventory, not a promise of synchronous provider discovery |
| help | `help [command]`, all, scope/scopes and aliases |
| quit | `quit`; restores terminal and exits without stopping agent |

## HELP-03 Global help and aliases

Enter `help all`, `help scope`, `help scopes`, `?`, `help btw`, `help control`, `help q`, `help unknown-command`. Expect all 15 canonical commands with scope lists, six aliases, workspace/endpoint/session model and every cd form; aliases resolve to canonical detailed help. Unknown help reports error and leaves scope unchanged. Run `logs --help` and `start --help`: if REPL rejects option-style help, error must explicitly direct to `help logs`/`help start`; standalone --help support does not prove REPL support.

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

Actionable errors must name the short form: a missing session reports `use cd <number> to select a session row`, and a workspace-scope `show` reports `use show <number> for a session row or show <endpoint-id>`.
