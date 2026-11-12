---
maintainer: AI
author: DawsonLin
---

# Provider control and allowlisted command execution

This module verifies the two session-scope surfaces that reach the provider beyond
`send` and `interrupt`: the `ctl` control channel and the `!` allowlisted command
prefix. It is an operator acceptance procedure driven through the real
`agent-cluster-cli` binary in tmux, not a unit-test claim.

Both surfaces are one-shot. Neither starts a periodic refresh, so a case that sees
output change without a new command is a FAIL, not a bonus.

## Preconditions

- The Endpoint under test advertises at least one `ctl.<action>` capability. Confirm
  with `endpoints` and record the capability revision; a case run against an Endpoint
  that advertises none is BLOCKED, not PASS.
- The Endpoint was started with a command allowlist file. Confirm the resolved path
  from the Endpoint log line `loaded command allowlist` and record the entry count.
  An Endpoint started without one is expected to deny every `!` command, which is
  CTLEXEC-06 rather than a precondition failure.
- The selected session has a resolvable working directory. Record the expected
  directory from the provider's own session information, not from the CLI process
  working directory.
- Use only the owned disposable test agent. Keep one unrelated session running and
  verify it stays unchanged.

## CTLEXEC-01 Bare `ctl` renders the advertised actions

Precondition: session scope with a selected session.

Type `ctl` then Enter. Expect `Control actions:` followed by a numbered list, then
`Enter a number or an action name; empty cancels.` and the `ctl.action>` prompt.
Expect no command admission yet.

Compare the rendered list against the Endpoint's advertised `ctl.` capabilities. The
two sets must be identical: an action offered but not advertised is a FAIL, because
the prompt must never offer an action the Endpoint does not support.

## CTLEXEC-02 Empty answer cancels

Precondition: same as CTLEXEC-01.

Type `ctl` then Enter, then Enter again with no text. Expect `ctl cancelled` and no
command admission. A control action is a mutating request, so an empty answer must
never select the first action.

## CTLEXEC-03 Selecting by number and by name

Precondition: same as CTLEXEC-01.

Type `ctl` then Enter, then the number of a harmless advertised action such as
`heartbeat`, then Enter. Expect `Parameters for heartbeat:` and the `ctl.param>`
prompt, because the Endpoint advertises no per-action field schema so the client
cannot know which actions take arguments. Answer with no text, expect
`Parameters: none`, then expect the action name echoed in the confirmation question.
Answer `n` and expect `ctl cancelled` with no admission.

Repeat, answering `y` at the confirmation. Expect one `command submitted: <id>; use
status <id> to query` line, then the receipt fields CommandID, Status,
DeliveryBoundary, EffectCertainty and ErrorCode. Query `status <id>` and confirm the
durable result matches the rendered one.

Repeat once more, typing the action name instead of its number, and confirm the same
behaviour. Record the exact provider result; an admitted command that the provider
rejects is a FAIL, not a PASS.

## CTLEXEC-04 Supplied action and guided parameters

Precondition: same as CTLEXEC-01.

Type `ctl heartbeat` then Enter. Expect the confirmation question without the action
list, because the operator already named the action, and expect the parameter prompt
first because no parameter was supplied.

Repeat with explicit parameters, for example `ctl pause reason=live-tmux`. Expect no
parameter prompt, because the parameters were supplied on the command line, and expect
`Parameters: reason=live-tmux` echoed in the confirmation preview. Answer `n` first and
confirm no admission, then `y` and confirm the receipt.

Type `ctl pause timeout_seconds=300` then Enter and confirm. Expect the value to reach
the provider as a JSON number rather than a string, because an unquoted value that
parses as a JSON scalar keeps its type. Repeat with `timeout_seconds="300"` and expect
a JSON string instead.

Type `ctl heartbeat not-json` then Enter. Expect a parameter rejection naming the
`key=value` form and no admission. Repeat with `ctl heartbeat []` and `ctl heartbeat 5`;
both must be rejected rather than wrapped into an object. No interactive form may
accept a JSON document.

## CTLEXEC-05 Unadvertised action is refused

Precondition: session scope, with an action name that the Endpoint does not advertise.

Type `ctl <unadvertised-action>` then Enter. Expect an explicit refusal naming the
action, and expect no command admission and no parameter prompt, because the action is
rejected before the operator is asked to fill anything. A silently admitted command
that later fails is a FAIL, because the client must not send an operation the Endpoint
never advertised.

## CTLEXEC-06 `!` runs an allowlisted command

