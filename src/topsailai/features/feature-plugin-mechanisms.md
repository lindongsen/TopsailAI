---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
references:
  - utils/module_tool.py
  - tools/base/init.py
  - tools/base/common.py
  - prompt_hub/prompt_tool.py
  - ai_base/prompt_base.py
  - workspace/plugin_instruction/base/init.py
  - workspace/agent/hooks/base/init.py
  - workspace/agent/runtime_message_sources/__init__.py
  - ai_base/llm_control/llm_mistakes/base/init.py
  - ai_base/llm_control/llm_mistakes/hook_script_runner.py
  - ai_base/llm_hooks/executor.py
  - skill_hub/skill_tool.py
  - skill_hub/skill_hook.py
  - tools/subagent_tool.py
  - ai_team/manager.py
  - ai_team/prompt.py
  - tools/memory_tool_utils/memory_hooks.py
  - hooks/
---

# Plugin and Extension Mechanisms

## Core Goal

> **A plugin exists to extend the capability of a specific component in a highly convenient way: define the appropriate file or folder configuration, and that component automatically discovers the definition and gains the extended capability.**

## Plugin, Hook, and Event Responsibilities

Plugin, Hook, and Event describe complementary dimensions rather than mutually exclusive mechanism categories:

- **Plugin extends what a component can do.** It is a capability-extension mechanism through which a component discovers and installs additional capability from an agreed file, folder, module, script, or runtime configuration.
- **Hook defines when and where additional behavior runs within an existing flow.** It is an execution-point or lifecycle-invocation mechanism that lets registered behavior intervene at a host-defined boundary, such as before an LLM request or after a final answer.
- **Event communicates what has happened so decoupled components can observe or react.** It is a fact-distribution and decoupled-coordination mechanism; stronger guarantees such as workflow ordering, transactions, or retries require contracts beyond the event itself.

The mechanisms can be composed. For example, a plugin may provide an audit capability, register it at a request-completion hook, publish audit events when that hook runs, and let independent logging and statistics consumers respond to those events. A plugin may register hooks or event consumers, and a hook may publish events, without making the three concepts equivalent.

In the current TopsailAI implementation, the `events/` subsystem primarily supports recording and observability by collecting, buffering, and persisting events through configured backends. It is not yet a full publish/subscribe business event bus, so its present role should not be overstated as general workflow coordination.

## Purpose

TopsailAI supports several forms of extensibility rather than one universal plugin protocol. Extensions may be discovered as Python modules, loaded from configured package folders, executed as external scripts, registered through a typed runtime API, or selected from a fixed internal registry.

This document identifies the implemented extension points, their contracts, placement, configuration, and lifecycle. It also distinguishes externally configurable plugins from internal composition seams so that a registry is not mistaken for a public discovery mechanism.

## Mechanism map

