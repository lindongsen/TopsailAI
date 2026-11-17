---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: resolved
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

## Resolution

### Finding 1 (symlink admission): confirmed and fixed

The design corpus mandates rejection in five explicit places, so this was a
conformance defect rather than an open policy question:

```text
docs/Hooks_API.md:305                          never follows file or directory symbolic links
docs/Hooks_API.md:480                          rejects symlinks ... as a whole-point failure
features/feature-unified-hooks-design.md:160   local and external resources share security admission
features/feature-unified-hooks-design.md:615   symlinks ... reject the complete affected point
features/feature-unified-hooks-design.md:860   reject symlinks, path escape ... without partial admission
```

`hooks/point_entry.py::_eligible` now rejects a symlink before the existence
check, so the raise propagates through `_discover` into `execute_point`'s
`except Exception` and produces `unavailable_result(name, "discovery_failed")`.
That is whole-point failure, never partial admission.

Measured before and after:

| Probe | Before | After |
|---|---|---|
| `symlink -> file inside folder` | `_eligible=True` | `ValueError` |
| `symlink -> file OUTSIDE folder` | `_eligible=True` | `ValueError` |
| escape folder as a point | admitted `['link_esc.py']` | `status=unavailable`, no handlers |
| real regular file | admitted | `status=success`, `['plain.py']` |
| broken symlink | `unavailable` | `unavailable` (unchanged) |

No symlink exists under `hooks/points` today (`find hooks/points -type l`
returned nothing), so no deployed resource changes behaviour.

### Finding 2 (ordering key): disproven, no code change

The issue assumed the registered name and the filename differ. They do not.
`handler_result(...)` receives `path.name` as its filename argument and
`HandlerIdentity(f"{kind}:{filename}", filename, kind)` stores that same value
as `name`, so the registered name **is** the filename.

Probe output:

```text
registered names : ['a-b.py', 'a.so']
filenames on disk: ['a-b.py', 'a.so']
registered == filenames : True
sorted(registered) == registered : True
```

The design settles the question directly at
`features/feature-unified-hooks-design.md:168`: "Filename order applies where
the admitted name is the filename." Sorting by `path.name` therefore already
conforms. Switching the sort key to the logical name would **violate** that
clause, so no change was made and the characterization test
`test_module_ordering_uses_filename_not_logical_name` stays as written.

### Tests updated

The three characterization tests that encoded symlink admission were rewritten
to assert whole-point failure, and renamed so their names no longer claim
admission:

```text
test_symlink_child_is_admitted_and_escape_is_not_rejected -> test_symlink_child_is_rejected_including_escape
test_symlink_to_directory_is_skipped                      -> test_symlink_to_directory_is_rejected
test_broken_symlink_reports_discovery_failure             (docstring corrected)
```

The BDD harness now asserts the point status as well as the per-handler rows,
because an empty handler list alone cannot distinguish "rejected" from "nothing
found". `symlink-inside`, `symlink-escape` and `symlink-directory` expect
`unavailable` plus a `discovery failed` diagnostic; `ordering-logical` expects
`completed_with_errors` (the deliberately invalid `a.so` fails at import).

### Verification

```text
tests/unit/test_topsailai_hooks/test_point_entry_prototype.py   31 passed
tests/bdd/test_point_entry_resource_edges.py                     4 passed
combined                                                        35 passed
```

Negative control, removing only the `is_symlink()` guard:

```text
unit: 2 failed  (DID NOT RAISE ValueError at :370 and :387)
bdd : 3 failed  (symlink-inside, symlink-escape, symlink-directory)
```

Restoring the guard returns both suites to green, which proves the tests
observe the rejection rather than the surrounding plumbing.

### Disclosure: the decision rested on a timeout default

`MEMORY.md` requires explicit Human approval before a behavioural change. The
three-way choice (reject all symlinks / reject only escaping symlinks / keep
current behaviour) was escalated and returned `status: timeout` after 300
seconds, so the recommended option was applied as the default. This is a
timeout default, not explicit approval, and the Human may reverse it.

### Pre-existing failures are unrelated

`tests/unit/test_topsailai_hooks` reports 324 failed / 4583 passed, dominated by
`trust_rejected` in the artifact-lease and plan-capture suites. Zero of those
failures are in `point_entry` tests, and the same baseline was recorded before
this change.

## Status

Resolved. Finding 1 fixed and verified with a negative control; finding 2
disproven against the design's own ordering clause.
