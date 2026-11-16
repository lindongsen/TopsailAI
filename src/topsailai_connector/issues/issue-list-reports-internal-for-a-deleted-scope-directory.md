---
maintainer: AI
author: DawsonLin
status: open
severity: low
created: 2026-11-16
platform: linux
---

# A listing of a scope whose directory was deleted reports `internal`, not `not_found`

## Symptom

When the scope directory is deleted while the Node is running, the three read
operations disagree about what happened. Measured on Linux with the Node running
and the scope directory removed underneath it:

```
file.read  hello.txt   -> not_found: the path does not exist inside the scope
file.stat  hello.txt   -> not_found: the path does not exist inside the scope
file.list  (root)      -> internal: the server failed
```

The Node stays alive in every case, so this is a wrong code rather than a crash.
The same request answered `not_found` for `read` and `stat` answers `internal` for
`list`, and the caller cannot tell "the directory is gone" from "the server
broke".

## Cause

Two different mappings for the same condition.

`internal/node/fence.go` `classifyOpenError` maps a missing path to `not_found`:

```go
if errors.Is(err, os.ErrNotExist) {
    return newError(protocol.CodeNotFound, "open: %v", err)
}
```

`internal/node/fence.go` `List` maps a `Readdirnames` failure to `internal`
unconditionally, without consulting `classifyOpenError`:

```go
names, err := file.Readdirnames(-1)
if err != nil {
    return nil, newError(protocol.CodeInternal, "list %q: %v", path, err)
}
```

`Read` and `Stat` reach the missing directory through `openValidated`, which
classifies the error. `List` opens the directory successfully — the `os.Root`
handle still references the deleted inode — and only fails at the read, which is
the step that has no classification.

## Why it matters

`internal/protocol/codes.go` defines `CodeInternal` as "the Server failed.
Details are logged, never returned." A deleted scope directory is not a Server
failure and not a Node defect; it is a caller-visible condition that the other two
operations already report as `not_found`.

The consequence is a caller that retries on `internal` and gives up on
`not_found`, which is the opposite of the correct reaction: retrying will never
succeed, because the handle keeps the deleted inode and a recreated directory at
the same path is not adopted. Measured: after deleting and recreating the scope
directory, `read` still returned `not_found` and `list` still returned `internal`.

## Platform difference

The case is unreachable on Windows. A directory the Node holds open cannot be
deleted or renamed:

```
Remove-Item -LiteralPath <scope> -Recurse -Force
  -> The process cannot access the file because it is being used by another process
Rename-Item -LiteralPath <scope> -NewName scope-renamed
  -> The process cannot access the file because it is being used by another process
```

`-Recurse` does delete the contents, so the reachable Windows state is an emptied
scope rather than a deleted one. Measured on Windows Server 2022 with the Node
running and the scope emptied:

```
file.list  (root)      -> success, empty output
file.read  hello.txt   -> not_found
file.list  empty-dir   -> not_found
```

So the Windows answer is already consistent, and the defect is Linux-only in
practice. It is still a defect, because the code path is platform-independent and
the Linux behaviour is the one a caller sees.

## Fix direction

`List` should classify the `Readdirnames` failure the same way `openValidated`
does, rather than mapping every failure to `internal`. A missing directory is
`not_found`; a genuine I/O failure stays `internal`. The classification belongs in
one place so the three operations cannot drift apart again.

## Evidence

- `.tmp/nonexistent-scope/local/delete-results.txt` — the Linux run, six cases.
- `.tmp/nonexistent-scope/windows/emptied-scope-results.txt` — the Windows run.
- `.tmp/nonexistent-scope/win-delete-scope.ps1` — the refused deletion.
- `.tmp/nonexistent-scope/win-delete-sub.ps1` — the refused rename.