| Category | Extension point | Discovery or activation | Extension contract |
|---|---|---|---|
| Python module discovery | Agent tools | Scan `topsailai.tools` and configured plugin packages | Every package may export `TOOLS` and `TOOLS_INFO`; built-in modules also provide prompt metadata |
| Prompt and script configuration | Prompt providers | Read file/content inputs or execute configured commands | Text extends system, tool, environment, or summary prompts; no callable tool is registered |
| Prompt-only configuration | Extra tool descriptions | Read configured Markdown files | Markdown is added to the tool prompt; no callable is registered |
| Python module discovery | Slash instructions | Scan `workspace/plugin_instruction` and configured plugin packages | Module exports `INSTRUCTIONS` |
| Python module discovery | Agent lifecycle hooks | Scan `workspace/agent/hooks` | Module exports `HOOKS`; key prefixes select lifecycle timing |
| Python module discovery | LLM mistake handlers | Scan `ai_base/llm_control/llm_mistakes` | Module exports `MISTAKES` |
| Script discovery | Model-specific LLM mistake scripts | Rescan a model script package for each response | Importable source or extension module; JSON stdout contract |
| Folder discovery | Skills | Scan built-in, configured, and project-local skill roots | Skill folder contains `SKILL.md` or `skill.md` |
| Python module configuration | Skill lifecycle hooks | Load configured external packages | Module exports `HOOKS` with before/after suffixes |
| Folder discovery | Subagent and AI-team roles | Scan configured folders for `*.member` and related files | Member files supply role content; companion files supply abilities and values |
| Import-path configuration | LLM request/response hooks | Import configured `hook_execute` functions | Function transforms and returns the current content |
| Script configuration | Post-final-answer hooks | Execute configured scripts | Final answer is provided through the child environment |
| Programmatic and script configuration | Memory write hooks | Register callables or configure scripts | Create/update event contract; failures are isolated from the write path |
| Programmatic registration | Standalone hook framework | Register event definitions and bindings on `HookRuntime` | `module:function` handler receives `HookContext` in an isolated child process |
| Registry configuration | Agent2LLM runtime message sources | Select a registered source type | Class implements `Agent2LLMMessageSource` |
| Internal Python discovery | Chat history managers | Scan `context/chat_history_manager` | Module exports `MANAGERS`; environment selects registered classes |
| Internal Python discovery | Control-channel handlers | Inspect modules in `workspace/control_handlers` | Concrete `ControlHandler` subclass |
| Closed internal registries | LLM providers and event backends | Resolve a fixed registered name | Provider/backend interface; adding a name currently requires core wiring |

## Shared Python module discovery

`utils/module_tool.py` provides the common discovery implementation used by tools, instructions, agent hooks, mistake handlers, and chat history managers.

`get_function_map()` performs these steps:

- Imports a Python package.
- Uses `pkgutil.iter_modules()` on the package path.
- Considers direct non-package child modules whose names do not start with `__`.
- Imports modules in lexicographic order.
- Reads a named module-level registry such as `TOOLS`, `HOOKS`, or `MISTAKES`.
- Merges dictionary, list, set, or tuple entries into one namespaced mapping.

Discovery uses the Python import system rather than filtering only `.py` directory entries. Importable compiled extension modules are therefore discoverable. Child packages are not recursively scanned by this loader.

`get_external_function_map()` accepts a Python package path or a filesystem path that can be converted into an importable package. When needed, it adds the package parent to `sys.path`, then delegates to the same direct-module discovery behavior. An external plugin folder must consequently be structured as an importable Python package, including package initializers where required by the import layout.

Registry key collisions use normal dictionary update behavior at the merge point. Plugin authors should use stable, unique module and exported function names.

## Agent tool modules

### Built-in discovery

`tools/base/init.py` scans direct modules under `topsailai.tools`. A tool module exposes callable entries through `TOOLS`:

```python

def inspect_item(item_id: str):
    """Inspect one item by its identifier."""
    ...


TOOLS = {
    "inspect_item": inspect_item,
}
```

With the default connection character `-`, a module named `example_tool` produces the public tool name `example_tool-inspect_item`.

A discovered tool module may expose:

| Export | Scope | Purpose |
|---|---|---|
| `TOOLS` | Built-in and external packages | Required mapping of local tool names to callables |
| `TOOLS_INFO` | Built-in and external packages | Optional provider-facing function schemas; ordinary tools derive schemas from docstrings |
| `PROMPT` | Built-in `topsailai.tools` modules | Module-level capability overview added to the system tool prompt |
| `OBSERVATION` | Built-in `topsailai.tools` modules | One-time or runtime context added as a user observation |
| `FLAG_TOOL_ENABLED` | Built-in `topsailai.tools` modules | Default module enablement flag |
| `reload()` | Built-in `topsailai.tools` modules | Optional prompt/context refresh callback |

External packages are discovered for callable and schema registries only. Prompt metadata is resolved by importing `topsailai.tools.<module>`, so an arbitrary external package's `PROMPT`, `OBSERVATION`, `FLAG_TOOL_ENABLED`, or `reload()` export is not automatically consumed.

