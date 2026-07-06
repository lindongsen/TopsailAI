# AI Agent Tools

These tools will be called by the AI agent.

## Variables & Functions

- TOOLS: required, dict, func_name=func_call
- TOOLS_INFO: optional, dict, func_name={openai_tool_spec}; -> Do not set it unless necessary!
- PROMPT: optional, str, tool prompt; -> The usage of the tool should be included in the corresponding function comments, not here!
- FLAG_TOOL_ENABLED: optional, bool, default True
- reload(): optional, callable function to reload sth.
