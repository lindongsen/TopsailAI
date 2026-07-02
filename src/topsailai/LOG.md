# TopsailAI Log

## Logs that need attention

How to retrieve log:
```
LogFile: `{TOPSAILAI_HOME}/log/chat.log`, TOPSAILAI_HOME is environment variable, default is `~/.topsailai`
Use command `topsailai_check_log` to review log content.
Use command `grep -C 10 "{time}" {LogFile}` to print NUM lines of output context for log
```

H3 title format: `LOG_ATTENTION: {content}` -> DONOT CHANGE THE FORMAT, REFER TO BIN FILE `topsailai_check_log`!

### LOG_ATTENTION: "[0-9] CRITICAL -"

Some critical logs

### LOG_ATTENTION: "[0-9]\- LLM Mistake: give final due to duplicate to"

- LLM Lazy execution
- LLM Make mistake in the final

### LOG_ATTENTION: "[0-9]\- LLM Mistake: invalid json string"

LLM output unexpected content

### LOG_ATTENTION: "[0-9]\- LLM Service:"

LLM service errors

### LOG_ATTENTION: '"raw_text": "missing tool_call"'

- LLM make mistake
- MAX_TOKENS is too small

### LOG_ATTENTION: "[0-9]\- Heavy Task Trigger"

Task execution time is too long

