---
name: agent-cluster-cli-noninteractive
description: Use when a user or agent needs to drive Agent Cluster from a script, CI job or another program through the standalone (non-interactive) `agent-cluster-cli` surface — listing sessions and endpoints, forcing a collection, reading output, history, messages, projects or models, and submitting lifecycle or control actions such as send, btw, interrupt, ctl, exec, start, resume, stop, clean, drive, model set, project add or project remove. Covers the exact command grammar, the global options and their placement, the `--yes` confirmation matrix, the `--json` document shapes, exit codes and the fact that a rejected receipt still exits 0, the credential and configuration precedence, and the argument traps that silently change a command's meaning.
version: 1.0.0
author: DawsonLin
license: Apache-2.0
metadata:
  tags: [agent-cluster, cli, non-interactive, automation, json, scripting]
  related_skills: [agent-cluster-cli-interactive, agent-cluster-watch-trigger]
---

# Agent Cluster CLI Non-Interactive Mode

## Overview

`agent-cluster-cli` has two surfaces over one implementation: an interactive REPL and a
standalone command surface. This skill covers only the standalone surface, because it is the
one a script, a CI job or another agent can drive without a terminal.

The standalone surface is the contract. Every command has an explicit syntax, validates its
own arguments, and offers a machine-readable `--json` mode. The REPL is a convenience layer
over the same behaviour, so anything described here is also what the REPL does — but the
reverse is not true: the REPL accepts row numbers, scope defaults and prompts that the
standalone surface does not.

Two properties decide how you must use this surface:

- **A rejected command still exits `0`, but a missing target exits `2`.** The durable receipt is the
  authority, not the exit status. A command that the Endpoint refused (`target_still_active`,
  `generation_required`, `target_generation_mismatch`, `policy_denied`) prints `failed` and exits
  `0`. A command whose target does not exist never produces a receipt and exits `2`. Always read
  `status` / `error_code` from the receipt or the `--json` document, and read the message before
  treating exit `2` as a syntax error.
- **Diagnostics go to stderr, data goes to stdout.** The resolved Server profile line
  (`using server profile "primary" (http://...)`) is written to stderr, so `--json` output on
  stdout stays parseable.

## When to Use

Use this skill when the task is to:

- read the fleet: sessions, endpoints, one session's detail, output, history, messages,
  projects, model registry;
- force a fresh collection before reading, so the next read is not stale;
- submit an action: `send`, `btw`, `interrupt`, `ctl`, `exec`, `start`, `resume`, `stop`,
  `clean`, `drive start|stop`, `model set`, `project add|remove`;
- poll a submitted command's durable result with `status`;
- build automation that must parse results, so it needs the `--json` shapes and the exit-code
  rules.

Do not use this skill for the interactive REPL, for row-number selection, for `cd`/scope
navigation, for `watch`, or for the `!` command prefix. Those exist only interactively, and they are
covered by `agent-cluster-cli-interactive`.

## The Daily Workflow: What Did the Agent Just Do

The most common question is "what did this agent just do", and it needs two reads with **opposite
identifier rules**. One `--json list` read resolves both identifiers, so no lookup is repeated.

```bash
# 1. Resolve both identifiers in one read
agent-cluster-cli --json list 2>/dev/null \
  | jq -r '.[] | [.endpoint_id,.cluster_session_id,.provider_session_id,.provider_generation] | @tsv'
```

```text
ac.ai-dev	res_50da448edfd53f9b19032af9354c290e	20261123131848	636422598
```

```bash
# 2. Conversation: the PROVIDER session ID, and it is oldest-first, so tail it
agent-cluster-cli --json messages ac.ai-dev 20261123131848 -c 2000 2>/dev/null \
  | jq -r '.messages[-2:][] | "--- #\(.no) \(.role) ---\n\(.content)"'

# 3. Recent output: the CLUSTER resource ID; -n and --lines are the same bound
agent-cluster-cli --json logs ac.ai-dev res_50da448edfd53f9b19032af9354c290e -n 50 2>/dev/null \
  | jq -r '.data'
```

