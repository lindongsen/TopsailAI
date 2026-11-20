---
maintainer: AI
author: DawsonLin
---

# Help and command contracts

## HELP-01 Scope overview

In workspace, endpoint and session respectively type `help` then Enter. Expect `Current scope: <scope>`, `Commands:`, descriptions and `Run help all for every command and scope.` No commands executable only in another scope may appear as available.

| Scope | Commands in display order |
| --- | --- |
| workspace | list, endpoints, cd, show, info, start, resume, stop, clean, drive, logs, status, refresh, watch, project, history, messages, model, help, quit, exit |
| endpoint | list, cd, show, info, start, resume, stop, clean, drive, logs, status, refresh, watch, project, history, messages, model, help, quit, exit |
| session | list, cd, show, info, stop, btw, interrupt, ctl, drive, logs, send, status, refresh, messages, model, help, quit, exit |

Workspace/endpoint help must explain starting a project and navigation; session help must explain bare cd/root, parent endpoint, internal selectors, adapter capability and freshness. A legacy start form may be documented but must not obscure supported wizard behavior.

## HELP-02 Detailed help

For **each** of list, endpoints, project, cd, show, info, start, resume, stop, clean, btw, interrupt, ctl, drive, logs, send, status, refresh, watch, project, history, messages, model, help, quit, exit, enter `help <command>` in all three scopes. Capture complete output, not only its first line. Expect command name, Syntax, Available in and Description; Parameters and Examples appear where applicable. An unavailable command may have detailed help but Available in must not authorize that scope. Verify every displayed example against actual parsing and provider contract; do not approve merely because help renders.

