---
maintainer: AI
author: DawsonLin
status: done
created: 2026-11-11
---

# The Windows test suite fails instead of skipping, so a Windows run says nothing

## Symptom

Running the unit suite on Windows reports 13 failures and 5 skips in
`internal/node`. Most of the failures are tests that cannot run on Windows at all,
and they fail rather than skip, so a red Windows run is indistinguishable from a
real regression.

## Reproduction

```
GOOS=windows GOARCH=amd64 go test -c -o node.test.exe ./internal/node
wine node.test.exe -test.v
```

13 failures, 5 skips. The POSIX baseline `go test ./...` is green, so every failure
is Windows-specific.

## Impact

The project rule is that a path rule which only holds on POSIX is a defect. The
same rule applies to the tests: a suite that cannot be run on a supported platform
provides no evidence there, and a suite that fails for environmental reasons trains
the reader to ignore a red result.

## Root cause

Four distinct causes:

1. **Symlink creation needs a privilege.** Nine tests call `os.Symlink` and then
   `t.Fatalf` on failure. On a default Windows host a normal account gets
   `ERROR_PRIVILEGE_NOT_HELD` unless Developer Mode is enabled, so the test fails
   before it tests anything. Two other tests in the same package already use
   `t.Skipf` for exactly this reason, so the convention exists and was not applied
   consistently.
2. **`string(filepath.Separator)` is not a filesystem root on Windows.**
   `TestOpenScopeRejectsBadMappings/filesystem_root` uses it as the input, but on
   Windows it is `\`, and `filepath.IsAbs("\\")` is false, so the path is refused as
   "relative" and the expected "filesystem root" message never appears. The
   production check is correct; the test's input is POSIX-only.
3. **Two tests assert POSIX-only behaviour.** `TestDeviceOfReportsADeviceForARealFile`
   asserts a device is reported, but `deviceOf` returns false on Windows by design.
   `TestCheckIdentityFileModeReportsAMissingFile` asserts a missing file is
   reported, but the function returns nil on Windows before stat-ing.
4. **Windows strips a trailing space.** `TestScopeListReportsGrammarRefusedName`
   writes a file named `trailing ` and expects to list it. Windows creates
   `trailing`, so the entry never exists. The test's own `Skipf` guard does not fire
   because the write succeeds.

## Detection failure

The suite was only ever run on Linux. Cross-compilation was never part of the build
or check target, so `go vet` and `go build` for Windows were never run either, and
the platform-specific tests were never executed on the platform they describe.

## Fix

1. Use `t.Skipf` when `os.Symlink` fails, matching the convention already used in
   `fence_extra_test.go` and `store_extra_test.go`.
2. Build the filesystem-root input per platform, for example from
   `filepath.VolumeName` plus a separator on Windows and `filepath.Separator` on
   POSIX.
3. Make the two POSIX-only assertions platform-aware, or skip them with a stated
   reason.
4. Skip the trailing-space case when the filesystem strips the space, by checking
   the created name rather than assuming it.
5. Add `build-windows` and `test-windows-compile` targets to the `Makefile` so the
   check is repeatable rather than a one-off.

## Resolution

Fixed. The suite now reports 0 failures and 18 skips on Windows, down from 13
failures and 5 skips.

- `mustSymlink(t, target, link)` in `fence_test.go` creates the link and then reads
  it back with `os.Lstat`, skipping when the entry is missing or is not a symlink.
  Reading the link back is the part that matters: under wine `os.Symlink` returns
  success while creating nothing, so a `Skipf` on the error alone never fired.
  All 14 `os.Symlink` call sites now use it.
- `filesystemRootPath(t)` derives the root from `os.Getwd()` and
  `filepath.VolumeName`. A bare `\` is drive-relative on Windows and
  `filepath.IsAbs("\\")` is false, so the old input was refused as a relative path
  and never reached the filesystem-root check.
- `TestOpenScopeRejectsSymlinkRoot` was split out of
  `TestOpenScopeRejectsBadMappings`, because a table-driven case cannot skip on its
  own without hiding the other cases.
- `TestDeviceOfReportsADeviceForARealFile` and
  `TestCheckIdentityFileModeReportsAMissingFile` now expect the Windows behaviour
  instead of the POSIX one.
- `TestScopeListReportsGrammarRefusedName` verifies through `directoryHasName` that
  the name survived the write before asserting, because Windows strips a trailing
  space while the write still returns nil.

Every remaining skip is a platform limit, not a hidden defect: 14 symlink fixtures
that the platform cannot create, 2 permission-bit assertions that carry no meaning
on Windows, 1 trailing-space name the filesystem strips, and 2 `os.UserHomeDir`
cases that read a different variable on Windows.

A repeatable check was added so this cannot regress silently: `make build-windows`
and `make test-windows-compile`, both wired into `make check`.
