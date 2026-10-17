---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# `point_entry` symlink admission and ordering-key gaps

Scope: `hooks/point_entry.py` (the only supported/maintained Hook resource path).

## Symptom

Empirically verified by running real code (probe under `.tmp`, since removed):

1. **Symlink children are followed, including path escape.** `_eligible()` uses `path.is_file()`, which follows symlinks. A symlink child pointing to a regular file inside the folder is admitted, and a symlink child pointing to a file **outside the point tree** is also admitted. There is no `is_symlink()` rejection and no path-escape check.
2. **Ordering uses the filename, not the logical name.** `_discover()` sorts by `path.name` (`hooks/point_entry.py:105`), while the design states the ordering authority is the final registered name (the logical name). Observed: for `a-b.py` + `a.so`, filename order is `['a-b.py', 'a.so']` but logical-name order is `['a.so', 'a-b.py']`.

## Impact

- A deployment-authorized external folder can silently admit resources that resolve outside the intended tree, weakening the containment expectation.
- Execution order can differ from the documented logical-name ordering when compiled extensions and source modules coexist.

## Evidence

- `hooks/point_entry.py:121-124` (`_eligible`, no symlink check).
- `hooks/point_entry.py:105` (`sorted(entries, key=lambda path: path.name)`).
- Characterization tests added: `tests/unit/test_topsailai_hooks/test_point_entry_prototype.py` (`test_symlink_child_is_admitted_and_escape_is_not_rejected`, `test_symlink_to_directory_is_skipped`, `test_broken_symlink_reports_discovery_failure`, `test_module_ordering_uses_filename_not_logical_name`).
- BDD: `tests/bdd/features/point_entry_resource_edges.feature`.

## Status

Open. The new tests assert CURRENT behavior (characterization), so the suite is green while the gap is documented. Fixing requires a decision on whether to reject symlinks and whether to switch the ordering key to the logical name.
