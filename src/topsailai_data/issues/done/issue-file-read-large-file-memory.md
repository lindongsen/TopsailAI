---
maintainer: AI
author: DawsonLin
---
# File read buffers the whole object file into memory

The `file` read subcommands are streaming-capable in `pkg/filetool`, but the
object-backed file system defeats that design. `pkg/objectfs/objectfs.go`
`Open` and `ReadFile` call `io.ReadAll` on the manager stream and wrap the
result in a `memoryFile`, so the complete file is resident before any window,
line range, or truncation limit is applied. The comment on `Open` claiming
"object files are bounded by the truncation limit on the read paths, so
buffering stays small" is false: truncation happens afterwards in
`filetool.readWindow`, so the buffer is the full file.

Measured on a 209,715,186-byte object file, baseline CLI RSS is 6.4 MB:

| Command | Peak RSS | Elapsed |
|---------|----------|---------|
| `file read big.log` (non-whitelisted, truncates to 30000) | 431 MB | 0.37s |
| `file read bigobj.md` (whitelisted, full content) | 1214 MB | 1.36s |
| `file read big.log --size 100` | 717 MB | 1.37s |
| `file read big.log --seek -100 --size 100` | 581 MB | 1.42s |
| `file read-lines big.log --start 1 --end 3` | 467 MB | 0.58s |
| `file read-around big.log 5 --context 2` | 581 MB | 0.92s |
| `file read-context big.log INFO --context 1` | 1340 MB | 13.34s |
| `file size big.log` | 430 MB | 1.07s |
| `file exists a=big.log` | 562 MB | 1.03s |
| `file list-dirs .` | 7 MB | 0.57s |
| `get bigobj big.log` | 6.4 MB | 0.05s |

`file size` and `file exists` are the worst offenders relative to their work:
`ObjectFS.Stat` reads the entire file only to report `len(data)`.

The local adapter already returns a seekable `*os.File` from
`ReadFile`, and `get` streams it with `io.Copy` at constant memory. The fix is
to let `ObjectFS.Open` return that stream directly when it is seekable, and to
give `Stat` a size query instead of a content read. Non-seekable remote
adapters need an explicit bounded-window or spool-to-temp strategy rather than
an unbounded `io.ReadAll`. A regression test must assert bounded memory on a
file far larger than the truncation limit.

## Resolution

Fixed. `ObjectFS.Open` now forwards the adapter stream when it is seekable
(`streamFile`), so `filetool` reads only the bytes it needs. `ObjectFS.Stat`
reports the size from a size query instead of reading content. Only a
non-seekable remote adapter still buffers.

Measured on the same 209,715,186-byte file, baseline 6,468 KB:

| Command | Before | After |
|---------|--------|-------|
| `file read big.log` (truncated) | 431 MB | 7,172 KB |
| `file read --size 100` | 717 MB | 6,728 KB |
| `file read --seek -100 --size 100` | 581 MB | 6,612 KB |
| `file read-lines 1..3` | 467 MB | 6,740 KB |
| `file read-around 5` | 581 MB | 6,832 KB |
| `file size` | 430 MB | 6,364 KB |
| `file exists` | 562 MB | 6,520 KB |
| `file read-context` (no match) | 1,340 MB | 12,440 KB |

Regression tests in `pkg/objectfs/objectfs_test.go` assert bounded allocation
on an 8 MB file for `ReadFile`, `Stat`, and the streaming write paths, plus a
sensitivity control proving the allocation counter observes buffers. Each
bounded-memory test was confirmed to fail against the pre-fix implementation.

Still open, tracked separately: `file read-context` whose pattern matches every
line is output-proportional (about 1.2 GB for a 200 MB result), and whitelisted
extensions remain uncapped by design, so `file read` still materializes a full
string for a huge whitelisted file.