Precondition: session scope, allowlist containing the program under test.

Type `!pwd` then Enter. Expect one receipt with CommandID, Status, DeliveryBoundary,
EffectCertainty, ErrorCode, then `exit_code: 0`, `truncated: false` and a `stdout:`
section. Expect the printed directory to equal the session working directory recorded
in the preconditions, not the CLI process working directory.

Confirm no confirmation question appeared: `!` is a one-shot execution form, so it
submits directly. Confirm the receipt shows delivery evidence rather than task
completion.

## CTLEXEC-07 `!` refuses a command outside the allowlist

Precondition: session scope, with a program that the allowlist does not contain.

Type `!<unlisted-program>` then Enter. Expect Status `rejected`, EffectCertainty
`not_applied` and ErrorCode `policy_denied`, and expect no `stdout:` section. A refusal
must never be rendered as an empty successful result.

## CTLEXEC-08 `!` keeps arguments literal

Precondition: session scope, allowlist containing the program under test.

Type `!echo "two words"` then Enter. Expect `stdout:` to contain `two words` as one
line, proving the quoted argument stayed one argument.

Type `!echo -n hi` then Enter. Expect the flag to reach the program as an argument
rather than being consumed by the CLI, and expect no trailing newline in `stdout:`.

Type `!echo $HOME` then Enter. Expect the literal text `$HOME`, not an expanded path,
because no shell expansion is performed. Type `!echo a | b` and expect the literal
`a | b`, because no pipeline is interpreted.

## CTLEXEC-09 `!` rejects malformed input

Precondition: session scope.

Type `!` then Enter. Expect `usage: !<program> [arguments...]` and no admission.

Type `!echo "unterminated` then Enter. Expect `unterminated quote in command line` and
no admission.

## CTLEXEC-10 Standalone surfaces match the interactive ones

Precondition: a terminal outside the REPL, with the same Endpoint and session.

Run `agent-cluster-cli ctl <endpoint> <resource> <action>` and expect
`confirmation required for ctl <action> target=<resource> parameters={}; rerun with
--yes`. Repeat with `--yes` and confirm the receipt matches CTLEXEC-03.

Run `agent-cluster-cli exec <endpoint> <resource> <generation> -- <argv...>` and expect
the same confirmation gate, then the same receipt shape as CTLEXEC-06. Confirm that
`exec <endpoint> <resource> <generation> -- ls -la` passes `-la` as an argument.

Run `agent-cluster-cli ctl <endpoint> <resource>` and expect
`usage: ctl <endpoint-id> <resource-id> <action> [json] [generation]`. Run
`agent-cluster-cli exec <endpoint> <resource> <generation>` and expect
`usage: exec <endpoint-id> <resource-id> <generation> -- <argv...>`.

## CTLEXEC-11 Allowlist hot reload

Precondition: session scope, allowlist file path recorded from the Endpoint log.

Add a new program to the allowlist file and send SIGHUP to the exact Endpoint process
ID. Expect a `reloaded command allowlist` log line with the new entry count. Type
`!<newly-listed-program>` and expect it to run.

Then remove a previously listed program, send SIGHUP again, and expect that program to
be refused with `policy_denied`. Asserting only the addition would pass a reload that
appends instead of replacing, so both directions are required.

Stop only the exact process ID recorded for this run. Never signal by name.

## CTLEXEC-12 Help documents both surfaces

Precondition: session scope.

Type `help` then Enter. Expect `ctl` in the session-scope command list. Type
`help ctl` and expect Syntax, Available in and Description, and expect the description
to state that the action list comes from the advertised capabilities.

Confirm the `!` prefix is documented in the session workflow block, because it is an
input-prefix form rather than a command word and therefore has no `help <command>`
entry of its own.

Type `help exec` in the REPL and expect `unknown help command "exec"; next: run help all`.
That rejection is correct, not a defect: `exec` is a standalone-only spelling with no
scope-matrix entry, so the REPL must not advertise it. Then run
`agent-cluster-cli help exec` outside the REPL and expect the standalone syntax with the
`--` separator and the argv description. A REPL that renders `exec` help, or a standalone
`help exec` that fails, is a FAIL.

## Evidence

Record case ID, exact keystrokes, captured output, admitted command ID, payload, the
resolved session directory, the allowlist path and entry count, the Endpoint process ID
and the tmux target under workspace `.tmp/live-tmux-audit/`. Stop only the tmux session
and service processes created by this run.