Each registered callable's docstring is an LLM-facing function contract. It should describe parameters and behavior concisely and must tolerate the project's string-first tool-argument behavior.

### External tool packages

`TOPSAILAI_PLUGIN_TOOLS` is a semicolon-separated list of importable package paths or package folders. Each package is scanned for direct child modules exporting `TOOLS` and optionally `TOOLS_INFO`.

Example layout:

```text
example_plugins/
  __init__.py
  inventory_tool.py
```

`inventory_tool.py` exports `TOOLS`; configuring the package folder adds its namespaced callables to the global tool map during tool-base initialization.

`TOPSAILAI_TOOL_CONN_CHAR` controls the one-character separator used in generated tool names. `TOPSAILAI_ENABLED_TOOLS` and `TOPSAILAI_DISABLED_TOOLS` filter both built-in and external modules. The enabled list supports `*` and `+`; module-name and prefix matching are also supported. A built-in module with `FLAG_TOOL_ENABLED = False` remains disabled unless explicitly selected.

The legacy aliases `PLUGIN_TOOLS`, `ENABLED_TOOLS`, and `DISABLED_TOOLS` remain fallback inputs when their `TOPSAILAI_*` counterpart is empty.

### Prompt-only extra tools

`TOPSAILAI_EXTRA_TOOLS` is different from `TOPSAILAI_PLUGIN_TOOLS`. It is a semicolon-separated list of Markdown files read by `prompt_hub/prompt_tool.py` and appended between `Extra Tools` markers in the prompt.

This mechanism advertises externally available tools to the model but does not register a Python callable. A separate execution integration must exist for any advertised name. The legacy `EXTRA_TOOLS` variable is a fallback.

### Programmatic tool registration

`tools/base/common.py::add_tool()` can add a callable to the process-global tool map before an agent instance is created. `AgentToolManager.add_tools_by_module()` can also load a particular module's `TOOLS` mapping into one agent. These are programmatic composition seams, not directory plugins.

## Prompt providers and composition

Prompt content can be extended without creating a tool or hook package. `SYSTEM_PROMPT` accepts a file path or raw content, while `SYSTEM_PROMPT_EXTRA_FILES` accepts comma-separated prompt files that `prompt_hub/prompt_tool.py` resolves and appends. `ENV_PROMPT` similarly appends file content or raw text to the generated environment prompt.

`TOPSAILAI_OBTAIN_SYSTEM_PROMPT_SCRIPT` and `TOPSAILAI_OBTAIN_TOOL_PROMPT_SCRIPT` provide script-backed prompt providers. During `PromptBase` construction, each non-empty configured command is executed with a 60-second timeout. Successful, non-empty stdout is appended to the corresponding system or tool prompt; an empty value, failure, or empty stdout contributes nothing.

Example configuration shape:

```text
TOPSAILAI_OBTAIN_SYSTEM_PROMPT_SCRIPT=/trusted/path/render-system-prompt
TOPSAILAI_OBTAIN_TOOL_PROMPT_SCRIPT=/trusted/path/render-tool-prompt
```

Summary behavior has separate content-oriented extension inputs: `TOPSAILAI_SUMMARY_PROMPT` supplies the main summary prompt, and `TOPSAILAI_SUMMARY_PROMPT_EXTRA_MAP` maps agent types to additional prompt files. These mechanisms extend instructions and context, not executable registries.

Prompt scripts execute during prompt-manager construction, whereas file/content sources are read by their owning prompt composition path. All configured files and commands are trusted inputs because they can change model behavior, and prompt-provider commands execute with the host process's authority.

## Slash-instruction plugins

`workspace/plugin_instruction/base/init.py` scans direct modules in `topsailai.workspace.plugin_instruction`. Each module exports an `INSTRUCTIONS` mapping:

```python

def status(args: str = ""):
    ...


INSTRUCTIONS = {
    "status": status,
}
```

