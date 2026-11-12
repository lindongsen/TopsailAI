---
maintainer: AI
author: DawsonLin
---
# Folder operations stream the whole archive on every call

`ObjectFS` has no path index, so every folder-level operation reads the object's
complete tar archive from disk to learn which paths exist. Memory stays bounded
because `tar.Reader` skips file bodies, but the I/O cost is proportional to the
whole object payload and is paid on every single call.

Split from `issue-file-write-large-file-and-lost-updates.md`, which fixed the
streaming and lock-scope defects but left this one open.

## Where the scan happens

`listAll` (`pkg/objectfs/objectfs.go:402`) opens `mgr.ReadActualArchive` and
walks every tar header to collect file paths. Four call sites use it:

| Call site | Triggered by |
|-----------|--------------|
| `isDir` (`objectfs.go:273`) | `Stat` when the file lookup fails — so `exists` on a folder or a missing path |
| `ReadDir` (`objectfs.go:291`) | `list-dirs` |
| `MkdirAll` (`objectfs.go:361`) | every `write`, `append`, `overwrite-lines`, `insert` into a subdirectory, because `writeText`/`updateText` call `MkdirAll` first |

`MkdirAll` is the expensive one in practice: it runs before every write that
names a subdirectory, including writes into a folder that already exists.

Measured on a 209,715,186-byte object, baseline CLI RSS 6,324 KB:

| Command | Elapsed | Peak RSS |
|---------|---------|----------|
| `file write root1.txt` (object root, no `MkdirAll` scan) | 0.01 s | 6,324 KB |
| `file write sub/dir1.txt` (new subdirectory) | 0.14 s | 7,204 KB |
| `file write sub/again1.txt` (subdirectory already exists) | 0.15 s | 7,400 KB |
| `file write a/b/c/d.txt` (three levels) | 0.20 s | 7,708 KB |
| `file exists a=big.txt` (file, no scan) | 0.01 s | 6,528 KB |
| `file exists a=sub` (folder, scans) | 0.15 s | 7,472 KB |
| `file exists a=nope.txt` (missing, scans) | 0.13 s | 7,248 KB |
| `file list-dirs .` | 0.16 s | 7,140 KB |

A write at the object root costs 0.01 s; the same write one level down costs
0.15 s. The 15x difference is entirely the archive scan, and it does not shrink
when the folder already exists.

## Why it matters at scale

The cost is O(object size) per call, not O(number of paths). A 2 GB object makes
every subdirectory write take over a second, and a script that writes 100 files
into a subdirectory pays that cost 100 times. This is the same class of defect
as the read and write buffering: the work is proportional to data the operation
does not need.

## Fix direction

1. **Cache the path set per object.** `ObjectFS` is constructed per command
   invocation, so a per-instance cache already removes repeated scans within one
   command. `MkdirAll` writing three markers for `a/b/c` currently scans once but
   each marker write re-enters the manager; a cache makes the whole command pay
   one scan.
2. **Make the cache invalidate on write.** Any `WriteFile`, `WriteFileFrom`,
   `AppendFrom`, or `UpdateFile` that creates a new path must update the cached
   set, not just drop it, so a command that writes then lists does not rescan.
3. **Prefer a direct existence probe over a full scan.** For `isDir`, the local
   adapter can answer "does this folder exist" without listing the whole object.
   A `StatFile`-style adapter method, or a manager-level existence check that
   does not enumerate, removes the scan from `exists` entirely.
4. **Consider a persistent index.** A per-object path index stored in the Hash
   metadata leaf would make folder operations O(1) across process boundaries.
   This is a larger change and should be evaluated separately; the in-process
   cache plus the direct probe covers the common case.
5. **Keep the semantics identical.** A folder still becomes visible only when it
   holds a file, `mkdirs` still writes an `AGENTS.md` marker per created level,
   an existing level is still skipped, and the object root is still never
   modified.
6. **Add a regression test.** Assert that a second `MkdirAll` for the same path
   does not re-read the archive, and that `exists` on a folder does not enumerate
   the object. A counting wrapper around the archive reader makes this
   observable without timing.

## Acceptance

- A write into an existing subdirectory of a 200 MB object costs about the same
  as a write at the object root.
- `exists` on a folder does not stream the archive.
- Folder visibility, marker creation, and skip-existing behaviour are unchanged.
- `go test ./...` passes.

## Resolution

Resolved. `ActualDataAdapter` now exposes `StatFile` and `ListFiles`, and
`ObjectFS.Stat`, `ReadDir`, and `MkdirAll` use those operations instead of
`ReadActualArchive`. The local adapter performs direct filesystem metadata and
directory discovery while filtering reserved temporary paths. Counting-adapter
regression tests prove folder discovery does not call `ReadArchive`; marker
creation and skip-existing behavior remain unchanged.
