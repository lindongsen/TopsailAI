---
maintainer: AI
author: DawsonLin
---

# Provider control actions and instructions

This document is the reference for the catalog in `conf/control-actions.conf.example`. That file is a repository reference, not an installed file: no deployment path ships it, so an operator copies it by hand to the path the Provider reads and points `AGENT_CLUSTER_TOPSAILAI_CONTROL_ACTIONS` at that copy. It records what the TopsailAI provider actually serves, so an operator can decide which entries to enable without reading provider source.

The catalog is read by the TopsailAI Provider CLI at its own process boundary, through `AGENT_CLUSTER_TOPSAILAI_CONTROL_ACTIONS`. The Endpoint does not parse it: the Endpoint advertises the `ctl.` capabilities named in its `ADAPTERS` document and refuses anything else, so the two documents are the two halves of one decision. The catalog says what an action runs; the adapter document says who may run it.

Everything below was read from the installed provider: `topsailai docs read usage/topsailai_send_control.md`, `topsailai runtime control --help`, and the handler and instruction modules under `workspace/`. It describes the provider as it exists today, not a proposal.

## Three layers

The provider exposes three different things, and they are not interchangeable.

| Layer | What it is | How the catalog reaches it |
|---|---|---|
| Control handlers | Ten fixed actions on the session control channel | One catalog entry per handler, each naming its own provider command |
| Instructions | Registered `/` commands inside a live agent | One catalog entry, `call_instruction`, whose payload names the instruction |
| Provider CLI verbs | `send`, `btw`, `control`, `logs` | Not in this catalog; they back the standard `message.send`, `context.inject` and `output.snapshot` operations |

The catalog covers control actions only. `send`, `btw` and `logs` are standard cluster operations with their own payload contracts, so they are not duplicated here.

## Control handlers

The handler set is discovered from the live registry, so it can grow through plugins. These ten are registered by the current build.

| Action | Payload | Result on success | Typical errors |
|---|---|---|---|
| `call_instruction` | `instruction` required string, `args` optional list, `kwargs` optional object | The instruction's own return value | `missing or invalid instruction`, `args must be a list`, `kwargs must be an object`, `unknown instruction: NAME`, `instruction failed: ...` |
| `clear_interrupt` | none | `action`, `session_id`, `pid`, `flag_path`, `removed`, `message` | `missing session_id`, `missing pid`, `failed to clear interrupt flag: ...` |
| `clear_pause` | none | `action`, `session_id`, `pid`, `flag_path`, `removed`, `message` | `missing session_id`, `missing pid`, `failed to clear pause marker: ...` |
| `get_runtime_messages` | none | `count`, `messages` | `no active agent in control context or current thread`, `active agent has no messages attribute` |
| `get_session_messages` | `session_id` required string | `count`, `messages` | `missing or empty session_id`, `session manager is not available`, `session not found: ID`, `failed to retrieve session messages: ...` |
| `hard_interrupt` | none | `action`, `session_id`, `pid`, `flag_path`, `message` | `missing session_id`, `missing pid`, `failed to write interrupt flag: ...` |
| `heartbeat` | must be empty | `alive`, `pid`, `hostname`, `session_id` nullable | `invalid_payload` when any field is supplied |
| `llm_control` | `operation` must be `force_retry` | `state: "flag_written"` | `unavailable`, `invalid_operation`, `unsupported_target`, `flag_write_failed`, `not_waiting` |
| `pause` | `reason` optional string, `prompt` optional string, `timeout_seconds` optional number, `default` optional `continue` or `interrupt` | `action`, `session_id`, `pid`, `flag_path`, `state: "pause_requested"`, `message` | `missing session_id`, `missing pid`, `failed to write pause marker: ...` |
| `soft_interrupt` | `message` optional string | `action`, `session_id`, `pid`, `file_path`, `message` | `missing session_id`, `missing pid`, `failed to append inject message: ...` |