Built-in keys are namespaced as `module.action`; for example, an action in `env.py` becomes an `/env.*` instruction. `HookInstruction` receives the merged mapping and dispatches user messages beginning with `/`.

`TOPSAILAI_PLUGIN_INSTRUCTIONS` accepts semicolon-separated external package paths. Each package is scanned through `get_external_function_map()` for direct child modules exporting `INSTRUCTIONS`, and those entries are merged after built-ins. Expansion occurs when the instruction registry module is initialized, so configuration must be present before that import.

## Agent lifecycle hook modules

`workspace/agent/hooks/base/init.py` scans `workspace/agent/hooks` for `HOOKS` mappings. `AgentChatBase` groups discovered functions by registry-key prefix:

| Key prefix | Lifecycle list |
|---|---|
| `pre_run` | Runs before the User2Agent conversation loop begins |
| `post_final_answer` | Runs after a final answer path |
| `post_succ_run` | Runs after a successful run |
| `post_fail_run` | Runs after a failed run |

Example:

```python

def pre_run_prepare(agent_chat):
    ...


HOOKS = {
    "pre_run_prepare": pre_run_prepare,
}
```

Functions are called in deterministic registry-key order. This mechanism currently discovers only modules inside the built-in `workspace/agent/hooks` package; it has no separate external agent-hook package environment variable.

One built-in post-final hook bridges to configured scripts through `TOPSAILAI_HOOK_SCRIPTS_POST_FINAL_ANSWER`. Each entry has the form:

```text
/path/to/executable timeout=30 env_keys=EXTRA_KEY
```

Entries are separated by semicolons and execute sequentially. Standard session/task identifiers are passed, configured `env_keys` may add selected variables, and `TOPSAILAI_FINAL_ANSWER` contains the serialized final message. Script failures are logged and retained in the result mapping rather than stopping the remaining scripts.

## LLM transformation hooks

`ai_base/llm_hooks/executor.py` implements ordered content-transformation chains. Every configured module path must expose:

```python

def hook_execute(content):
    ...
    return content
```

The return value from one hook becomes the input to the next hook.

| Configuration | Boundary | Default behavior |
|---|---|---|
| `TOPSAILAI_HOOK_BEFORE_LLM_CHAT` | Message list before an LLM request | When unset, built-ins normalize system messages and tool-call pairing |
| `TOPSAILAI_HOOK_AFTER_LLM_CHAT` | Raw chat content after provider chat | Model/content-specific built-ins may be selected when unset |
| `TOPSAILAI_HOOK_AFTER_LLM_RESPONSE` | Raw response content before response formatting | Default memory-reference scan hook is configured by the environment template/documentation |

Explicitly configuring a hook chain replaces runtime defaults for that key rather than appending to them. In particular, replacing `TOPSAILAI_HOOK_BEFORE_LLM_CHAT` also removes the default tool-call pairing sanitizer unless the configured chain includes equivalent handling.

These hooks execute in process and may transform trusted request or response data. They should remain small, deterministic, and failure-aware.

## LLM mistake extensions

### In-process mistake handlers

`ai_base/llm_control/llm_mistakes/base/init.py` scans direct modules under `llm_mistakes` for a `MISTAKES` mapping. A handler accepts the current response and optional context:

```python

def repair_response(message, **kwargs):
    ...
    return repaired_message_or_none


MISTAKES = {
    "repair_response": repair_response,
}
```

Handlers run in sorted registry-key order. Returning `None` or the same object means no change. The first handler that returns a distinct truthy repair wins, after which mistake processing stops. These modules are loaded through normal Python module discovery at initialization.

### Model-specific mistake scripts

Models may additionally own a hook-script package such as `ai_base/llm_control/llm_mistakes/deepseek_hook_scripts/`. The package is rescanned through `pkgutil.iter_modules()` for every applicable response, so eligible scripts added, removed, or changed can take effect without restarting the agent.

