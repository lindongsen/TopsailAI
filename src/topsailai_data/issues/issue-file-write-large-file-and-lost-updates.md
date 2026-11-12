---
maintainer: AI
author: DawsonLin
---
# File write buffers whole files and loses concurrent updates

The `file` write subcommands have the same unbounded-buffering defect as the
read path, plus a correctness defect that the read path does not have.

## 1. Unbounded buffering

`filetool.FS` declares `WriteFile(path string, data []byte, perm)` and
`AppendFile(path string, data []byte, perm)`, so content is a complete byte
slice by construction. Every partial edit is a read-modify-write over the whole
file:

- `write --seek != 0` calls `readExisting` then rebuilds the whole content.
- `append` calls `ObjectFS.AppendFile`, which reads the whole file first.
- `overwrite-lines` and `insert` call `FS.ReadFile`, split every line into a
  `[]string`, join, and write back.
- `unifiedDiff` additionally builds `difflib.SplitLines` for both the before
  and after snapshots, doubling the resident copies.
- `resolveContent` buffers the whole `--from` file or stdin with
  `os.ReadFile` / `io.ReadAll`.

Measured on a 209,715,186-byte object file, baseline CLI RSS 6.3 MB:

| Command | Peak RSS | Elapsed |
|---------|----------|---------|
| `file write wobj.md --content x` (seek 0, full replace) | 6.5 MB | 0.03s |
| `file write wobj.md --seek 100 --content HELLO` | 840 MB | 0.81s |
| `file append wobj.md --content "tail line"` | 636 MB | 0.81s |
| `file write wobj.md --seek -1 --insert --content tail` | 480 MB | 1.09s |
| `file insert wobj.md 5 --content inserted` | 1048 MB | 2.15s |
| `file overwrite-lines wobj.md 5 --content replacement` | 1046 MB | 2.39s |
| `file write newbig.md --from big.md` (200 MB source) | 418 MB | 0.39s |
| `file append newbig.md --from big.md` (200 MB + 200 MB) | 1196 MB | 1.34s |
| `put wobj wobj.md --from big.md` (streaming, for comparison) | 6.5 MB | 0.28s |

`write --seek 0` is the only bounded path because it never reads the existing
file. `put` proves the adapter can stream; the `file` group cannot because its
interface takes `[]byte`.

## 2. Lost updates on concurrent writes

`ObjectFS.AppendFile` reads outside the lock and writes inside it:

```go
existing, err := f.ReadFile(p)          // no lock
combined := append(existing, data...)
return f.WriteFile(p, combined, perm)   // takes the lock
```

`ReadFile` goes through `readActiveObject`, which acquires a lock only when
`TOPSAILAI_DATA_READ_LOCK` is set (default `0`). The write lock therefore
protects only the final replacement, not the read that produced its input.

`filetool.OverwriteLines` and `InsertContent` have the same shape: `FS.ReadFile`
then `writeText`, two separate manager calls with no custody spanning them.

Reproduced with 20 concurrent `file append` calls on one object file; the
result kept 1 to 2 of the 20 appends:

```
run1: base|10
run2: base|17
run3: base|17
```

Five concurrent `file insert` calls on a 3-line file kept one insertion:

```
L1
ins2
L2
L3
```

This is silent data loss, not a performance issue. `OSFS.AppendFile` uses
`O_APPEND` and is atomic, so the defect is specific to the object-backed file
system.

## 3. Dead create-on-missing branch

`readExisting` treats a missing file as empty content when `os.IsNotExist(err)`
is true. `ObjectFS.ReadFile` returns a wrapped `errors.ErrObjectNotFound`, which
`os.IsNotExist` does not match, so the branch never runs for objects:

```
$ file insert brandnew.md 1 --object wobj --content hello
error: file insert: object not found: file "brandnew.md"
$ file write brandnew2.md --seek 5 --object wobj --content hello
error: file write: object not found: file "brandnew2.md"
```

The documented "creating parent folders as needed" and "a missing file is
treated as empty content" behaviour is unreachable through the object file
system.

## 4. Whole-archive scan on every subdirectory write

`writeText` calls `FS.MkdirAll` before writing. `ObjectFS.MkdirAll` calls
`listAll`, which streams the object's complete tar archive to collect paths.
Memory stays bounded because `tar.Reader` skips file bodies, but every write
into a subdirectory reads the entire object payload from disk. Measured 0.23s
for a 200 MB object.

## Fix direction

1. Add a streaming write seam: `WriteFileFrom(path string, r io.Reader, perm)`
   and `AppendFrom(path string, r io.Reader, perm)` on `FS`, so `--from` and
   stdin never materialise. `put` already proves the adapter supports it.
2. Implement `ObjectFS.AppendFile` with a real append (open the payload file
   with `O_APPEND` under the write lock) instead of read-modify-write.
