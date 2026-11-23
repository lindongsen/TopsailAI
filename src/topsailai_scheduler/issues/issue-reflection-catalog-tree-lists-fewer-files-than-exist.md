---
maintainer: AI
author: DawsonLin
status: open
severity: low
created: 2026-11-23
---

# The reflection catalog's embedded folder tree lists fewer files than exist

## Symptom

The `note--ai-reflection-archive` catalog carries two inventories of the same set:
one line per reflection, and an embedded folder-structure tree. They disagree.

Measured on 2026-11-23 after the daily consolidation run:

```text
catalog entry lines : 216
reflection files    : 216
tree listing lines  : 213
```

The catalog lines and the files agree in both directions (no catalog entry without
a file, no file without a catalog entry), so only the tree is stale.

## Reproduction

```bash
A=/work/hosts/.topsailai/data/object/2026/0828/1817/notes/topsailai/lessons/note--ai-reflection-archive
grep -cE '^- `[a-z0-9-]+`' "$A/note--ai-reflection-archive.md"   # 216
ls "$A/reflections" | wc -l                                      # 216
awk '/^├── reflections$/{f=1;next} f&&/^└──|^[^│ ]/{f=0} f' \
  "$A/note--ai-reflection-archive.md" | grep -c '\.md$'          # 213
```

The three entries missing from the tree are `nested-field-absence-is-not-a-defect`,
`pathspec-resolves-from-current-directory`, and
`rebuild-does-not-replace-a-running-process`.

## Impact

The tree is a second source of truth for the same fact. A reader who trusts it will
believe three existing lessons do not exist, and a future consolidation run that
regenerates the tree from the catalog will produce a large, hard-to-review diff.

## Suspected cause

The tree is maintained by hand alongside the catalog lines. Entries added by a run
that only appended catalog lines left the tree behind, and the drift predates the
2026-11-23 run.

## Suggested fix

Derive the tree from the catalog instead of maintaining it by hand, or drop the tree
and keep the catalog lines as the single inventory. The daily task already caps a run
at five merges, so a full regeneration should be a deliberate, separately reviewed
change.