Eligible handlers are importable Python source or compiled extension modules whose names do not start with `_`. Packages and unsupported artifacts are skipped. Lexicographic module-name order controls precedence; a `pNNN_` prefix is the established way to express priority.

Each handler runs in an independent subprocess with a finite timeout and bounded stdout:

- Source handlers execute as scripts and may use an `__main__` block.
- Compiled handlers are imported by module name and expose `main()`.
- Empty stdout means “not handled.”
- Valid JSON matching the agent step schema means success and stops the chain.
- Invalid JSON, oversized output, timeout, or process failure is logged and the next handler is attempted.

The child receives a curated environment containing the model, response or response-file path, script path, and script directory. Relevant limits are configured with `TOPSAILAI_LLM_MISTAKE_SCRIPT_TIMEOUT`, `TOPSAILAI_LLM_MISTAKE_RESPONSE_MAX_ENV`, `TOPSAILAI_LLM_MISTAKE_RESPONSE_MAX_FILE`, and `TOPSAILAI_LLM_MISTAKE_OUTPUT_MAX`.

Unlike generic module plugins, model-specific script folders are wired by the owning model handler. Creating a new arbitrary folder alone does not activate it; the model handler must resolve and call that package.

## Skill folder plugins

### Discovery roots

`skill_hub/skill_tool.py` loads skills from:

- The built-in `skills/` folder.
- Semicolon-separated roots in `TOPSAILAI_PLUGIN_SKILLS`.
- `.topsailai/skills` beneath `TOPSAILAI_PROJECT_WORKSPACE` and `TOPSAILAI_PWD` when present.
- A folder supplied directly to the runtime `load_skill()` operation.

A skill folder contains `SKILL.md` or `skill.md`. The loader parses its metadata and prompt-facing description, caches the resulting `SkillInfo`, and rejects conflicting duplicate folder basenames when their skill documents differ.

If a configured root is not itself a skill, subfolders are searched up to `TOPSAILAI_SEARCH_SKILLS_MAX_DEPTH`. A typical skill may include:

```text
example-skill/
  SKILL.md
  scripts/
  references/
  assets/
  config/
```

Only the skill document is required by discovery. Scripts are not executed merely because they exist; the skill document and callable skill tool must identify the exact runnable artifact.

### Runtime controls

| Configuration | Effect |
|---|---|
| `TOPSAILAI_DISABLED_SKILLS` | Excludes exact names, folder matches/prefixes, or all skills with `*` |
| `TOPSAILAI_LOAD_OVERVIEW_INTO_PROMPT_SKILLS` | Loads full overview content for selected skills; supports `*`, path, prefix, or folder-basename matching |
| `TOPSAILAI_SEARCH_SKILLS_MAX_DEPTH` | Bounds recursive root scanning |
| `TOPSAILAI_SESSION_LOCK_ON_SKILLS` | Requires session locking for matched skill paths |
| `TOPSAILAI_SESSION_REFRESH_ON_SKILLS` | Refreshes session state for matched skill paths |
| `TOPSAILAI_CALL_SKILL_TIMEOUT_MAP` | Assigns execution timeouts by matching skill folder key |

`load_skill()` adds the folder to the current process's `TOPSAILAI_PLUGIN_SKILLS` value and cache. `unload_skill()` removes it from both. These operations change current process state; they do not edit persistent environment configuration.

## Skill lifecycle hooks

`TOPSAILAI_HOOK_MODULE_SKILLS` configures external importable packages scanned for `HOOKS` mappings. `SkillHookHandler` invokes entries whose names end with:

- `handle_before_call_skill`
- `handle_after_call_skill`

Each function receives the `SkillHookHandler`, which exposes the skill folder, command list, session-lock decision, session-refresh decision, and refresh data. Exceptions from one hook are logged and do not stop other matching hooks.

The loaded hook map is cached in process-global state after the first non-empty load. Configure the package list before the first skill call.

## Role and team folder extensions