| Read | Accepts | Rejects |
|---|---|---|
| `messages <endpoint> <session>` | the **provider session ID** (`20261123131848`) | a cluster resource ID → `invalid_target: session_id must be the provider session ID, not a cluster resource ID` |
| `logs <endpoint> <session>` | the **cluster resource ID** (`res_50da...`) | a provider session ID → `output snapshot failed: unknown_resource` |

The two mismatches do **not** fail the same way, and the difference decides whether a script notices:

| Mismatch | Human output | `--json` output | Exit |
|---|---|---|---|
| `messages` given a cluster resource ID | `server request failed (400): invalid_target: ...` on stderr | nothing on stdout | `2` |
| `logs` given a provider session ID | `output snapshot failed: unknown_resource` on stderr | nothing on stdout | `2` |

Both forms now fail the same way, because one shared guard performs the read and the check before
either renderer runs. A script may therefore trust the exit status for `logs`, and `--json` never
prints a document describing a read that failed.

The reason the two reads take opposite identifiers is deliberate: `messages` reads persisted provider
data, which a stopped session still has and which is keyed by the provider's own identifier, while
`logs` addresses a cluster resource.

`messages` prints oldest first, so the newest turn is the **last** element. Reading `.messages[0]`
answers "how did this start", not "what just happened".

## Invocation and Global Options

```text
agent-cluster-cli [options] <command> [arguments]
```

Global options may be written **before or after** the command word; the parser hoists trailing
options. Both `--json` and `-json` are accepted.

Hoisting stops at the `--` separator. Everything after `--` is literal argv by contract, so a
global option written there is a command argument and never an option. `exec` is the command with
that separator, and `exec ep -- apt-get install --yes pkg` is a legitimate invocation in which the
trailing `--yes` belongs to `apt-get`. Write the confirming `--yes` before `--`, as in
`exec <endpoint> --yes -- <argv...>`.

| Option | Meaning |
|---|---|
| `--json` | Write the structured document instead of the rendered form |
| `--endpoint <id>` | Filter by endpoint ID; also required by `--endpoint-token` |
| `--yes` | Confirm a mutating action |
| `--server-url <url>` | Server API URL (default `http://127.0.0.1:8080`) |
| `--token <token>` | Server credential; `hmac` mode needs `key_id.secret` form |
| `--auth-mode <hmac\|bearer>` | Credential presentation mode (default `hmac`) |
| `--server-profile <name[,name]>` | Named Server profile or ordered failover group (default `primary,secondary`) |
| `--endpoint-token <token>` | Token the target Endpoint accepts; requires a single endpoint |
| `--wait-timeout-ms <n>` | Maximum local wait for command completion |
| `--max-bytes <n>` | Maximum output snapshot size in bytes (default `65536`) |
| `--lines <n>` | Output lines for `logs` (default `100`; the standalone surface accepts any non-negative count, and a negative value is rejected) |
| `--follow`, `-f` | Stream output records until interrupted; `logs` only |
| `--limit <n>` | Maximum history rows; `0` keeps the provider's own window |
| `--max-chars <n>`, `-c <n>` | Maximum characters per message; ceiling `100000` |
| `--max-tokens <n>`, `-t <n>` | Maximum tokens per message; ceiling `200000`; `0` means no bound, and an absent value uses `5000` |
| `--generation <g>` | Target generation, as an alternative to the positional slot |
| `-s <id>`, `--session <id>` | Provider session identifier for `resume` |
| `--profile <id>`, `--profile-revision <rev>` | Launch profile for `start` (both required) |
| `--folder <path>`, `--task <text>` | Working folder and literal initial task for `start` |
| `--no-color`, `--no-truncate`, `--no-progress` | Presentation only; never change the data |
| `--help`, `-h` | Detailed help for the command; same output as `help <command>`; exits `0` |
| `--version`, `-v` | Print the binary identity; add `--json` for a structured document; exits `0` |

`--` ends option parsing. Before it, `--help` and `-v` are meta-options; after it, everything is
literal data. `exec` keeps its own `--` because the terminator is part of its syntax.

## Command Reference

### Read commands