A handler that rejects a request returns top-level `status: "error"` with an `error` string. A successful response means the handler accepted and performed its own local step. It never means the agent has already reacted.

### Acceptance is not reaction

This distinction decides how an operator should read a result, so it is stated per action.

| Action | What a success proves | What it does not prove |
|---|---|---|
| `pause` | The pause marker was written | The agent blocked. It pauses at its next safe point, never mid-stream, and only the outermost agent consumes the marker |
| `clear_pause` | An unconsumed marker was removed, or none existed | A consumed marker was undone |
| `hard_interrupt` | The interrupt flag was written | The agent stopped |
| `clear_interrupt` | The flag was removed, or none existed | An already-observed interrupt was cancelled |
| `soft_interrupt` | A user message was appended to the inject file | The agent consumed it. It is queued for the next LLM call |
| `heartbeat` | The control channel answered | Agent or LLM progress |
| `llm_control` | A retry flag was staged | A retry happened |
| `get_runtime_messages` | The process's current messages were read | Anything about task state |
| `get_session_messages` | Persisted messages were read | Anything about task state |

Two ordering facts matter. A hard interrupt arriving before a pause marker is consumed wins and discards the marker. When no input channel is available the agent logs a warning and continues instead of blocking forever, so a pause can be accepted and never take effect.

### `pause` payload normalization

The handler does not trust the payload shape, and it silently normalizes rather than rejecting.

| Field | Accepted | Anything else becomes |
|---|---|---|
| `timeout_seconds` | Positive finite number | `0.0`, which waits forever. Booleans, NaN, infinity and non-numbers all fall here |
| `default` | `continue` or `interrupt`, case-insensitive | `continue` |
| `prompt` | Non-blank string | The built-in prompt |
| `reason` | Any string | Empty string |

A negative `timeout_seconds` therefore means wait forever, not fail fast. An operator who wants a bounded wait must supply a positive number.

### `heartbeat` rejects any payload

The handler returns `invalid_payload` when the payload is non-empty. The catalog entry therefore carries an object schema with no properties, so the guided prompt asks nothing and sends `{}`. A schema that documented a field would invite an operator to fill it in and get a guaranteed rejection.

### `llm_control` serves one operation

The handler hardcodes the accepted operation.

```text
operation != "force_retry"        -> invalid_operation
"target" present in the payload   -> unsupported_target
context.pid != os.getpid()        -> unavailable
no active agent chat              -> unavailable
stage_retry() returned false      -> not_waiting
```

`force_retry` abandons the current request attempt and reuses the existing retry loop, remaining budget and backoff. It does not restart the agent or its tools, does not reset the budget, and does not guarantee another attempt when the budget is exhausted.

The provider documentation also describes `status` and `hard_interrupt` operations for a routing-capable handler. **This build does not register that handler**, so both are rejected with `invalid_operation`. The catalog must not advertise them, and it does not. `not_waiting` is a success-shaped CLI exit with a non-applied effect: no first-byte wait marker existed, so nothing was staged.

### `call_instruction` is a factory layer

This is the one action whose reachable surface is not fixed at build time.

```text
CallInstructionHandler.handle
  -> hook_instruction.call_instruction(name, *args, **kwargs)
     -> self.hook_map["/" + name]
        -> every registered HookFunc for that name
```

The registry is built from `INSTRUCTIONS` dictionaries collected by `get_function_map("topsailai.workspace.plugin_instruction", key="INSTRUCTIONS")`, plus external plugins named in the semicolon-separated `TOPSAILAI_PLUGIN_INSTRUCTIONS` environment variable, plus instructions registered directly on the hook object.

Three consequences follow.

- The instruction set is a property of the live agent process, not of the provider installation. A catalog listing instructions is a snapshot, not a live view.
- `hook_map[name]` is a list. `call_instruction` invokes every function registered under the name and returns only the **last** result. Earlier results are discarded silently, so a name with several handlers cannot report all of them.
- `INSTRUCTIONS["git"] = INSTRUCTIONS["git.git"]` is an alias, so `/git` and `/git.git` are the same handler reached by two names.