### Subagent role catalog

`TOPSAILAI_SUBAGENT_ROLE_FOLDER` selects a folder of `*.member` role definitions and defaults to `{TOPSAILAI_HOME}/subagents`. `tools/subagent_tool.py` scans only direct files whose names contain no additional dot before `.member`, sorts them by filename, and reads non-empty content into the subagent role catalog.

For example, `reviewer.member` creates the selectable role name `reviewer`. Its content is displayed in the subagent tool prompt and appended to the delegated subagent's system prompt when that role is requested. `TOPSAILAI_SUBAGENT_SYSTEM_PROMPT` and `TOPSAILAI_SUBAGENT_TOOL_PROMPT` add file-or-content prompt fragments around this mechanism.

The role folder is resolved and scanned when `tools.subagent_tool` is imported. Role-file changes therefore normally require a new process or module reload; this is folder discovery, not a per-call rescan.

### AI-team member catalog

`TOPSAILAI_TEAM_PATH` selects the AI-team definition folder. `ai_team/manager.py` reads each direct `*.member` file as one member definition and derives the member ID from its filename. A same-basename `.chat` or `.agent` file advertises the corresponding execution ability. A same-basename `.values` file is appended to that member's role prompt, while `team.values` contributes shared team-wide values.

Example layout:

```text
team/
  reviewer.member
  reviewer.agent
  reviewer.values
  team.values
```

`TOPSAILAI_TEAM_PROMPT` supplies the shared team prompt as file content or raw text, and `SYSTEM_PROMPT` remains the base prompt input. The manager builds the member inventory when composing the team prompt. These files extend role definitions and available team executors; they do not register ordinary agent tools.

## Memory write extensions

Memory create and update operations support three parallel extension forms in `tools/memory_tool_utils/memory_hooks.py`.

### Programmatic callables

`register_create_hook()` and `register_update_hook()` add in-process callbacks in registration order. Matching unregister functions remove them. A callback receives the memory event dictionary. Individual callback failures are logged and represented as `None` without aborting other hooks.

### Legacy script hooks

`TOPSAILAI_HOOK_SCRIPTS_MEMORY_WRITE` uses the shared semicolon-separated script syntax. Scripts run after a successful create or update and receive the event fields through selected environment data. This path remains for compatibility.

### Event-keyed synchronization scripts

`TOPSAILAI_MEMORY_SYNC_HOOKS` is a JSON object keyed by `create` and `update`. Each value is a list of bindings with:

- `script`: executable path
- `timeout`: positive integer, default `300`
- `enabled`: optional boolean
- `env_keys`: optional list of environment names to forward

The script receives a stable JSON object on stdin containing `schema_version`, `event`, memory identity, title, content, file, workspace, timestamp, and version. Unknown events, malformed bindings, failures, and non-zero exits are logged without converting a successful memory write into failure. Delete operations are not supported by this hook contract.

## Standalone unified hook framework

The `hooks/` package is an implemented foundational plugin framework with explicit programmatic registration. It is independent from the older specialized tool, skill, memory, LLM, and agent-hook mechanisms; those mechanisms are not automatically migrated into it.

A caller creates `HookRuntime`, opens a scope, registers an `EventDefinition` and `Binding`, then publishes through `emit()`, `dispatch()`, or `adispatch()`. A binding identifies a handler with `module:function` syntax:

```text
example_plugin.audit:on_event
```

The callable receives a detached `HookContext` and returns a JSON-compatible value synchronously or asynchronously. Handlers are imported and executed in managed child processes, not inline in the host. The framework provides:

- Exact event-name and major-version matching.
- Immutable registry generations and scope-owned registrations.
- Priority and dependency ordering.
- Finite queue, payload, worker, handler, dispatch, and shutdown limits.
- Structured outcomes for import errors, handler errors, timeouts, invalid output, capacity rejection, cancellation, and dependency skips.
- Bounded process termination and cleanup-debt reporting.

