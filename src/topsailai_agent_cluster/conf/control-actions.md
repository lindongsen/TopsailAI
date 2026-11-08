---
maintainer: AI
author: DawsonLin
---

# Provider control actions and instructions

This document is the reference for the catalog in `conf/control-actions.conf.example`. It records what the TopsailAI provider actually serves, so an operator can decide which entries to enable without reading provider source.

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
| `permission` | The operator scope required. One entry carries one scope, so every instruction reachable through `call_instruction` shares that scope |
| `payload_schema` | What the guided prompt asks. An enum becomes a numbered menu, so an unsupported value cannot be typed |
| `command` | The provider argv template, with `{session}` and `{payload}` placeholders |

Two consequences are worth stating plainly.

- **One entry means one permission.** `call_instruction` reaches read-only instructions such as `ctx.history` and mutating ones such as `ctx.clear` under a single scope. A site that needs to separate them must declare several catalog entries that share the same `command` but carry different `payload_schema` enums and different `permission` values. The catalog supports that; the shipped example keeps one entry for simplicity.
- **The enum is a prompt, not a gate.** The provider validates the instruction name against its live registry. A name absent from the enum can still be submitted by a caller that builds the payload itself, so the enum must not be mistaken for an allowlist.

## Shortcuts

A shortcut is a second name for an action that already exists in the catalog. It
exists so a frequent action can be typed quickly: with the shipped entries an
operator types `ctl.session.messages` instead of `ctl.get_session_messages`, and
the dotted spelling skips the action menu entirely.

A shortcut declares only two fields.

```json
{"name": "session.messages", "alias_of": "get_session_messages"}
```

Everything else is inherited from the action it names: the permission, the payload
schema, the payload selector field and the provider argv. A shortcut therefore
cannot widen what an operator may do, cannot advertise a different schema, and
cannot run a different command.

Rules enforced at load time:

- `alias_of` must name a real action declared anywhere in the file, so a forward
  reference is allowed and file order does not matter.
- A shortcut may not name itself.
- A shortcut may not name another shortcut. One indirection is enough for a typing
  shortcut, and a chain would make the effective permission depend on resolution
  order.
- A shortcut may not declare `permission`, `command`, `payload_schema` or
  `payload_session_field`. Declaring one is an error rather than a silent no-op,
  because an operator who wrote it would otherwise believe it took effect.
- A name may appear only once, whether it is a real action or a shortcut.

A shortcut is resolved into a full copy at load time, so execution never follows a
second lookup and a reload cannot leave a shortcut pointing at a stale definition.
Retiring the target retires the shortcut with it, because the file is validated as
a whole.

The shipped catalog carries ten shortcuts: `session.messages`,
`session.runtime_messages`, `session.heartbeat`, `session.pause`,
`session.unpause`, `session.interrupt`, `session.soft_interrupt`,
`session.clear_interrupt`, `session.instruction` and `session.llm`. The list is a
starting point, not a fixed set; nothing about a shortcut is compiled in.

## Provider gaps this catalog cannot close

These are provider-side limitations. The catalog documents them rather than working around them.

- **No structured instruction catalog.** The provider exposes instruction names and docstrings through `/help`, but no machine-readable signature document. The catalog's enum is therefore a hand-maintained snapshot.
- **No multi-handler disclosure.** `call_instruction` returns only the last result when a name has several handlers, and reports nothing about the others.
- **No `llm_control` operation enumeration.** The accepted operation is hardcoded, so the catalog states it as a one-value enum.
- **No non-interactive `drive log` or `drive meta`.** Both exist only in the provider's interactive loop.
- **No `--task-goal` flag.** The driver task goal is provider-environment-only, so a cluster command cannot supply one without smuggling it through a process environment variable.

## See also

- `conf/control-actions.conf.example` — the catalog this document describes
- `conf/command-allowlist.conf.example` — the separate allowlist for `command.exec`
- `docs/agent-cluster-protocol.md` — the standard operation contracts
- `docs/agent-cluster-adapters.md` — the Endpoint-private provider mapping