| Command | Required syntax/semantics |
| --- | --- |
| list | `list [endpoint] [--clean] [--full]`; scoped filter must match current endpoint; --clean omits failed endpoints, diagnostics remain; --full disables truncation so a long PROJECT_WORKSPACE wraps instead of clipping; `lf` is the shorthand and implies --full, so `lf --clean` renders the same table as `list --clean --full`; a repeated --full is a usage error |
| endpoints | `endpoints [endpoint-id]`; workspace scope only; lists every registered endpoint with connection state, observation time and capability revision; an unknown filter renders an empty table, not an error; it never changes the `list` row numbers used by `cd <number>` |
| cd | `cd [target]`; empty and / return workspace, .. moves parent, latest row number/hostname/endpoint/internal session/provider session selectors supported |
| show | `show [endpoint-or-session]`; omitted target uses selected scope target; a bare row number or the displayed provider session ID is accepted; workspace without target must report required selection and name `show <number>` |
| info | `info [session]`; read-only session detail; a bare row number or the displayed provider session ID is accepted; omitted target uses the current session in session scope and must report required selection in workspace and endpoint scope; endpoint scope must reject a row belonging to another endpoint; it never changes the selected session or the `list` row numbers |
| start | wizard `start [endpoint]`; without an endpoint argument it prints a numbered endpoint list and accepts a bare number, so no endpoint identifier has to be typed; folder/project and task prompts; legacy explicit endpoint/resource/profile/revision syntax documented separately |
| resume | `resume`; selected stopped historical session, confirmation; complete fresh inventory must prove no live generation before and after confirmation |
| stop | `stop`; confirmation, pinned resource and generation |
| clean | `clean <row|session>`; delete provider-owned expired artifacts for one exact session after confirmation; a bare row number selects the session shown at that row of the most recently rendered list, and a numeric token that is not a row number is retried as a provider session ID; workspace scope resolves the row's own endpoint and rejects a token matching sessions on several endpoints; the adapter requires the provider's exact session ID and PID and never retries with a weaker selector; available only in workspace and endpoint scope |
| btw | `btw [text]`; literal context text, submitted directly without a confirmation question because the command word and the text are already stated; a bare `btw` reads a multi-line context block finished with a standalone EOF line or Ctrl+D, and an empty block is rejected instead of submitting nothing; no JSON is required |
| interrupt | `interrupt [soft\|hard] [message]`; bare `interrupt` prompts for the action then an optional soft message; verify real effect, not just admission |
| ctl | `ctl [action] [key=value ...]` or `ctl.<action> [key=value ...]`; bare `ctl` renders the action list from the capabilities the endpoint advertises and accepts a number or a name, so no action has to be typed; the dotted spelling names the action in the command word and must skip the action prompt while keeping the confirmation gate; an unadvertised action must be refused before admission in both spellings; parameters are guided as `key=value` pairs and an empty answer sends `{}`, so no JSON document is ever typed; a bare word without `=` must be rejected as a parameter error; confirmation is required; verify the durable receipt, not just admission |
| drive | `drive [start\|stop\|status] [session]`; omitted action reports status; the first token is an action only when it names one, so `drive <row>` and `drive <session-id>` report status; a target is required in workspace and endpoint scope and rejected in session scope; workspace scope resolves the row's own endpoint and rejects a token matching several endpoints; `drive stop` stops only the driver controller and must leave the agent running |
| logs | `logs [session]`; selected session by default; a bare row number or the displayed provider session ID is accepted; bounded stdout body, not just metadata |
| send | `send <text>`; literal message text, no confirmation because the text is on screen; a bare `send` reads a multi-line block and asks once; no JSON is required |
| status | `status [command-id]`; explicit result, otherwise the last command submitted in this CLI, otherwise selected session state; with no retained command it explains the short form instead of demanding an identifier |
| refresh | `refresh`; reload server inventory, not a promise of synchronous provider discovery |
| watch | `watch [interval] [--force] [-a|--all] [-t|--trigger[=<path>]] [-b|--bell]`; re-renders on a timer until any key is pressed; `--force` needs at least 10s because each tick launches one provider discovery per endpoint; `-t` is the short spelling of `--trigger`; `-b` is the short spelling of `--bell`, which rings the terminal bell on any observed state change and is silent on the first collection; unavailable in session scope |
| project | `project [endpoint]`; list the managed projects of one endpoint as standard Project resources; the result is a live provider read; PROJECT_ID is the opaque Cluster identity and provider row numbers are never identities; read-only, so registration and removal remain local administrative actions |
| history | `history [endpoint]`; read bounded provider session history for one endpoint and render it as a numbered table; the result is a live provider read, never a persisted projection; a hostname shared by several endpoints is rejected with the candidate list; history row numbers are a separate namespace from list row numbers, and a history render replaces the list row numbers; a row the inventory join could not resolve to a live resource and generation cannot be entered with `cd` |
| messages | `messages [-c N] [-t N] [session]`; read one session's conversation, which is persisted provider data, so a stopped session can still be read; a bare row number selects the row shown at that row of the most recently rendered table, either the list or the history table; `-c`/`--max-chars` and `-t`/`--max-tokens` shorten each body and mark it with an ellipsis, both bounds apply together and the tighter one wins; a bounded window is always labelled, so a shortened conversation is never presented as complete; read-only, so it never changes the selected session or the row numbers |
| model | `model [session] [profile] \| model set [<row\|model-profile-id>]`; outside session scope a bare `model` reads the endpoint model registry, which lists the models a launch from that endpoint can use and marks the one in use, and workspace scope asks which endpoint to read; in session scope a bare `model` lists the profiles of the current session; `model set` declares which model a launch from this endpoint should use, and with no selector it renders the registry and asks which row to declare, where an empty answer keeps the current default; `model set` is refused in session scope, where `model <profile>` already applies a profile to the session; a row number resolves against the table the operator last saw and is never retried as an identifier, while a `model_profile_id` or display name resolves against a fresh registry read; every read is a live provider query, never a persisted projection; both mutations ask for confirmation, and `model set` refuses an unavailable model before asking so a refusal proves nothing was written; an empty catalog or registry is a real answer, while an endpoint with no capable adapter is reported as an integration gap |
| help | `help [command]`, all, scope/scopes and aliases |
| quit | `quit`; restores terminal and exits without stopping agent; outside workspace scope `quit` and its `q` alias return to workspace scope instead, and only in workspace scope do they exit |
| exit | `exit`; always restores terminal and exits without stopping agent, from every scope; it is a separate command rather than an alias of `quit`, so it never navigates |

## HELP-03 Global help and aliases

Enter `help all`, `help scope`, `help scopes`, `?`, `help btw`, `help control`, `help q`, `help unknown-command`. Expect all 25 canonical commands with scope lists, eight aliases (`?=help`, `q=quit`, `r=refresh`, `l=list`, `w=watch`, `control=ctl`, `>=send`, `m=model`), workspace/endpoint/session model and every cd form; aliases resolve to canonical detailed help. `exit` is canonical, not an alias, so `help exit` must describe it directly. Unknown help reports error and leaves scope unchanged. Run `logs --help` and `start --help`: if REPL rejects option-style help, error must explicitly direct to `help logs`/`help start`; standalone --help support does not prove REPL support.

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
| `drive` | `drive <row>` | `drive <resource-id>`, `drive <provider-session-id>`, `drive status <row>` |
| `ctl` | `ctl` then a bare action number or name | `ctl <action> <key=value ...>`, `ctl.<action> <key=value ...>` |

The interactive `!` prefix is a short form of its own: `!<argv>` runs one allowlisted command without any endpoint, resource or generation argument. In session scope the selected session supplies the working directory; in endpoint scope the command runs in the Endpoint-local `AGENT_CLUSTER_ENDPOINT_COMMAND_DIR`, and an Endpoint that has not configured it refuses the form and names the setting. It has no `help <command>` entry; see `control-and-exec.md`.

Actionable errors must name the short form: a missing session reports `use cd <number> to select a session row`, and a workspace-scope `show` reports `use show <number> for a session row or show <endpoint-id>`.