`HookSettings.from_mapping()` accepts explicit typed configuration; it does not read environment variables. The framework does not crawl plugin directories or auto-load package entry points. The host application must explicitly register definitions and bindings, and no current `TOPSAILAI_HOOK_*` variable configures this generic runtime.

This is the preferred foundation when a new extension requires isolated execution, bounded resource use, deterministic dependency ordering, and structured outcomes. It is not a substitute for required authentication, validation, persistence, cleanup, or other authoritative application control flow.

## Agent2LLM runtime message-source registry

`workspace/agent/runtime_message_sources` defines a small source registry. `TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_SOURCE` selects the registered type, and `TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_ENABLED` gates installation during the agent pre-run hook.

The only registered implementation is currently `file`. It reads JSONL from `TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_FILE` or a session-scoped default file, clears consumed input, and injects valid records as Agent2LLM user observations before an LLM call.

To add a source type in code:

- Implement `Agent2LLMMessageSource`.
- Add the class to `workspace/agent/runtime_message_sources.REGISTRY` under a unique type name.
- Extend the pre-run configuration assembly when the constructor needs settings other than `file_path`.

This is extension-ready but not an external auto-discovery plugin: setting an unknown type does not import a package and leaves the source unset.

## Internal discovery and composition seams

### Chat history managers

`context/chat_history_manager/__init__.py` scans direct package modules for `MANAGERS` mappings. `CONTEXT_HISTORY_MANAGERS` then selects registered classes with entries such as:

```text
sql.ChatHistorySQLAlchemy conn=sqlite:///memory.db;
```

The environment can select and parameterize discovered managers but cannot point to an arbitrary external package. Adding a manager currently means adding a module under the core package or changing the registry wiring. Session storage still uses `SessionSQLAlchemy` derived from the selected manager connection; this is not a general external session-backend plugin.

### Control-channel handlers

`workspace/control_handlers/__init__.py` scans direct modules, imports them independently, and registers every concrete `ControlHandler` subclass. A broken module is skipped without suppressing later valid handlers. This is an internal auto-discovery mechanism only; there is no external handler-path configuration.

### LLM provider registry

`ai_base/llm_pool/provider_registry.py` defines `LLMProviderBackend` and `LLMProviderRegistry`. A backend supplies client configuration, acquisition, invalidation, chat-model access, response adaptation, and model/API resolution functions. Providers are lazily imported on first resolution.

The current provider-to-module map contains only `openai`, and no environment variable or package scan extends that map. Tests and callers may inject a different registry into `LLMModel`, but production provider expansion currently requires core registration and module-map changes.

### Event backend adapters

`events.backends.EventBackend` defines `write()`, `close()`, and `cleanup()`. `TOPSAILAI_EVENTS_BACKEND` selects the fixed names `file`, `db`, or `webhook`; unknown values fall back to `file`.

Only the file backend is operational. Database and webhook adapters are placeholders whose `write()` methods raise `NotImplementedError`. The backend factory does not dynamically import external implementations, so this is an adapter seam rather than a public plugin loader.

### Tool approval, multimodal, model pools, and sandbox settings

These areas are configurable or replaceable in code but are not independently discovered plugin systems:

- Tool approval loads policy rules and tracks pending requests; rules configure decisions but do not load executable plugin code.
- Multimodal classes share the LLM hook chain but do not scan multimodal provider plugins.
- LLM client pools are selected through the closed provider registry described above.
- `TOPSAILAI_SANDBOX_SETTINGS` creates configured SSH or Docker targets; it is runtime data, not a sandbox-driver plugin registry.
- The user model registry and `TOPSAILAI_MODEL_SETTINGS` add model configurations, not new provider implementations.

## Load timing and runtime behavior

