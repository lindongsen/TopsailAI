---
maintainer: AI
author: DawsonLin
---
# Line-range edits build full snapshots for the diff

`file overwrite-lines` and `file insert` still allocate memory proportional to
the whole file, even though the write itself is now lock-scoped and the read
path streams. The remaining cost is the unified diff, not the write.

Split from `issue-file-write-large-file-and-lost-updates.md`, which fixed the
streaming and lock-scope defects but left this one open.

## Where the copies come from

One `overwrite-lines` call on a file of size N holds these full copies at once:

1. `existing []byte` from `FS.UpdateFile` — N bytes.
2. `string(existing)` in `updateText` (`pkg/filetool/write.go:114`) — N bytes.
3. `before = existing` in `overwriteRange` (`pkg/filetool/edit.go:66`) — N bytes.
4. `lines := splitLinesKeepEnds(before)` (`pkg/filetool/edit.go:67`) — N bytes
   spread over a `[]string` of every line, plus per-line slice headers.
5. `updated` built by three `strings.Join` calls (`pkg/filetool/edit.go:95`) —
   N bytes.
6. `[]byte(updated)` back in `updateText` — N bytes.
7. `difflib.SplitLines(before)` and `difflib.SplitLines(after)` in
   `unifiedDiff` (`pkg/filetool/write.go:205`) — 2N bytes, plus two more
   `[]string` line indexes.

`insertLineAt` (`pkg/filetool/edit.go:147`) has the same shape.

Measured on a 209,715,186-byte file, baseline CLI RSS 6,468 KB:

| Command | Peak RSS |
|---------|----------|
| `file insert` | 1,105 MB |
| `file overwrite-lines` | 1,122 MB |

## Why streaming alone does not fix it

A unified diff needs both the before and after text to compute hunks. Making the
write streaming does not help, because the diff is computed after the write from
two in-memory snapshots. The fix has to bound the diff window, not the I/O.

## Fix direction

1. **Compute the diff from a bounded window.** Only the replaced range and a
   few context lines around it can change. Slice the before text to
   `[rangeStart - context, rangeEnd + context]` and the after text to the
   corresponding span, then diff those two small windows. The hunk header line
   numbers are already known from the range, so the window does not need the
   full file to produce correct `@@ -a,b +c,d @@` headers.
2. **Avoid the intermediate `[]string` of every line.** `splitLinesKeepEnds`
   builds a slice of all lines only to index into the range. A byte-offset scan
   that finds the start and end of the range, plus the line count up to that
   point, gives the same result with constant extra memory.
3. **Build `updated` as a stream, not a concatenation.** Copy the untouched
   prefix, write the replacement, copy the untouched suffix. The diff window
   from step 1 is the only part that needs to be materialized.
4. **Keep the existing behaviour contracts.** Line-ending preservation
   (`trailingLineEnding`), the `--end 0` and `--end -1` sentinels, the
   `OverwriteWarning` prefix, and the `Nothing Changed` output must not change.
5. **Add a regression test.** Assert bounded allocation for `overwrite-lines`
   and `insert` on a file far larger than the truncation limit, using the
   `allocatedBytes` helper already in `pkg/objectfs/objectfs_test.go`. Also
   assert the diff text is byte-identical to the current implementation for a
   range in the middle, at the start, and at the end of a file.

## Acceptance

- `file overwrite-lines` and `file insert` on a 200 MB file stay within a few
  megabytes of the baseline RSS.
- Diff output is byte-identical to the current implementation for the covered
  cases.
- `go test ./...` passes, including the existing line-ending and sentinel tests.