The handler validates before dispatch: `instruction` must be a non-empty string, `args` must be a list, `kwargs` must be an object, and the name must exist in the live registry. A name that is absent fails with `unknown instruction: NAME` instead of being attempted.

## Instructions

Forty-six instructions are registered in a live agent. The leading `/` is optional in the payload, because the handler adds it when missing.

### Agent and model

| Instruction | Arguments | Effect |
|---|---|---|
| `help` | none | Print help |
| `agent.system_prompt` | none | Print the system prompt |
| `agent.env_prompt` | none | Print the environment prompt |
| `agent.tool_prompt` | none | Print the tool prompt |
| `agent.tools` | none | Return the sorted tool names available to the active agent |
| `agent.tools_observation` | none | Return observations exposed by the agent's tool modules |
| `agent.set_llm` | positional, or `model=`, `base_url=`, `api_key=`, `api_key_env=` | Change LLM configuration for the active agent |
| `agent.models` | none, a model name, or a 1-based index | List or select a model from the user registry |
| `agent.llm` | none | Print the LLM name |
| `agent.messages` | none | Print the current messages |
| `agent.tokens` | none | Report token usage for the two current message layers |

### Environment

| Instruction | Arguments | Effect |
|---|---|---|
| `env.set` | `k`, `v` | Set an environment value |
| `env.get` | `k` | Read an environment value |
| `env.print_step_mode` | none, a 1-based index, or a mode name | Show or set `TOPSAILAI_PRINT_STEP_MODE` |

### Git, read-only

`git.git` is the dispatcher and `git` is its alias. Both validate the subcommand against a read-only allowlist before running anything.

| Instruction | Arguments | Effect |
|---|---|---|
| `git.git` | subcommand plus arguments | Run one read-only git command |
| `git` | same as `git.git` | Alias of `git.git` |
| `git.git_status` | none | `git status` |
| `git.git_log` | none | `git log` |
| `git.git_diff` | none | `git diff` |
| `git.git_show` | none | `git show` |
| `git.git_branch` | none | `git branch` |
| `git.git_tag` | none | `git tag` |
| `git.git_remote` | none | `git remote` |

Allowed subcommands are `status`, `show`, `log`, `diff`, `branch`, `tag`, `remote`, `rev-parse`, `ls-files` and `config`. `config` is further restricted to `--get`, `--get-all`, `--get-regexp` and `--list`. Write and destructive flags on `branch` and `tag` are rejected. The working directory resolves from `TOPSAILAI_PROJECT_FOLDER`, then `TOPSAILAI_PWD`, then the process working directory.

### Skills

| Instruction | Arguments | Effect |
|---|---|---|
| `skill.show` | optional name filter | Return cached skills |
| `skill.load` | skill folder | Load a skill and return its status |
| `skill.unload` | skill folder | Unload a skill and return its status |
| `skill.hooks` | none | Return the sorted skill hook names |
| `skill_repo.list` | none | List skill folders under the skill root |
| `skill_repo.install` | local path, URL, git URL or zip path | Install a skill |
| `skill_repo.uninstall` | skill folder name | Remove a skill folder |

### Statistics

| Instruction | Arguments | Effect |
|---|---|---|
| `stat.tool_call` | optional tool name | Show tool-call statistics |
| `stat.tool_call_errors` | optional tool name | Show tool-call errors |
| `stat.tool_call_reset` | none | Reset the active agent's statistics |
| `stat.tool_call_log` | none | Export tool-call information |

### Context and session

| Instruction | Arguments | Effect |
|---|---|---|
| `ctx.clear` | none | Clear all context messages for the session |
| `ctx.story` | none | Save context messages to a new story |
| `ctx.history` | optional `head:tail` slice | Return the session history |
| `ctx.history2` | none | Return raw history messages |
| `ctx.del_msg` | `index`, 1-based | Delete one message by sequence number |
| `ctx.del_msgs` | several 1-based indexes | Delete several messages |
| `ctx.del_msg_ids` | `msg_ids` list | Delete one message by message ID |
| `ctx.summarize` | `head_offset_to_keep`, `need_interactive`, `to_force` | Summarize context messages |
| `ctx.search` | `keyword` | Search context messages |
| `ctx.btw` | positional words | Add a by-the-way message to the ephemeral context |
| `session.rename` | positional words | Rename the session and refresh its update time |

