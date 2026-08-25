---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_memory_delete

Delete a specific story memory and its stat record.

## Purpose

Removes a single story memory file (identified by its memory id / filename
stem) together with its accompanying `.stats` record. Deletion is destructive,
so the command prompts for confirmation unless `--yes` is passed.

## Invocation

```bash
topsailai_memory_delete 20260101T000000.My_Memory
topsailai_memory_delete --home /path/to/topsailai-home 20260101T000000.My_Memory
topsailai_memory_delete --yes 20260101T000000.My_Memory
topsailai_memory_delete --yes --json 20260101T000000.My_Memory
```

The module can also be invoked through its executable module entry point.

## Arguments

| Argument | Description |
|----------|-------------|
| `title` | Positional memory id (filename stem) to delete. The `.md` suffix is optional. |

## Options

| Option | Description |
|--------|-------------|
| `--home <path>` | TOPSAILAI_HOME; memory resolves to `{home}/memory`. If the path already contains `story/`, it is used as the memory root. Defaults to the configured memory workspace. |
| `--yes` | Skip the confirmation prompt. |
| `--json` | Output a structured object instead of human-readable text. |

## Behavior

- The memory file is matched by filename within the workspace `story` folder.
- Deleting a memory also removes its corresponding `.stats` record.
- Without `--yes`, the command prompts `[y/N]`; anything other than `y`/`yes`
  aborts the deletion. Non-interactive terminals deny by default.
- If the memory does not exist, the command reports an error and exits non-zero.

## Output

Human-readable output states the deleted memory id, its file path, and the
resolved workspace.

With `--json`, output has this top-level structure:

```json
{
  "workspace": "/path/to/topsailai-home/memory",
  "title": "20260101T000000.My_Memory",
  "memory_file": "/path/to/topsailai-home/memory/story/2026-01-01/20260101T000000.My_Memory.md",
  "deleted": true
}
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Deletion completed (or was cancelled by the user). |
| 1 | Resolution or deletion failed. |
| 2 | Command-line arguments are invalid. |