| Command | Syntax | Notes |
|---|---|---|
| `list` | `list [--clean] [-a\|--all] [--full] [--brief]` | Reads only the Server's persisted inventory. Offline endpoints are omitted; in the rendered form they are reported once as `offline endpoints hidden: N (use --all to include)` on stdout, and `--json` omits that line. `--all` includes them; `--clean` omits an online endpoint that failed to report |
| `refresh` | `refresh [endpoint] [-a\|--all]` | Forces one fresh collection and waits for it to be committed, then renders the committed inventory. The only command that makes the next read fresh |
| `endpoints` | `endpoints [endpoint-id]` | Registered endpoints with connection state, observation time and capability revision. Never forces discovery |
| `show` | `show <endpoint-or-session>` | Endpoint or session detail; returns `{capabilities, command_history, endpoint, inventory, session}` |
| `info` | `info <session-id>` | Session detail including the provider's own `provider_metadata` and `provider_runtime` documents |
| `logs` | `logs <endpoint> <session> [-n N\|--lines N] [-f\|--follow]` | Bounded output snapshot, or a live tail with `--follow`; `-n` and `--lines` are one bound |
| `history` | `history <endpoint-id-or-hostname> [--limit N]` | Live provider session history, never a persisted projection |
| `messages` | `messages <endpoint> <session-id> [-c N] [-t N]` | Persisted conversation; a stopped session can still be read. The session must be a provider session ID, not a cluster resource ID |
| `project` | `project <endpoint>` | Managed projects as standard Project resources; a live provider read |
| `model registry` | `model registry <endpoint>` | Models a launch from this endpoint can use, with the one in use marked |
| `model` | `model <endpoint> <session> [profile]` | Model profiles one session can select. This is a live provider query and can fail with `provider_error` |
| `status` | `status <command-id>` | Durable result of a submitted command |
| `drive status` | `drive status <endpoint> <session>` | Standard drive state from the persisted inventory; never probes the provider; takes no generation; accepts a cluster resource ID or a provider session ID |

### Action commands

| Command | Syntax | Confirmation |
|---|---|---|
| `send` | `send <endpoint> <resource> [text] [generation]` | `--yes` |
| `btw` | `btw <endpoint> <resource> [text] [generation]` | `--yes` |
| `interrupt` | `interrupt [soft\|hard] <endpoint> <resource> [message] [generation]` — the action word is its own slot; both actions accept a message; the generation travels in `--generation` only | `--yes` |
| `ctl` (alias `control`) | `ctl <endpoint> <resource> <action> [json] [generation]` | `--yes` |
| `exec` | `exec <endpoint> <resource> <generation> -- <argv...>` or `exec <endpoint> -- <argv...>`; `--yes` goes **before** `--` | `--yes` |
| `start` | `start <endpoint> <resource> [text] [generation] --profile <id> --profile-revision <rev>` | `--yes` |
| `resume` | `resume <endpoint> <resource> [generation]` or `resume <endpoint> -s <session-id> [--generation g]` | `--yes` |
| `stop` | `stop <endpoint> <resource> <generation>` | `--yes` |
| `clean` | `clean <endpoint> <resource> [generation]` | `--yes` |
| `drive start` / `drive stop` | `drive <start\|stop> <endpoint> <session> <generation>` | `--yes` |
| `model set` | `model set <endpoint> <model-profile-id-or-name>` | `--yes` |
| `project add` | `project add <endpoint> <folder> [name]` | `--yes` |
| `project remove` | `project remove <endpoint> <project-id>` | `--yes` |

### Meta commands

| Command | Meaning |
|---|---|
| `help [command]` | Command overview, or detailed help for one command; exits `0` |
| `interactive` (or `-i`) | Start the REPL. Requires a terminal on stdin; refuses `--json` and `--yes`; exits `2` without a terminal |

### Shorthands

| Spelling | Expands to |
|---|---|
| `lf` | `list --full` |
| `lb` | `list --brief` |
| `logf` | `logs -f` (follow is implied; a repeated `--follow` is rejected) |
| `control` | `ctl` |

## Confirmation and `--yes`

Every mutating command refuses to run without `--yes` and exits `2` with a message that names
the operation, the target and the exact payload:

