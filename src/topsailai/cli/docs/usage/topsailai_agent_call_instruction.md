---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_agent_call_instruction

Generate an instruction message for an agent to call a tool.

## Purpose

Builds a structured instruction that tells an agent how to invoke a specific tool with the given arguments. The output is formatted as a `step_name`/`raw_text` message pair suitable for injecting into a session.

## Invocation

```bash
./topsailai_agent_call_instruction.py --tool <tool_name> --args <json_args>
```

Because the script is registered in `../bin/` as `topsailai_agent_call_instruction`, you can also run it as:

```bash
topsailai_agent_call_instruction --tool cmd_tool-exec_cmd --args '{"cmd":"echo hi"}'
```

## Options

| Option | Description |
|--------|-------------|
| `--tool <name>` | Required. Name of the tool to call. |
| `--args <json>` | Required. Tool arguments as a JSON object. |
| `--session-id <id>` | Optional session ID to include in the instruction envelope. |
| `--output-format <format>` | Output format: `json` or `text` (default: `text`). |

## Output

In `text` mode, prints the instruction in the standard `step_name`/`raw_text` format. In `json` mode, prints a JSON object containing `step_name` and `raw_text`.

## Examples

```bash
# Generate a tool-call instruction
topsailai_agent_call_instruction --tool cmd_tool-exec_cmd --args '{"cmd":"echo hello"}'

# JSON output
topsailai_agent_call_instruction --tool cmd_tool-exec_cmd --args '{"cmd":"echo hello"}' --output-format json

# Include a session ID
topsailai_agent_call_instruction --tool cmd_tool-exec_cmd --args '{"cmd":"echo hello"}' --session-id my-session
```

## Notes

- `--args` must be valid JSON.
- The generated instruction can be piped into `topsailai_session_add_agent2llm_message` to make a running agent execute the tool call.
