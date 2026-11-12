---
maintainer: AI
author: DawsonLin
---
# Byte-offset writes materialize the whole file

`file write --seek != 0` still allocates memory proportional to the whole file.
The write is lock-scoped and the `--from`/stdin source streams, but the splice
itself rebuilds the entire content as a string.

Split from `issue-file-write-large-file-and-lost-updates.md`, which fixed the
streaming and lock-scope defects but left this one open.

## Where the copies come from

`overwriteAt` (`pkg/filetool/write.go:65`) and `insertAt`
(`pkg/filetool/write.go:47`) both route through `updateText`, whose callback
receives the complete file as a string and returns the complete replacement:

```go
position := resolvePosition(seek, len(existing), false)
if position+len(content) <= len(existing) {
    return existing[:position] + content + existing[position+len(content):], nil
}
return existing[:position] + content, nil
```

For a file of size N that is: `existing []byte` (N), `string(existing)` (N),
the concatenated result (N), and `[]byte(updated)` (N) — four full copies to
change a handful of bytes.

Measured on a 209,715,186-byte file, baseline CLI RSS 6,468 KB:

| Command | Peak RSS |
|---------|----------|
| `file write --seek 100 --content HELLO` | 772 MB |

`file write --seek 0` is already bounded (6,424 KB) because it never reads the
existing file.

## Why this is fixable in place

The local adapter already exposes a seekable stream: `ObjectFS.Open` forwards
the adapter's `*os.File` when it is seekable, and `filetool.ReadSeekCloser`
carries `io.Seeker`. A byte-offset overwrite therefore does not need the file
content at all — it needs a writable handle positioned at the offset.

## Fix direction

1. **Add a positional write seam.** Extend `FS` with something like
   `WriteAt(path string, r io.Reader, offset int64, truncateAt int64) error`,
   implemented on `OSFS` with `os.OpenFile` + `WriteAt`, and on `ObjectFS`
   through a new manager primitive that holds object custody for the whole
   operation.
2. **Add the matching adapter method.** `ActualDataAdapter` needs a positional
   write that opens the payload file with `O_WRONLY` (not `O_APPEND`), seeks to
   the offset, copies the stream, and truncates when the replacement is shorter.
   The local adapter already resolves and validates the payload path in
   `WriteFile` and `AppendFile`, so the same validation applies.
3. **Keep custody across the whole operation.** The offset must be resolved
   against the current length under the same lock that performs the write,
   otherwise a concurrent append changes the meaning of a negative `--seek`.
   `Manager.UpdateActualFile` already holds custody; a positional variant must
   do the same without nesting a second lock acquisition, because the object
   lock is `LOCK_NB` and not re-entrant.
4. **Preserve the existing semantics.** `resolvePosition` clamping, negative
   `--seek` counting from the end, `--insert` adding one, extension when the
   replacement is longer, and truncation when it is shorter must all keep their
   current behaviour.
5. **Add a regression test.** Assert bounded allocation for
   `write --seek != 0` on a file far larger than the truncation limit, and
   assert byte-exact results for: overwrite in the middle, overwrite past the
   end (extension), overwrite with a shorter replacement (truncation), negative
   seek, and insert mode.

## Acceptance

- `file write --seek != 0` on a 200 MB file stays within a few megabytes of the
  baseline RSS.
- All offset, insert, extension, and truncation cases produce byte-identical
  results to the current implementation.
- `go test ./...` passes.

## Resolution

Resolved. Positional writes use `FS.WriteAt`, `Manager.WriteActualFileAt`, and
`ActualDataAdapter.WriteFileAt`. The local adapter resolves the offset while
the existing object lock is held, streams the unchanged prefix and suffix
through a same-directory temporary file, and atomically renames the result.
Negative offsets, insert mode, extension, and truncation retain their previous
semantics. Failure tests prove the old destination survives and temporary
files are removed.