```text
confirmation required for send target=res_8e7ef4b41d733a75867ccbff38c1dcd0 parameters={"text":"probe"}; rerun with --yes
```

The target is rendered as whichever identity the request carries: a cluster resource ID, or
`session=<provider-session-id>` for the `resume -s` form, or `endpoint=<endpoint-id>` for a
target-less operation such as `model set` and `project add`.

Read the `parameters=` fragment before adding `--yes`. It is the canonical payload the command
will submit, so it is the cheapest way to confirm that the text, action word or argv you meant
is the one that was parsed. This is how the argument traps below are caught before submission.

## Argument Traps

These are verified behaviours, not hypotheticals. Each one changes what a command means without
reporting an error.

- **Quote every text payload.** `send <endpoint> <resource> [text] [generation]` has two
  optional positionals. `send ep res hello world` parses `hello` as the text and `world` as the
  **generation**, and the confirmation line shows `parameters={"text":"hello"}`. Three or more
  words are rejected with `unexpected arguments "..."; quote the message text so it stays one
  argument`. Always pass one quoted argument, or omit the text and pipe a multi-line block.
- **`interrupt` gives the action word its own slot.** The grammar is
  `interrupt [soft|hard] <endpoint> <resource> [message] [generation]`. The action word is a
  subcommand, exactly like `drive <start|stop|status>`, so the message is a **separate** positional
  and never has to be prefixed with an action word:
  `interrupt ep res soft "stop now"` submits `{"action":"soft_interrupt","message":"stop now"}`.
  Both actions accept a message; the cluster forwards it without deciding which action may carry
  one, because that is a provider implementation detail. A bare `interrupt ep res` submits the hard
  default. A message with no action word is refused rather than guessed, so
  `interrupt ep res "stop now"` reports `interrupt needs an action word (soft or hard) before the
  message` instead of silently choosing an action.
- **`interrupt` takes the generation only through `--generation`.** There is no positional
  generation slot, because a positional generation is an unconstrained string and would be
  indistinguishable from a second word of an unquoted message: `interrupt ep res soft stop now`
  would send `stop` as the message and `now` as the expected generation. Use
  `interrupt ep res soft "stop now" --generation <gen>`. An unquoted message is then refused with
  `unexpected arguments "stop now"; quote the message text so it stays one argument`.
- **`interrupt` accepts exactly two action words.** `soft` and `hard` are the only CLI words;
  `s`, `h`, `soft_interrupt` and `hard_interrupt` are refused with
  `interrupt needs an action word (soft or hard) before the message`. The wire names
  `soft_interrupt` and `hard_interrupt` are what the provider decodes, so they appear in the
  payload and never on the command line.
- **The `interrupt` JSON form is validated locally.** A JSON object in the message slot is
  accepted, but only with the fields `action` and `message`, and `action` must be the wire name
  that agrees with the action word. `{"action":"soft_interrupt","msg":"x"}` is refused with
  `JSON field "msg" is not part of the interrupt payload`, and `{"action":"soft"}` is refused
  with `the document carries the wire action name`. An empty `{}` receives the action word, so
  `interrupt soft ep res '{}'` submits `{"action":"soft_interrupt"}`. Prefer the plain form.
- **A message on `hard` is refused by the shipped provider, not by the cluster.** The cluster
  contract allows a message on both actions and forwards it without deciding which action may carry
  one. The TopsailAI provider does not implement that: `interrupt hard ep res "please stop"` is
  accepted by the cluster and then refused at the provider seam with
  `hard_interrupt does not accept a message` as `invalid_request` / `not_applied`. Treat this as a
  provider limitation rather than a syntax error, and use `soft` when a message must reach the agent.
- **`exec` requires `--`, and `--yes` must come before it.** Without `--` the command reports
  `usage: exec <endpoint-id> <resource-id> <generation> -- <argv...>`. The argv array comes from
  the shell's own word splitting and is never re-tokenized. The endpoint-only form
  (`exec <endpoint> -- <argv>`) must not carry a generation.
  A `--yes` written after `--` becomes part of the argv, so the command stays unconfirmed and the
  refusal says `the --yes after -- is part of the command argv, so it did not confirm; write --yes
  before --`. That wording is the signal to move the flag, not to add it again. The tail is never
  rewritten, because `exec ep -- apt-get install --yes pkg` legitimately passes `--yes` to
  `apt-get`.
