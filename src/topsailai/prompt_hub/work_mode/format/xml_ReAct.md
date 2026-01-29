# Output Format Notes

If `step_name` is `action`, the following is the content of `raw_text` in JSON:
- tool_call (str), a tool name
- tool_args (json)

## Example
```
<thought>
hello
</thought>

<action>
{"tool_call": "cmd_tool-exec_cmd", "tool_args": {"cmd": "echo ok"}}
</action>
```
