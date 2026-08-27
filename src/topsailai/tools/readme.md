# AI Agent Tools

These tools will be called by the AI agent.

## Available Tools

| Module | Tool Name | Purpose |
|--------|-----------|---------|
| `cmd_tool.py` | `exec_cmd` | Execute arbitrary shell commands |
| `file_tool.py` | `read_file`, `write_file`, `append_file`, `check_files_existing`, `mkdirs`, `overwrite_lines_in_file`, `insert_content_to_file`, `list_dirs`, `read_files` | File and directory operations |
| `git_tool.py` | `exec_readonly` | Execute read-only git commands safely (disabled by default) |

## Variables & Functions

- TOOLS: required, dict, func_name=func_call
- TOOLS_INFO: optional, dict, func_name={openai_tool_spec}; -> Do not set it unless necessary!
- PROMPT: optional, str, tool prompt; -> The usage of the tool should be included in the corresponding function comments, not here!
- OBSERVATION: optional, str, content appended once to the first user observation message for enabled tools.
- FLAG_TOOL_ENABLED: optional, bool, default True
- reload(): optional, callable function to reload sth.

## Prompt vs. Function Docstring

When a tool registers a function in `TOOLS`, its function `__doc__`, module-level `PROMPT`, and module-level `OBSERVATION` serve distinct purposes:

- Put **capability overviews, catalogs, and role lists** in the module-level `PROMPT` for the system prompt.
  - Example: `subagent_tool.py` loads `{role_name}.member` role files and appends the discovered role catalog to `PROMPT`. The catalog has two parts:
    - `## Available Subagent Roles` lists the discovered role names.
    - `## Subagent Role Details` contains each role's full `{role}.member` content wrapped in a fenced code block (e.g. ```text ... ```). Wrapping prevents markdown in the role file from interfering with the main tool prompt's own markdown structure.
- Put concise tool-specific user context in `OBSERVATION`. Each enabled tool module is identified with `<observation source="tool_module">...</observation>` in the first user observation message.
- Use the function `__doc__` for **function-specific documentation**: signature, parameters, return value, and usage examples.
  - Example: `subagent_tool.py` keeps `call_assistant.__doc__` focused on the `role` parameter, explaining that a matching `{role}.member` file will prefix the message with `@{role}:` and inject the role definition into the sub-agent system prompt.
- Treat the docstring of every function registered in `TOOLS` as an LLM-facing interface contract. Every such docstring MUST have corresponding unit-test coverage. Docstrings of internal helper functions not registered in `TOOLS` do not require unit-test coverage.

Do not duplicate the same catalog or overview in both places.

## Utility Placement

Public/common methods closely related to tools in general belong in `base/`; public methods related to a specific tool belong in `{tool}_utils/`.

## Tool Parameter Types Must Assume String-Typed LLM Output

LLM response content is non-deterministic, so a tool must never assume that an argument arrives with the type it was declared with.

### Rule

Design tool parameters **string-first**. When a parameter is declared as `int`/`float`, convert it at runtime; when it is declared as `list`/`dict`, try `json.loads` first, because the LLM may well have serialized the container into a string.

### Why

- When `TOOLS_INFO` omits type information, the provider stringifies every argument before the call reaches us.
- Even with complete type information, the LLM still returns quoted numbers, values with surrounding whitespace, or JSON text for containers.
- Pushing type discrimination onto the caller means a malformed argument gets disguised as a business status, which makes the real failure invisible.

### Required practice

- Prefer `string` for parameter design; if a string can express the intent, do not use a container or numeric type.
- Numeric parameters: parse actively (strip whitespace, accept scientific notation), and always apply a **finite-value check** (reject `NaN` and `±inf`); preserve existing boundary semantics such as the meaning of `<= 0`.
- Boolean-semantics parameters: this project uses **integer (`1` = true, `0` = false)**, with `int()` applied to string input. Do not reintroduce a truthy/falsy string set (explicitly rejected by the human).
- Container parameters: attempt `json.loads` first; only treat the argument as invalid when parsing fails.
- On conversion failure, return a **machine-readable parameter-error status** (in this project: `invalid_request` plus a `reason` field). Never reuse a business/environment status such as `unavailable` for a bad argument.
- Keep the parameter-parsing path deliberately separate from the environment-variable path: env values may keep using `utils/env_tool.py::is_true()`, while parameters must not reuse that truthy set.

### Reference implementation

`tools/human_tool.py` - `TOOLS_INFO`, `_validate_request()`, `_resolve_allow_free_text()`.
See `issues/done/issue-human-decision-input-source-detection-false-negative.md` for the full decision history.

### Known deviation

`ask_decision` still rejects `options` when it is passed as a JSON string, which contradicts this principle and has not been converged yet (open item).
