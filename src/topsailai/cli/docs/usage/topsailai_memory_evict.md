---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_memory_evict

Preview synchronized story memories that would be evicted by a retention limit.

## Purpose

Runs the memory-stat eviction engine in dry-run mode and reports the healthy synchronized memory/stat pairs that exceed an explicit maximum count. The command never deletes files. Unsynced memories remain protected.

## Invocation

```bash
topsailai_memory_evict --max-count 100
topsailai_memory_evict --workspace /path/to/topsailai-home/memory --max-count 100
topsailai_memory_evict --max-count 100 --json
```

The module can also be invoked through its executable module entry point.

## Options

| Option | Description |
|--------|-------------|
| `--workspace <path>` | Memory workspace containing the `story` folder. Defaults to `TOPSAILAI_HOME/memory` (the memory workspace resolved by the folder constants). |
| `--max-count <count>` | Required positive integer maximum for healthy memory/stat pairs. This value never falls back to `TOPSAILAI_MEMORY_STAT_MAX_COUNT`. |
| `--json` | Output a structured object containing the victim list and summary. |

## Selection and Safety

- The command always uses dry-run mode and provides no live deletion option.
- Only healthy synchronized (`synced=True`) memory/stat pairs are eligible.
- Unsynced (`synced=False`) memories are never selected automatically.
- Victims are ordered by oldest `last_activity_at`, with ties resolved by lexicographic `memory_id`.
- Each victim includes `memory_id`, `last_activity_at`, and `synced`.

## Output

Human-readable output includes the resolved workspace, maximum count, sorting rule, victim metadata, scan summary, and an explicit statement that no files were deleted.

With `--json`, output has this top-level structure:

```json
{
  "workspace": "/path/to/topsailai-home/memory",
  "max_count": 100,
  "dry_run": true,
  "sort": "oldest last_activity_at first, then lexicographic memory_id",
  "victims": [],
  "summary": {}
}
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Preview completed successfully. |
| 1 | Preview failed while scanning memory data. |
| 2 | Command-line arguments are invalid. |