## Execution log

Note: the table below records the first run, which predates the guided-parameter change.
CTLEXEC-03 and CTLEXEC-04 were executed while the interactive surface still accepted a
JSON payload, so their recorded evidence describes superseded behaviour. Both cases were
re-run against the current build; see "Run 2" below, which supersedes those two rows. The
other cases are unaffected, because they do not exercise the payload form.

Executed on 2026-11-07 against a real `topsailai` provider, using binaries built from
HEAD into `.tmp/live-tmux-audit/bin/` and the isolated cluster started by
`start_services.py`. The live deployment (`/usr/local/sbin/agent-cluster-endpoint`,
PID 100053) was never restarted: its uptime advanced from 6h04m to 6h30m across the run,
which is the isolation proof.

Note: the deployment path above reflects the layout in use when the run was recorded. The
payload now lives under `/opt/agent-cluster`, so the same endpoint is reached through the
entry-point symlink `/usr/local/sbin/agent-cluster-endpoint` ->
`/opt/agent-cluster/bin/agent-cluster-endpoint`. The recorded observation is unchanged.

Preconditions observed before any case: Endpoint log line
`loaded command allowlist ... entries=3`, all ten `ctl.*` actions plus `command.exec`
advertised, and one live session in the persisted inventory.

| Case | Result | Evidence |
|---|---|---|
| CTLEXEC-01 | PASS | Bare `ctl` rendered all ten actions as a numbered list with the `ctl.action>` prompt; no command admitted |
| CTLEXEC-02 | PASS | Empty answer produced `error: ctl cancelled` plus usage; no command admitted |
| CTLEXEC-03 | PASS (run 2) | `7` resolved to `ctl heartbeat`; guided prompt `ctl.param>` accepted an empty answer as `Parameters: none`; confirmation `y` returned `finished`/`acknowledged` with `delivery_state: control_acknowledged` and `result: {"alive": true, "pid": 1347750, "hostname": "ai-dev", "session_id": "wa-d9ef07069d5b"}`. Supersedes the run-1 row |
| CTLEXEC-04 | PASS (run 2) | `9` resolved to `ctl pause`; the guided prompt walked `default` (enum `continue`/`interrupt`), `prompt`, `reason` and `timeout_seconds` (number) one field at a time; `timeout_seconds=300` was sent as a JSON number and the provider returned `state: pause_requested` with the pause flag path. No JSON was typed. Supersedes the run-1 row |
| CTLEXEC-05 | PASS | `ctl.not_a_real_action` rejected as `unsupported capability` |
| CTLEXEC-06 | PASS | `!ls internal` listed the real `internal/` tree; `pwd` matched `topsailai_session_info` `project_workspace` |
| CTLEXEC-07 | PASS | Command outside the allowlist returned `rejected`/`not_applied`/`policy_denied` |
| CTLEXEC-08 | PASS | `two words` stayed one argument; `$HOME` stayed literal; `a \| b` stayed literal; `-n` reached `echo` (no trailing newline) |
| CTLEXEC-09 | PASS | Bare `!` produced `invalid arguments` and `usage: !<program> [arguments...]`; an unterminated quote produced `unterminated quote in command line` |
| CTLEXEC-10 | PASS | Both `usage:` forms matched; both confirmation gates fired; `-la` appeared as a discrete argv element; both `--yes` receipts matched the CTLEXEC-03 and CTLEXEC-06 shapes, with real `ls -la` output from the session directory |
| CTLEXEC-11 | PASS | Reload asserted in both directions: a newly listed `ls` was permitted, and the previously listed `echo` was revoked with `policy_denied` |
| CTLEXEC-12 | PASS | REPL returned `unknown help command "exec"`; standalone `help exec` rendered the full syntax |

### Confinement verified separately from the allowlist

With `ls -la` in the allowlist, `ls /etc/passwd` was denied as `policy_denied` because the
prefix did not match, which does not exercise confinement. After reloading to a bare `ls`
entry, the same arguments were denied as `argument_not_confined`, a distinct error code
proving `confineArguments` ran, while `ls internal` still succeeded.

### Corrections made during execution

Two findings were stated and then retracted after verification:

- `ctl.heartbeat` returning `target_generation_mismatch` was an invocation error, not a
  defect: the syntax is `ctl <endpoint> <resource> <action> [json] [generation]`, and the
  generation had been omitted. Re-running with it succeeded.
