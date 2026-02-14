# Output Format Notes

If `step_name` is `action`, the following is the content of `raw_text` in JSON:
- tool_call (str), a tool name
- tool_args (json)

Output Example:
```
topsailai.thought
I need do sth.

topsailai.action
{
  "tool_args": {},
  "tool_call": "",
}
```