3. Hold custody across the whole read-modify-write for `overwrite-lines`,
   `insert`, and `write --seek != 0`. Either expose a manager-level
   read-modify-write transaction or make the FS interface carry an explicit
   lock scope.
4. Make `overwrite-lines` and `insert` stream: copy the untouched prefix, write
   the replacement, copy the untouched suffix, and compute the diff from a
   bounded window rather than two full snapshots.
5. Fix the missing-file detection to use `errors.Is(err, ErrObjectNotFound)`
   instead of `os.IsNotExist`, or remove the unreachable branch.
6. Cache or index the object's path list so `MkdirAll` does not re-read the
   whole archive on every write.
7. Add regression tests: bounded memory on a file far larger than the
   truncation limit, and a concurrent-append test asserting no lost updates.
   No existing test covers either; `objectfs_test.go` has no concurrency test
   and `write_test.go` uses only tiny inputs.

## Resolution

Fixed for the streaming and lock-scope defects. The remaining diff, byte-splice,
and archive-scan work was split into three separate issues.

**Streaming write seam.** `FS` gained `WriteFileFrom`, `AppendFrom`, and
`UpdateFile`. `write` with `--seek 0` and no `--insert`, and `append`, stream
`--from` and stdin to the adapter through `openContent` instead of
materializing `[]byte`.

**Real in-place append.** `ActualDataAdapter` gained `AppendFile`, implemented
in the local adapter with `O_APPEND|O_CREATE|O_WRONLY` plus `io.Copy` under the
object lock. `ObjectFS.AppendFile` no longer reads the file first.

**Lock-scoped read-modify-write.** `Manager.UpdateActualFile` holds exclusive
object custody across read, transform, write, and timestamp publication.
`Manager.AppendActualFile` appends under the same custody. `overwrite-lines`,
`insert`, `write --seek != 0`, and `append` all route through these primitives.
The lock is the object's meta lock file
`meta/<h[0:2]>/<h[2:4]>/<h[4:6]>/<h>/lock`, acquired with `LOCK_NB`; because
flock is per open file description the lock is not re-entrant, so custody is
acquired once per operation and never nested inside `WriteActualFile`.

**Missing-file branch.** `readExisting` was replaced by `updateText`, which
receives an explicit `exists` flag from the manager instead of testing
`os.IsNotExist` against a wrapped error, so the create-on-missing path is now
reachable.

Measured on the same 209,715,186-byte file, baseline 6,468 KB:

| Command | Before | After |
|---------|--------|-------|
| `file append` | 636 MB | 6,592 KB |
| `file write --seek -1 --insert` | 480 MB | 6,576 KB |
| `file write --from big.md` | 418 MB | 6,660 KB |
| `file append --from big.md` | 1,196 MB | 6,668 KB |
| `file write --seek 100` | 840 MB | 772 MB |
| `file insert` | 1,048 MB | 1,105 MB |
| `file overwrite-lines` | 1,046 MB | 1,122 MB |

**Concurrency.** With the real binary, 20 concurrent `file append` calls
produced 4 successes and 16 explicit `ErrObjectLocked` failures, and all 4
acknowledged markers were present. 6 concurrent `file insert` calls produced 2
successes and 4 failures, and both acknowledged inserts persisted. An external
`flock(LOCK_EX|LOCK_NB)` holder makes a CLI write fail closed with
`object is locked by another process` and exit 1 without writing. Silent loss
is gone; contention now fails loudly.

**Remaining work, split into separate issues.**

The three open technical items were split so each can be evaluated, fixed, and
verified independently:

- `issue-diff-bounded-window.md` — `overwrite-lines` and `insert` remain about
  1.1 GB on a 200 MB file because `unifiedDiff` builds `difflib.SplitLines` for
  both snapshots. A unified diff needs both texts, so this needs a
  bounded-window diff strategy, not a streaming change.
- `issue-write-seek-inplace.md` — `write --seek != 0` remains 772 MB because
  `overwriteAt` materializes the file to splice bytes. A byte-offset overwrite
  can be done in place on the underlying handle.
- `issue-mkdirs-archive-scan.md` — `ObjectFS` has no path index, so `MkdirAll`,
  `ReadDir`, and `isDir` stream the whole tar archive on every call. A write
  into a subdirectory of a 200 MB object costs 0.15 s versus 0.01 s at the
  object root, and the cost does not shrink when the folder already exists.

One test limitation stays recorded here rather than in a separate issue:
`TestConcurrentAppendKeepsEverySuccessfulUpdate` does not distinguish a
lock-scoped append from an unlocked read-modify-write, because `LOCK_NB` makes
losers fail loudly in both cases. Bounded memory on a large existing file is
what pins the in-place implementation.