### Hosting

| Instruction | Arguments | Effect |
|---|---|---|
| `hosting` | none | Start supervised background hosting for the current session |

`hosting` is registered directly on the hook object rather than through an `INSTRUCTIONS` dictionary, and it starts a real child process. It is the only instruction that creates a long-lived process.

## What cannot be enumerated statically

A catalog is a configuration file, so it can only list what someone wrote down. Three parts of the instruction surface resist a static list.

- **`ctx.*`, `agent.tokens` and `session.rename`** are registered by `workspace/context/instruction.py` through `load_instructions`, not by an `INSTRUCTIONS` dictionary under `plugin_instruction/`. A scan of that package alone misses all twelve.
- **`hosting`** is registered by `hook_instruction.py` directly, so it appears in no dictionary either.
- **Plugin instructions** arrive through `TOPSAILAI_PLUGIN_INSTRUCTIONS` at agent start. They exist only in the live process, so a catalog cannot know them in advance.

The catalog therefore lists the instructions the current build registers, and the provider still validates every name against the live registry. An instruction added by a plugin is reachable through `call_instruction` even when the catalog does not list it, because the enum is a prompt convenience and not the authorization boundary. The authorization boundary is the catalog entry itself: an operator can only reach `call_instruction` when that entry is enabled.

## How the catalog maps onto this

Each catalog entry declares four things, and all four come from the file.

| Field | Meaning for these actions |
|---|---|
| `name` | The public `ctl.<name>` operation. It is not the provider action name, although the shipped catalog uses the same spelling |
| `permission` | Not declared here. The operator scope is declared on the Endpoint's `ADAPTERS` capability entry for the same operation name, because the Endpoint is the component that enforces it |
| `payload_schema` | What the guided prompt asks. An enum becomes a numbered menu, so an unsupported value cannot be typed |
| `command` | The provider argv template, with `{session}` and `{payload}` placeholders |

Two consequences are worth stating plainly.

- **One entry means one permission.** `call_instruction` reaches read-only instructions such as `ctx.history` and mutating ones such as `ctx.clear` under a single scope. A site that needs to separate them declares several catalog entries that share the same `command` but pin the instruction with `payload_constants`, and declares a different `required_permission` for each of those operation names in the Endpoint's `ADAPTERS` document. The shipped example does exactly that; see the instruction shortcuts below.
- **The enum is a prompt, not a gate.** The provider validates the instruction name against its live registry. A name absent from the enum can still be submitted by a caller that builds the payload itself, so the enum must not be mistaken for an allowlist. The same holds for a pinned constant: it narrows what the menu offers, not what a hand-built payload can reach, because the Endpoint does not validate a payload against the advertised schema.

## Shortcuts

A shortcut is a second name for an action that already exists in the catalog. It
exists so a frequent action can be typed quickly: with the shipped entries an
operator types `ctl.session.messages` instead of `ctl.get_session_messages`, and
the dotted spelling skips the action menu entirely.

The Provider has no alias concept, so a shortcut is written out as a full copy of
the action it names: same `command`, same `payload_schema`, same
`payload_session_field`, same `payload_constants`.

```json
{
  "name": "session.messages",
  "payload_schema": {"type": "object", "properties": {}},
  "payload_session_field": "session_id",
  "command": ["runtime", "control", "get_session_messages", "-s", "{session}", "-a", "{payload}", "--json"]
}
```