- **The endpoint-only form needs `AGENT_CLUSTER_ENDPOINT_COMMAND_DIR` on that Endpoint.** The form
  addresses the machine, so its working directory comes from Endpoint configuration rather than
  from a session. When the setting is unset the request is refused with
  `command_directory_unavailable` and a message naming the setting; the form is then unavailable
  until an operator configures it. This is distinct from `session_directory_unavailable`, which
  means a session-scoped request found no usable directory in provider evidence. Do not read the
  endpoint-scope refusal as "this endpoint has no session" — the form addresses no session by
  design.
- **`stop` requires a generation positionally**; `clean` does not, because an expired session
  may have no verified liveness.
- **`drive status` takes no generation** and refuses one.
- **`drive status` accepts a cluster resource ID or a provider session ID.** The resource ID
  namespace is searched first, so a token that is both keeps its routing meaning; a provider session
  ID that matches several rows is refused with the count and the remedy rather than resolved to the
  first. `drive start` and `drive stop` still require the cluster resource ID, because they address a
  live process and must carry a generation.
- **`-n` and `--lines` are the same bound on both surfaces.** `logs ep res -n 3` works standalone.
  Stating both with different values is refused with `--lines 5 and -n 3 disagree; state the bound
  once`, because either choice would silently ignore a bound the operator stated.
- **`resume` accepts either `-s <session-id>` or a positional resource ID, never both.** In the
  `-s` form the generation must be stated with `--generation`, because the positional slot
  belongs to the resource ID.
- **`messages` rejects a disagreeing duplicate bound.** `-c 100 --max-chars 200` fails with
  `--max-chars 200 and -c 100 disagree; state the bound once`. A value above the ceiling is
  rejected rather than clamped, so the bound honoured is the bound asked for.
- **`model` and `project` subcommands are recognised only as the first argument**, so an
  endpoint identifier that happens to be spelled `set`, `registry`, `add` or `remove` is still
  usable in the read form.
- **`--endpoint-token` requires a single endpoint**, stated with `--endpoint` or as the
  command's own endpoint argument.

## JSON Output Shapes

`--json` writes one document to stdout. Verified shapes:

| Command | Document |
|---|---|
| `list`, `refresh` | Array of session rows: `endpoint_id`, `adapter_id`, `cluster_session_id`, `provider_session_id`, `provider_display_name`, `provider_project_workspace`, `provider_generation`, `state`, `collection_status`, `stale`, `unknown`, `last_success_at_ms`, `messages`, `drive` |
| `endpoints` | Array: `endpoint_id`, `instance_id`, `display_name`, `hostname`, `connection_state`, `observed_at_ms`, `capability_revision` |
| `show` | Object: `capabilities`, `command_history`, `endpoint`, `inventory`, `session` |
| `info` | Object: `endpoint_id`, `session`, `provider_metadata`, `provider_runtime` |
| `logs` | Object: `data`, `observed_at_ms`, `truncated` |
| `logs --follow --json` | One document per record, carrying a `Lines` array |
| `history` | Object: `endpoint_id`, `rows` |
| `project` | Object: `projects` (each with `project_id`, `name`, `path`) |
| `model registry` | Object: `endpoint_id`, `rows` (each with `no`, `model_profile_id`, `provider_display_name`, `available`) |
| `messages` | Object: `endpoint_id`, `provider_session_id`, `messages` |
| `drive status` | Object: `endpoint_id`, `cluster_session_id`, `provider_generation`, `observed_at_ms`, `drive` (`state`, `reason`, `verified`, `observed_at_ms`) |
| Action commands, `status` | Receipt envelope carrying both spellings of each field: `CommandID`/`command_id`, `Status`/`status`, `Phase`/`phase`, `DeliveryBoundary`/`delivery_boundary`, `EffectCertainty`/`effect_certainty`, `ErrorCode`/`error_code`, `ProviderResponse`/`provider_response`, `ProviderResponseTruncated`/`provider_response_truncated`, `intent_json`, `request_hash` |

