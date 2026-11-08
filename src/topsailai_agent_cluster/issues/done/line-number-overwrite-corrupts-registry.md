---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# Chained line-number edits corrupted the BDD feature registry

## Trigger

A file is edited by replacing a line range, then edited again using a line number
remembered from before the first edit. The second edit lands on the wrong line
because the first edit changed the line count.

## Observed behavior

While registering the output follow feature, `tests/bdd/suite_test.go` was edited
by replacing one feature path with two lines. A follow-up edit used a line number
taken from the pre-edit file. The result was:

- `bidirectional_channel.feature` appeared twice in the path list.
- `unknown_input_offer.feature` disappeared entirely.

The corruption was silent: the file still parsed, the suite still compiled, and
only a later read of the file revealed the duplicate and the missing entry. It
was repaired by reading the file and rewriting the affected slice with boundary
assertions.

The same failure mode occurred four times during this task in different files:
a struct lost a field, a brace landed in the wrong place, a block was duplicated,
and a `case` header was duplicated while a closing brace was deleted.

## Impact

- A dropped feature path means those scenarios silently stop running. The suite
  still reports success, so the loss is invisible in CI.
- A duplicated path means the same scenarios run twice, inflating the scenario
  count and hiding the fact that coverage did not actually grow.
- Both defects are in test infrastructure, so they weaken every later
  verification rather than one feature.

## Root cause

Line-number replacement is positional, not semantic. The tool has no knowledge of
what the lines mean, and it does not re-read the file between calls. Any edit that
changes the number of lines invalidates every line number obtained before it, so
chaining edits from a remembered number is unsafe by construction.

The deeper cause is that the edit was applied as a range replacement to a list
whose entries are semantically independent, when the intent was "add one entry".
A whole-file write, or an edit anchored on the entry text rather than its line
number, cannot produce a duplicate or a deletion.

## Proposed resolution

- Write new files whole rather than by line range.
- When editing an existing file, re-read it immediately before each edit and
  derive the line number from that read, never from an earlier one.
- Prefer edits anchored on unique surrounding text over bare line numbers, so the
  edit fails loudly when the anchor is missing instead of landing on a neighbour.
- After any edit to a registry or list, read the file back and assert the expected
  entry count and the presence of every expected entry.
- For a list of independent entries, add or remove one entry rather than
  replacing a range.

## Verification

- A read-back check after the edit asserts the exact set of feature paths, so a
  duplicate or a missing entry fails immediately.
- The BDD suite reports the expected scenario count; a drop in count is treated as
  a failure rather than a smaller run.
- Review of the diff confirms the change is an addition, with no unrelated line
  removed.

## Resolution

The defect is in the editing process, not in product code, so a source change
cannot prevent it. The durable mitigation is a guard that fails loudly when the
registry loses or duplicates an entry.

### Change

- `tests/bdd/suite_test.go`: the feature path list was extracted from the inline
  `godog.Options` literal into a package-level `featurePaths` value, so a guard
  can inspect it. The suite passes a copy (`append([]string(nil), featurePaths...)`)
  so a future mutation of the slice cannot silently alter a running suite. The
  path list itself is unchanged: same 16 entries, same order.
- `tests/bdd/suite_registry_test.go` (new): four guards.
  - `TestFeatureRegistryHasNoDuplicates`: no path appears twice. A duplicate runs
    the same scenarios twice and inflates the count.
  - `TestFeatureRegistryPathsExist`: every registered path resolves to a file.
  - `TestFeatureRegistryCoversEveryFeatureFile`: every `features/*.feature` on
    disk is registered. This is the silent-loss case.
  - `TestFeatureRegistryCountMatchesDisk`: registry length equals the file count.
    A coarse backstop only; it cannot catch a swap that keeps the total unchanged.

Both files were written whole rather than by line range, which is the discipline
this issue asks for.

### Verification

| Check | Result |
|---|---|
| `gofmt -l` on both files | clean |
| `go vet ./tests/bdd/` | clean |
| `go build ./...` | clean |
| `go test ./tests/bdd/ -run TestFeatureRegistry` | 4/4 pass |
| Full BDD suite | **74 scenarios / 285 steps, all pass** |

### Reverse verification

A guard that passes both before and after the defect proves nothing, so each
failure mode was injected, confirmed to fail, then restored.

| Injected defect | Caught by |
|---|---|
| Duplicated `bidirectional_channel.feature` | `HasNoDuplicates` (17 entries vs 16 files) and `CountMatchesDisk` |
| Deleted `unknown_input_offer.feature` (the historical case) | `CoversEveryFeatureFile` (15 entries vs 16 files) and `CountMatchesDisk` |
| Deleted `unknown_input_offer.feature` **and** duplicated `bidirectional_channel.feature` | `HasNoDuplicates` and `CoversEveryFeatureFile`; `CountMatchesDisk` correctly stayed silent because the total really was 16 |

The third case is why the precise checks exist: a count-only guard would have
passed a registry that lost one feature and ran another twice.

After each injection the file was restored from `.tmp/suite_test.go.bak` and
confirmed byte-identical with `diff`, then the guards were re-run green.

### In-session recurrences

The hazard was still active while this issue was being resolved:

- `internal/channel/follow_end_termination_test.go`: two functions spliced
  together, file would not compile, repaired by rewriting the file whole.
- `internal/endpoint/service_abort_log_test.go`: a chained edit left an unused
  `channel` import, build failed, repaired by deleting the import and running
  `gofmt`.

### Remaining limitation

The guard protects the feature registry only. It cannot detect a chained edit that
corrupts a struct, a brace or a `case` header in ordinary source, which is the
other half of what this issue recorded. Those cases are caught by the compiler and
by `gofmt`, not by this guard. The editing discipline in the proposed resolution
remains the primary mitigation; this guard is the backstop for the one place where
corruption compiles and stays silent.