A copy cannot widen what an operator may do and cannot run a different command,
because it is the same document. The cost is that the two entries are independent:
retiring the target does not retire its copies, so remove both when you retire an
action. `TestShippedCatalogKeepsShortcutCopiesIdentical` fails if a copy drifts from
its target, and `TestShippedCatalogDeclaresNoAlias` fails if an `alias_of` entry is
ever added back in the Endpoint-only shape.

Rules enforced at load time:

- Every entry is a real action, so it must declare `command`.
- A name may appear only once.
- An unknown field is refused rather than ignored, so a leftover `alias_of` or
  `permission` fails at startup instead of being silently dropped.
The shipped catalog carries 10 shortcut entries: `session.messages`,
`session.runtime_messages`, `session.heartbeat`, `session.pause`,
`session.unpause`, `session.interrupt`, `session.soft_interrupt`,
`session.clear_interrupt`, `session.instruction` and `session.llm`. The list is a
starting point, not a fixed set; nothing about a shortcut is compiled in.

## Migrating a catalog that used alias_of

An earlier catalog shape let one entry name another with `alias_of` instead of
repeating the target's `command`. That field is gone, because the Provider has no
alias concept: an alias was resolved by the Endpoint, and the Endpoint no longer
parses this file. A catalog that still carries `alias_of` now fails to load, and
the failure is deliberate rather than a compatibility gap. An unknown field is
refused instead of ignored, so a leftover alias cannot be silently dropped and
leave an operator believing a shortcut exists when it does not.

To migrate, replace each `alias_of` entry with a copy of its target's `command`,
keeping the alias name. The copy is the same document, so it cannot widen what an
operator may do and cannot run a different command. Two consequences follow, and
both are the operator's responsibility:

- The copy and its target are independent. Retiring the target does not retire the
  copy, so remove both when you retire an action.
- A copy that drifts from its target is a defect, not a variant. The shipped
  catalog is checked for this, but a hand-written catalog is not.

An entry that only needs to pin one instruction does not need a copy of the whole
`call_instruction` argv; use `payload_constants` as described in the next section.

## Instruction shortcuts

A plain copy cannot express a shortcut for one instruction. It copies the target's
whole payload schema, so a copy of `call_instruction` would still ask the operator
to choose from the 46-value enum. The layer does not match: `call_instruction` is
one catalog entry, and the instructions are values inside it.

A per-instruction shortcut is therefore a real catalog entry that reuses the
`call_instruction` argv and pins the instruction with `payload_constants`.

```json
{
  "name": "git.status",
  "payload_constants": {"instruction": "git.git_status"},
  "payload_schema": {
    "type": "object",
    "properties": {"args": {"type": "array"}, "kwargs": {"type": "object"}}
  },
  "command": ["runtime", "control", "call_instruction", "-s", "{session}", "-a", "{payload}", "--json"]
}
```

The operator types `ctl.git.status` and is asked only for `args` and `kwargs`. The
instruction is filled by the adapter before dispatch, so the enum never appears.

`payload_constants` is an object of payload field to literal value. Four rules are
enforced when the file loads:

- The value is a literal, never a template. A value containing `{` is rejected,
  because a constant that could expand would reintroduce the operator-controlled
  command the catalog exists to prevent.
- The entry must still carry a `{payload}` placeholder, since the constants are
  merged into that payload.
- A constant may not name the `payload_session_field`, because the adapter injects
  the selector itself.
- A supplied value that disagrees with the constant is rejected rather than
  overwritten. The catalog is the authorization surface, so a caller must not reach
  a different instruction through an entry that advertises one. The rejection is
  reported as `invalid_request` with `not_applied` effect certainty, because the
  entry exists and only the payload disagrees. An action the catalog does not list
  is a different case: it is reported as `unsupported` before any argv exists, so
  the operator must not go looking for a missing catalog entry when the entry is
  present and only the payload is wrong.

A shortcut inherits its target's constants and may not declare its own.

The shipped catalog defines 48 actions. Of those, 28 are instruction shortcuts:
entries that reuse the `call_instruction` argv and pin the instruction with
`payload_constants`, split by what they do.