The rendered (non-JSON) form of an action result prints the status label, then
`command_id`, `phase`, `delivery_boundary`, `effect_certainty`, `outcome`, `error_code`,
`error_message`, then a `provider_response:` section holding the provider's own document. A
`finished` receipt renders only `confirmed result`, so use `--json` when you need the full
evidence.

## Exit Codes and Failure Semantics

| Code | Meaning |
|---|---|
| `0` | Success — **and also a rejected or failed receipt**, and also `help` and `--version` |
| `2` | Usage error, missing `--yes`, configuration error, unknown command, unknown flag, **and a target that does not exist** |
| `130` | Interactive REPL interrupted |

Three failure classes exist, and the difference decides what a script must do:

| Class | Exit | Example | Meaning |
|---|---|---|---|
| **Receipt rejection** | `0` | `resume` on a live session → `status: rejected`, `error_code: target_still_active` | The command reached the Endpoint and was refused. The receipt is the authority |
| **Local or transport failure** | `2` | `show no-such-endpoint` → `endpoint or session "..." was not found`; `info res_doesnotexist` → `session "..." was not found on any endpoint`; `status cmd_doesnotexist` → `server request failed (404): not_found` | The command never produced a receipt. Nothing was submitted |
| **Read failure** | `2` | `--json logs ep <provider-session-id>` → stderr `output snapshot failed: unknown_resource`, stdout empty | The read failed. One shared guard performs the read and the check before either renderer runs, so the human and `--json` forms fail identically |

Consequences you must respect:

- Never treat exit `0` as proof that an action happened. Read `status` and `error_code`.
  Verified example: `resume` on a live session exits `0` with `status: rejected`,
  `error_code: target_still_active`, `effect_certainty: not_applied`.
- A `--json` read that fails exits `2` and prints nothing on stdout, so an empty `data` field now
  means the read succeeded and the provider had nothing to show.
- Never treat exit `2` as proof that the command was malformed. A not-found target also exits `2`,
  so read the message before concluding that the syntax was wrong.
- A usage error exits `2` and writes the reason to stderr, so a script can distinguish "the
  command was malformed" from "the Endpoint refused the command".
- A non-interactive command never silently degrades to a weaker behaviour. If the stronger
  behaviour is unavailable it fails explicitly rather than returning cached or partial data
  under the same command name.
- `logs --follow` ends on SIGINT with `log.follow> follow stopped` and exit `0`. That is a
  normal stop, not a failure.

## Credentials and Configuration

The CLI resolves configuration from five sources, first match wins per key:

| Rank | Source |
|---|---|
| 1 | Explicit flag (`--server-url`, `--token`) |
| 2 | Process environment |
| 3 | `/opt/agent-cluster/bin/.env.local` |
| 4 | `${HOME}/.topsailai/.topsailai_agent_cluster.env` |
| 5 | Built-in default (`http://127.0.0.1:8080`, empty token) |

Keys: `AGENT_CLUSTER_CLI_SERVER_URL`, `_SERVER_TOKEN`, `_AUTH_MODE`, `_SERVER_PROFILES`,
`_SERVER_PROFILE_TOKENS`, `_SERVER_PROFILE`, `_SERVER_PROFILE_STICKY_FILE`,
`_ENDPOINT_TOKENS`, `_HISTORY_FILE`, `_HISTORY_MAX_ENTRIES`, `_HISTORY_MAX_SIZE_MB`,
`_HISTORY_MAX_BACKUPS`.

The legacy names (`AGENT_CLUSTER_SERVER_URL`, `AGENT_CLUSTER_TOKEN`, `AGENT_CLUSTER_CLI_TOKEN`,
`AGENT_CLUSTER_ENDPOINT_TOKENS`, `AGENT_CLUSTER_HISTORY_*`) are **no longer read**. A CLI that
still exports one of them silently uses the built-in default, and no warning is printed.

