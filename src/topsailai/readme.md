---
workspace: /root/ai/TopsailAI/src/topsailai
---

# Topsailai Agent

AI-Agent Core, Agent Workers

## Logical Components

1. Common Utils
2. Agent Core
3. Agent Workers

Folder details can be got from `test.md`

## Logs that need attention

LogFile: `/topsailai/log/chat.log`

H3 title format: `LOG_ATTENTION: {content}`

Use command `topsailai_check_log` to review log content.

### LOG_ATTENTION: " CRITICAL -"

Some critical logs

### LOG_ATTENTION: give final due to duplicate to

- LLM Lazy execution
- LLM Make mistake in the final
