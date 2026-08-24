---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_memory_reconcile

Reconcile memory stat records with their Markdown memories.

## Purpose

Scans the story memory workspace and repairs the correspondence between
Markdown memory files and their `.stats` JSON records. Healthy pairs are kept,
orphaned stats are purged, corrupt or mismatched stats are moved to a
quarantine folder, and missing stats are rebuilt from the Markdown files. The
command also enforces optional retention limits on the quarantine folder.

By default the command runs in dry-run mode and only reports what it would do;
pass `--no-dry-run` to apply the changes.

## Invocation

```bash
topsailai_memory_reconcile
topsailai_memory_reconcile --dry-run
topsailai_memory_reconcile --no-dry-run
```

The module can also be invoked through its executable module entry point.

## Options

| Option | Description |
|--------|-------------|
| `--dry-run` | Report planned actions without changing files. Enabled by default. |
| `--no-dry-run` | Disable dry-run mode and apply the reconciliation changes. |

The memory workspace is resolved internally from the story memory workspace
(`TOPSAILAI_STORY_WORKSPACE`, falling back to `TOPSAILAI_MEMORY_WORKSPACE`,
then the configured memory folder). There is no `--workspace` option.

## Reconciliation Actions

- `healthy` — a stat record correctly matches its Markdown memory.
- `rebuilt` — a Markdown memory has no stat record; one is regenerated.
- `purged_orphan` — a stat record has no matching Markdown memory; it is deleted.
- `quarantined` — a stat record is corrupt, mismatched, or ambiguous; it is moved
  to the `_quarantine` subfolder of the stats directory.
- `errors` — classification or repair attempts that failed.

Quarantined files are further subject to retention limits read from the
environment:

| Variable | Default | Meaning |
|----------|---------|---------|
| `TOPSAILAI_MEMORY_STAT_QUARANTINE_MAX_AGE_DAYS` | `30` | Maximum age in days for quarantined stats. |
| `TOPSAILAI_MEMORY_STAT_QUARANTINE_MAX_COUNT` | `100` | Maximum number of quarantined stats to retain. |

## Output

The command prints a JSON summary object:

```json
{
  "scanned": 42,
  "healthy": 38,
  "rebuilt": 2,
  "purged_orphan": 1,
  "quarantined": 1,
  "errors": 0,
  "dry_run": true,
  "elapsed_ms": 35
}
```

Field meanings:

| Field | Meaning |
|-------|---------|
| `scanned` | Total Markdown memories and stat records examined. |
| `healthy` | Stat records that correctly match their memory. |
| `rebuilt` | Stats regenerated from Markdown memories. |
| `purged_orphan` | Orphaned stats deleted. |
| `quarantined` | Corrupt or mismatched stats moved to quarantine. |
| `errors` | Failures encountered during reconciliation. |
| `dry_run` | Whether the run reported only planned actions. |
| `elapsed_ms` | Elapsed time in milliseconds. |

Progress and quarantine movements are also logged.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Reconciliation completed successfully. |
| 1 | Reconciliation failed while scanning or repairing memory data. |
| 2 | Command-line arguments are invalid. |