Two credentials are independent. The Server token is verified by the Server and terminates
there. The Endpoint token is verified by the Endpoint and forwarded opaquely by the Server, so a
missing Endpoint token produces a `policy_denied` refusal that the CLI annotates with the
missing configuration key. In `hmac` mode the Endpoint token must be in `key_id.secret` form; a
token that cannot be signed is reported as a local configuration error before anything is sent.

## Common Pitfalls

- **Reading the exit status instead of the receipt.** A refused action exits `0`. Parse
  `status`/`error_code`, or you will report a refusal as a success.
- **Forgetting `--yes` and calling it a failure.** The refusal is exit `2` with the exact
  payload printed. Read that payload, then re-run with `--yes` only if it is what you meant.
- **Passing unquoted multi-word text.** Two words silently become text plus generation; three
  or more are rejected. Quote the text, or pipe a block and finish it with a standalone `EOF`
  line or Ctrl+D.
- **Assuming `list` is fresh.** `list` renders only the persisted inventory. Use `refresh` when
  the answer must be current, and remember `refresh` is the only command that forces a
  collection.
- **Expecting `list` to show every endpoint.** Offline endpoints are omitted by default and
  reported as a hidden count on stdout; `--all` includes them.
- **Using a cluster resource ID where a provider session ID is required.** `messages` accepts
  only the provider session ID, because a stopped session has no cluster resource ID.
- **Using a provider session ID where a cluster resource ID is required.** `logs` accepts only the
  cluster resource ID, so `logs ep 20261123131848` fails with
  `output snapshot failed: unknown_resource` and exits `2` in both the human and `--json` forms.
  `drive status` is the exception among the drive actions: it also accepts a provider session ID,
  because it reads persisted data rather than addressing a live process. The two reads take opposite
  identifiers; see "The Daily Workflow" above.
- **Treating `model <endpoint> <session>` as always available.** It is a live provider query and
  can fail with `provider_error`; `model registry` is the machine-level read and is the safer
  probe.
- **Assuming `drive stop` stops the agent.** A driver injects input on the operator's behalf; it
  is not the agent. `drive stop` leaves the agent running.
- **Assuming `project remove` deletes a folder.** It removes one registry entry only. The folder
  and its contents are untouched.
- **Assuming `clean` always deletes something.** It deletes only provider-owned expired
  artifacts for one exact session. The provider reports four delivery states, and only one of
  them removed anything: `nothing_to_delete` (no eligible file, or every candidate was skipped
  by mutation-time revalidation), `preview` (files are eligible but the provider was not
  confirmed), `partial` (some deletions failed), and `deleted`. The eligibility rule is stated
  in the provider message: files must be idle and older than three days. Check `deleted` and
  `failed` rather than assuming success.
- **Parsing stdout when diagnostics are mixed in.** The resolved Server profile line goes to
  stderr, so `--json` on stdout stays clean. Do not merge the streams before parsing.
- **Writing global options after a positional payload.** They are hoisted, so a flag written
  after the payload is still a flag. That is convenient, and it is also why a mutating command
  can run when you believed you were only inspecting it. Hoisting stops at `--`: a flag written
  after the separator is argv, so `exec ep -- ls --yes` runs `ls --yes` unconfirmed instead of
  confirming the command.

## Verification Checklist

- [ ] The command spelling was taken from `agent-cluster-cli help <command>`, not recalled.
- [ ] Every text payload is one quoted argument, or a piped block terminated by `EOF`.
- [ ] Every mutating command carries `--yes`, and the printed `parameters=` was read first.
- [ ] The result was judged by `status`/`error_code`, not by the exit status alone.
- [ ] `--json` was used when the result must be parsed, and stdout was parsed without stderr.
- [ ] `refresh` was used when the answer had to be current, and `list` was not assumed fresh.
- [ ] The credential came from the documented source, and no legacy variable name was relied on.
- [ ] A destructive command was confirmed against the exact target and generation before running.

## File Structure Description

- **bin/**: None. This skill documents an existing installed binary,
  `agent-cluster-cli`, and ships no executable of its own.
- **scripts/**: None. Every command in this skill is invoked directly.
- **references/**: None. The command grammar, confirmation matrix, JSON shapes and exit codes
  are complete in this document.
- **assets/**: None.