| Mechanism | Typical load timing | Hot change behavior |
|---|---|---|
| Built-in/external tools | Import of `tools.base` | Restart or explicit module reload is normally required |
| Prompt providers | Owning prompt composition or `PromptBase` construction | Updated content is seen by subsequently constructed or composed prompts |
| Slash instructions | Import of instruction registry | Restart is normally required |
| Agent hooks | Import of agent-hook registry | Restart is normally required |
| In-process mistake handlers | Import of mistake registry | Restart is normally required |
| Model mistake scripts | Every applicable response | Added/removed/changed scripts are seen on the next scan |
| Skills | Prompt construction or explicit load | `load_skill()` and `unload_skill()` update current process cache/state |
| Skill hooks | First non-empty hook load | Later environment changes are not automatically reloaded |
| Subagent roles | Import of `tools.subagent_tool` | Restart or module reload is normally required |
| AI-team members | Team inventory and prompt construction | Folder contents are read when a new team composition is built |
| LLM transform hooks | Hook execution | Environment-selected module paths are read at call time |
| Post-final scripts | Final-answer hook execution | Script configuration is read at call time |
| Memory sync scripts | Successful create/update | JSON configuration is read at call time |
| Generic `HookRuntime` | Explicit host construction/registration | New registry generations apply to future admissions |
| Agent2LLM source | Conversation pre-run setup | Source remains for the owning conversation lifecycle |

## Failure and trust boundaries

Plugin mechanisms have different isolation guarantees:

- Tools, slash instructions, agent hooks, skill hooks, LLM transformation hooks, in-process mistake handlers, and memory callback hooks execute in the host process. They are trusted code and can affect host state.
- Generic hook-framework handlers and model mistake scripts execute in managed child processes with bounded protocols and deadlines.
- Prompt-provider, post-final, and memory scripts execute as external commands with configured timeouts, but the generic script utility does not provide the full dependency graph and structured outcome model of `HookRuntime`.
- Skill documents contribute prompt instructions. Skill scripts execute only through an explicit skill call and should be treated as trusted executable content.
- Prompt, extra-tool, role, member, and values files can influence model behavior even when they register no executable callable.
- AI-team `.chat` and `.agent` companion files identify executable integrations and must come from a trusted team folder.

External package paths and scripts must therefore come from trusted configuration. Process isolation limits host control-flow damage but is not a security sandbox for same-user filesystem or network access.

## Choosing an extension mechanism

Use the narrowest mechanism matching the requirement:

| Requirement | Preferred mechanism |
|---|---|
| Add an agent-callable Python function | External tool package through `TOPSAILAI_PLUGIN_TOOLS` |
| Advertise a tool implemented outside this process | Prompt-only file through `TOPSAILAI_EXTRA_TOOLS`, paired with a real executor |
| Add prompt content from files, text, or generated stdout | Prompt composition inputs or `TOPSAILAI_OBTAIN_*_PROMPT_SCRIPT` |
| Add a user-facing `/` command | Instruction package through `TOPSAILAI_PLUGIN_INSTRUCTIONS` |
| Add reusable agent guidance and scripts | Skill folder through `TOPSAILAI_PLUGIN_SKILLS` |
| Add selectable subagent roles | `*.member` files under `TOPSAILAI_SUBAGENT_ROLE_FOLDER` |
| Define an AI team and member executors | Member and companion files under `TOPSAILAI_TEAM_PATH` |
| Normalize messages or raw model output inline | LLM `hook_execute` chain |
| Repair one known parsed-response pattern | In-process `MISTAKES` handler |
| Repair model output without restarting | Model-specific mistake script package |
| Observe skill execution | Skill lifecycle hook package |
| Notify an external system after final output | Post-final script hook |
| Synchronize successful memory writes | `TOPSAILAI_MEMORY_SYNC_HOOKS` |
| Run optional event handlers with strong failure isolation | Standalone `HookRuntime` |
| Add another runtime message transport | Register an `Agent2LLMMessageSource` implementation in code |

Do not use optional plugins to replace required validation, authorization, persistence, cleanup, retry classification, or lifecycle ownership. Those responsibilities remain in the component that owns the business operation.
