---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_memory_top

Display story memories in most-recently-used order without changing their read statistics.

## Invocation

```bash
topsailai_memory_top
topsailai_memory_top --max-tokens 12000
topsailai_memory_top --max-count 10 --json
topsailai_memory_top --max-tokens 12000 --max-count 10
```

## Options

| Option | Description |
|--------|-------------|
| `--max-tokens <tokens>` | Maximum cumulative memory-content tokens. `0` means unlimited. Defaults to `TOPSAILAI_CONTEXT_MEMORY_LOAD_MAX_TOKENS`, then `0`. |
| `--max-count <count>` | Maximum number of ranked memories to print. `0` means unlimited and is the default. |
| `--json` | Print a structured object whose `memories` list preserves MRU order. |

## Output

The default output is a standard Markdown document. It starts with YAML frontmatter containing `max_tokens`, `max_count`, `current_count`, `total_count`, and `sort`, followed by the `# Top Memories` main title, a numbered `## Titles` summary in MRU order, and detailed memories under `## Memories`. JSON output remains machine-friendly and includes the same count fields and ordered `memories` list.

`max_count` is the requested output limit, `current_count` is the number of memories actually selected after token and count limits, and `total_count` is the total number of stored memories before either limit is applied.

## Ordering and Limits

The command reuses the startup memory loader. Memories are sorted by descending `last_activity_at`, descending `created_at`, and ascending `memory_id`. Memory content is read without updating read counters or activity timestamps.

The token bound is applied by the existing loader. If adding the next memory would exceed the token budget, selection stops. The count bound is then applied to the selected ordered memories.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Memories were selected and printed successfully. |
| 1 | Loading or formatting memories failed. |
| 2 | Command-line arguments are invalid. |
