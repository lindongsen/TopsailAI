# Output Format Notes

If `step_name` is `action`, the following is the content of `raw_text` in JSON:
- tool_call (str), a tool name
- tool_args (json)

Output Example:
```
topsailai.thought
I need to know the OS version.

topsailai.action
{
  "tool_args": {"cmd": "uname -a" },
  "tool_call": "cmd_tool-exec_cmd",
}
```
