---
maintainer: AI
author: DawsonLin
status: fixed
severity: low
created: 2026-11-16
fixed: 2026-11-16
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

## Resolution

Fixed by classifying the `Readdirnames` failure instead of mapping every failure
to `internal`.

`internal/node/fence.go` gained `classifyDirectoryReadError`, placed immediately
after `classifyOpenError` so the two classifications sit side by side and cannot
drift apart again:

```go
func classifyDirectoryReadError(path string, err error) *Error {
	if errors.Is(err, os.ErrNotExist) {
		return newError(protocol.CodeNotFound, "list %q: %v", path, err)
	}
	return newError(protocol.CodeInternal, "list %q: %v", path, err)
}
```

`List` now delegates to it:

```go
names, err := file.Readdirnames(-1)
if err != nil {
	return nil, classifyDirectoryReadError(path, err)
}
```

Only a missing directory becomes `not_found`. Every other failure stays `internal`,
because a genuine I/O failure while reading a directory is a Node defect and not a
caller-visible condition.

### Verification

Live reproduction, Node running with the scope directory deleted underneath it:

```
before-read    rc=0  recreated
before-list    rc=0  hello.txt	file	10
before-stat    rc=0  name hello.txt type file size 10 ...
--- DELETING the scope directory ---  deleted=YES
after-read     rc=1  not_found: the path does not exist inside the scope
after-list     rc=1  not_found: the path does not exist inside the scope
after-stat     rc=1  not_found: the path does not exist inside the scope
recreated-read rc=1  not_found
recreated-list rc=1  not_found
NODE_ALIVE=True  NODE_EXITED_EARLY=False
```

All three operations now agree, and the Node stays alive. The recreated directory
is still `not_found`, which is the documented behaviour: the handle keeps the
deleted inode and the directory is adopted by the next start, not by a running
process.

Tests added in `internal/node/coverage_extra_test.go`:

- `TestListReportsAMissingDirectory` now asserts `CodeOf(err) == CodeNotFound`
  instead of only `err != nil`, which passed both before and after the fix.
- `TestListReportsAVanishedDirectoryAsNotFound` deletes the scope directory and
  asserts all three operations report `not_found`. It skips when the deletion is
  refused, which is the Windows behaviour.
- `TestClassifyDirectoryReadErrorKeepsGenuineFailuresInternal` asserts a
  non-`ErrNotExist` failure stays `internal`.

Mutation testing, to prove the tests are not vacuous:

| Mutation | Result |
|---|---|
| `List` reverted to the hardcoded `internal` | `TestListReportsAVanishedDirectoryAsNotFound` failed: `CodeOf(List()) = internal, want not_found` |
| Classifier always returns `not_found` | `TestClassifyDirectoryReadErrorKeepsGenuineFailuresInternal` failed: `= not_found, want internal` |

The file was restored afterwards and its md5 compared with the backup:
`26b65e913962e7f3b3ec04800d07d838` for both.

Suite results: `go build ./...` 0, `go vet ./...` 0, `gofmt -l internal cmd` empty,
`go test -count=1 ./...` 0 with 9 packages `ok`, `make check` 0 with no `FAIL` line.

### Documents updated

- `docs/permission-design.md`: new section "A scope directory that vanishes while
  the Node runs", plus an enforcement checklist item that the three operations must
  report the same code for the same condition.
- `docs/cases/TestCase_operations.md`: new section "Cross-operation consistency"
  with TC-OP-57 and TC-OP-58.
- `LEARN.md`: the existing section "The same missing directory answered differently
  depending on the operation" now records the fix, the one-classifier rule, the
  vacuous-test trap and the mutation evidence, instead of describing the defect as
  open.