- The TUI ENDPOINT column showing `ai-dev` is the endpoint hostname field, not a
  cross-cluster leak. `endpoint_id` was `live-tmux-endpoint` and only one Server was
  running, so the run was isolated.

### Harness requirement

`start_services.py` gained an optional `--allowlist` argument, because the harness
previously had no way to configure `AGENT_CLUSTER_ENDPOINT_COMMAND_ALLOWLIST_FILE` and
`command.exec` therefore always failed closed. The option is optional so the same harness
can still prove the fail-closed path.

## Run 2: guided parameters against the current build

Executed on 2026-11-08 against a real `topsailai` provider, using binaries built from HEAD
`63664ebe` into `.tmp/live-tmux-audit/bin/` and the isolated cluster started by
`start_services.py`. The live deployment was never restarted.

Environment:

```text
runtime        .tmp/ctl/r6
provider home  .tmp/ctl/h
project        .tmp/ctl/p/demo
catalog        conf/control-actions.conf.example
allowlist      .tmp/live-tmux-audit/allowlist.conf
tmux session   ctllive   (window 0 = harness, window 1 = cli)
api port       39333
endpoint       live-tmux-endpoint
session        wa-d9ef07069d5b / res_993e48f6b1994d21ac9117af7c8646c5 / pid 1347750
```

Preconditions observed: Endpoint log line `loaded control action file ... actions=10`
listing all ten names, `loaded command allowlist ... entries=2`, and
`GET /api/v1/endpoints/live-tmux-endpoint/capabilities` returning 21 capabilities with all
ten `ctl.*` present.

| Case | Result | Evidence |
|---|---|---|
| CTLEXEC-01 | PASS | Bare `ctl` rendered `Control actions:` with ten numbered entries and the `ctl.action>` prompt; no command admitted |
| CTLEXEC-03 | PASS | `7` → `ctl.param>` → empty → `Parameters: none` → `y` → `finished`/`acknowledged`, `result: {"alive": true, "pid": 1347750, "hostname": "ai-dev"}` |
| CTLEXEC-04 | PASS | `9` → guided fields `default`/`prompt`/`reason`/`timeout_seconds` → `300` → `y` → `state: pause_requested` with the pause flag path |
| CTLEXEC-05 | PASS | `ctl.not_configured` → `error: endpoint "live-tmux-endpoint": unsupported capability "ctl.not_configured"` |
| CTLEXEC-13 | PASS | `ctl.heartbeat` skipped the action menu and went straight to `ctl.param>`, proving dotted spelling |
| CTLEXEC-14 | PASS | `call_instruction` prompted `args` (array), `instruction` (46-value enum) and `kwargs` (object) in alphabetical order; `agent.tokens` returned real token statistics |
| CTLEXEC-15 | PASS | `llm_control` prompted `operation` with the single value `force_retry`; an empty answer produced `error: operation is required for llm_control` |
| CTLEXEC-16 | PASS | `get_session_messages` prompted no user-facing field and returned `count: 3` real messages, proving `session_id` is injected from the target |

### Guided prompt shape observed

`call_instruction` prompts its fields in alphabetical order, not schema order:

```text
args · array · optional · space-separated, quote an item to keep spaces; empty skips
instruction · string · required · one of: help, agent.system_prompt, ... ; empty is rejected
kwargs · object · optional · key=value pairs, space-separated; empty skips
```

`pause` prompts `default`, `prompt`, `reason` and `timeout_seconds` in the same alphabetical
order, and `default` renders as a numbered enum menu.

### AF_UNIX path-length constraint

The provider builds its control socket at
`{TOPSAILAI_HOME}/workspace/task/{session_id}.{pid}.session.sock`. The first attempt used
`.tmp/live-tmux-audit/provider-home`, which produced a 125-character path and exceeded the
108-character AF_UNIX limit, so `get_or_start_control_server` failed with
`AF_UNIX path too long`, the agent never created its socket, and every `ctl.*` returned
`endpoint_missing`. Relocating the provider home to `.tmp/ctl/h` shortened the path to 101
characters and the socket appeared. Any future live run must keep the provider home short.

### Harness requirement for the catalog

`start_services.py` gained an optional `--control-actions` argument mirroring `--allowlist`:
it validates an absolute path and an existing file, then sets
`AGENT_CLUSTER_ENDPOINT_CONTROL_ACTION_FILE`. Without it the Endpoint advertises no `ctl.*` action and
every `ctl.*` fails closed, so the catalog could not be exercised at all. The option stays
optional so the same harness can still prove the fail-closed path.
