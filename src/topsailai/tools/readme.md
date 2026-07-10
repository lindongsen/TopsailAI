# AI Agent Tools

These tools will be called by the AI agent.

## Variables & Functions

- TOOLS: required, dict, func_name=func_call
- TOOLS_INFO: optional, dict, func_name={openai_tool_spec}; -> Do not set it unless necessary!
- PROMPT: optional, str, tool prompt; -> The usage of the tool should be included in the corresponding function comments, not here!
- FLAG_TOOL_ENABLED: optional, bool, default True
- reload(): optional, callable function to reload sth.

## Prompt vs. Function Docstring

When a tool registers a function in `TOOLS`, both the function's `__doc__` and the module-level `PROMPT` can become part of the system prompt shown to the main agent. To avoid redundancy and keep the prompt focused:

- Put **capability overviews, catalogs, and role lists** in the module-level `PROMPT`.
  - Example: `subagent_tool.py` loads `{role_name}.member` role files and appends the discovered role catalog to `PROMPT`. The catalog has two parts:
    - `## Available Subagent Roles` lists the discovered role names.
    - `## Subagent Role Details` contains each role's full `{role}.member` content wrapped in a fenced code block (e.g. ```text ... ```). Wrapping prevents markdown in the role file from interfering with the main tool prompt's own markdown structure.
- Use the function `__doc__` for **function-specific documentation**: signature, parameters, return value, and usage examples.
  - Example: `subagent_tool.py` keeps `call_assistant.__doc__` focused on the `role` parameter, explaining that a matching `{role}.member` file will prefix the message with `@{role}:` and inject the role definition into the sub-agent system prompt.

Do not duplicate the same catalog or overview in both places.
