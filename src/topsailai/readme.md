---
programming_language: python
workspace: /root/ai/TopsailAI/src/topsailai
reviewer: km-k25
developer: mm-m25
---

# Topsailai Agent

AI-Agent Core, Agent Workers

## Logical Components

1. Common Utils
2. Agent Core       -> Agent Enginering Framework
3. Agent Workers    -> Worker Entry

Folder details can be got from `test.md`

## Logs that need attention

How to retrieve log:
```
LogFile: `/topsailai/log/chat.log`
Use command `topsailai_check_log` to review log content.
Use command `grep -C 10 "{time}" {LogFile}` to print NUM lines of output context for log
```

H3 title format: `LOG_ATTENTION: {content}`

### LOG_ATTENTION: "[0-9] CRITICAL -"

Some critical logs

### LOG_ATTENTION: "[0-9]\- LLM mistake: give final due to duplicate to"

- LLM Lazy execution
- LLM Make mistake in the final

### LOG_ATTENTION: "[0-9]\- LLM mistake: invalid json string"

LLM output unexpected content

### LOG_ATTENTION: '"raw_text": "missing tool_call"'

- LLM make mistake
- MAX_TOKENS is too small
