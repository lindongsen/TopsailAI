# Additional notes in JSON

```
Keywords:
  step_name (str)
  raw_text (str)
  tool_call (str), specifies the tool name, used only in the action step
  tool_args (json), specifies tool parameters, used only in the action step

Output Example:
[
  {
    "step_name": "thought",
    "raw_text": "I need to know the OS version"
  },
  {
    "step_name": "action",
    "tool_args": {"cmd": "uname -a" },
    "tool_call": "cmd_tool-exec_cmd",
  }
]
```