| Effect | Shortcuts |
|---|---|
| read-only | `git.status`, `git.log`, `git.diff`, `git.show`, `git.branch`, `git.tag`, `git.remote`, `ctx.history`, `ctx.search`, `agent.tokens`, `agent.messages`, `agent.llm`, `agent.tools`, `skill.show`, `skill.hooks`, `skill_repo.list`, `stat.tool_call`, `stat.tool_call_errors`, `stat.tool_call_log` |
| mutating | `ctx.clear`, `ctx.del_msg`, `ctx.summarize`, `env.set`, `session.rename`, `skill.load`, `skill.unload`, `stat.tool_call_reset`, `agent.models` (mutating when it carries an argument) |

This table groups the shortcuts by what they do to the agent, not by who may run them.
No permission is declared here: the operator scope lives on the Endpoint's `ADAPTERS`
capability entry for the same operation name, as the field table above states.

The git shortcuts are spelled `git.status` rather than `git.git_status`, because
the doubled prefix is the provider's module naming and not something an operator
should have to type. The pinned value keeps the provider spelling.

Deliberately absent, because a shortcut would make a wide action too easy to reach:
`/hosting` starts a long-lived child process, `ctx.export` and `ctx.import` touch
files with complex arguments, `git.git_blame` is rarely used and takes many
arguments, `agent.set_llm` changes the model, and `skill_repo.install` and
`skill_repo.uninstall` change the installed skill set.

The split narrows the menu, not the wire. The Endpoint does not validate a payload
against the advertised schema, so a caller that builds the payload itself can still
submit any instruction name the provider registers, whatever permission the entry
it went through declares. Closing that gap needs Endpoint-side schema validation,
which is not implemented today.

## Tab completion

The interactive REPL completes a dotted control word from the Endpoint's
advertised actions, so `ctl.git.st` completes to `ctl.git.status ` and `ctl.`
lists every advertised action. The candidate set is the same capability
descriptor the Endpoint uses to authorize the action, so completion can never
offer an action the Endpoint would refuse, and a newly configured shortcut needs
no client change.

Completion reads a cache and never performs network I/O, because it runs inside
the keystroke handler. The cache is refreshed once per Endpoint change, so one
scope change costs one capability query instead of one query per keypress. A
failed query leaves the list empty rather than retrying on every prompt: TAB then
offers nothing, which is the safe outcome, and re-entering the Endpoint scope
refreshes it.

Completion is opt-in. A REPL that supplies no completion source performs no
capability query for completion at all, so the existing contract that a
capability query happens only when a command needs one is preserved.

Two limits are deliberate. A line that already carries a parameter is not
completed, because parameters are not completed and rewriting the command word
would move the cursor away from the argument. A command word that is not the
dotted spelling keeps the previous behaviour, so an argument is never rewritten.

## Provider gaps this catalog cannot close

These are provider-side limitations. The catalog documents them rather than working around them.

- **No structured instruction catalog.** The provider exposes instruction names and docstrings through `/help`, but no machine-readable signature document. The catalog's enum is therefore a hand-maintained snapshot.
- **No multi-handler disclosure.** `call_instruction` returns only the last result when a name has several handlers, and reports nothing about the others.
- **No `llm_control` operation enumeration.** The accepted operation is hardcoded, so the catalog states it as a one-value enum.
- **No non-interactive `drive log` or `drive meta`.** Both exist only in the provider's interactive loop.
- **No `--task-goal` flag.** The driver task goal is provider-environment-only, so a cluster command cannot supply one without smuggling it through a process environment variable.

## See also

- `conf/control-actions.conf.example` — the catalog this document describes, read by the Provider CLI through `AGENT_CLUSTER_TOPSAILAI_CONTROL_ACTIONS`
- `conf/command-allowlist.conf.example` — the separate allowlist for `command.exec`
- `docs/agent-cluster-protocol.md` — the standard operation contracts
- `docs/agent-cluster-adapters.md` — the Endpoint-private provider mapping
