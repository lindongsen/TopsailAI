---
maintainer: AI
author: DawsonLin
status: done
created: 2026-11-11
---

# A legitimate scope is refused on Windows because the path is compared as a raw string

## Symptom

`OpenScope` refuses a correct scope directory on Windows with the message
`a scope root must not be a symlink`, even though the directory is a real
directory and not a symlink.

## Reproduction

On Windows, with a real directory `C:\Users\me\Project`:

```
OpenScope("project", `C:\Users\me\Project`)   accepted
OpenScope("project", `C:/Users/me/Project`)   REFUSED: "resolves to ...; a scope root must not be a symlink"
OpenScope("project", `c:\Users\me\Project`)   REFUSED: "resolves to ...; a scope root must not be a symlink"
OpenScope("project", `C:\Users\me\Project\`)  REFUSED: "resolves to ...; a scope root must not be a symlink"
OpenScope("project", `C:\Users\me\Project\.`) REFUSED: "resolves to ...; a scope root must not be a symlink"
```

## Impact

`docs/cases/UserCase_identity-and-access.md` UC-8 cannot pass. A Windows operator
who writes `path: C:/Users/me/project` in the policy file — the spelling Windows
accepts and the one YAML authors naturally write — gets a startup failure naming a
symlink that does not exist. The Node refuses to start, so the failure is
fail-closed rather than a fence bypass, but Windows is not usable as documented.

## Root cause

`OpenScope` in `internal/node/fence.go` compares the configured path with
`filepath.EvalSymlinks(path)` as raw strings:

```go
resolved, err := filepath.EvalSymlinks(path)
if resolved != path {
    return nil, fmt.Errorf("scope %q: %q resolves to %q; a scope root must not be a symlink", ...)
}
```

On Windows `EvalSymlinks` normalises the path before returning it: `toNorm`
upper-cases the drive letter and `normBase` rewrites every component to its on-disk
case. The comparison therefore answers "did the spelling change" rather than "is
this a symlink", and on Windows those are different questions.

## Detection failure

The check was written and tested on POSIX, where `EvalSymlinks` returns the input
unchanged for a path that is already canonical. The test
`TestOpenScopeRejectsASymlinkedParent` asserts that a *different* path is refused,
which passes on both platforms; no test asserted that the *same* directory spelled
differently is accepted, so the false refusal was never exercised.

## Fix

Compare the two paths in a platform-appropriate way rather than as raw strings, and
apply the same normalisation to the home-directory check.

**The trap:** making only the symlink comparison case-insensitive opens a hole.
`isHomeDirectory` also compares by raw string, so once `c:\users\me` passes the
symlink check it would also pass the home check, and the home directory would
become an acceptable scope root — a blast radius of every file the user owns. Both
comparisons must be normalised together, or the home refusal must be applied to the
resolved path.

A test must assert that a case-different and separator-different spelling of the
same directory is accepted, and that the home directory is still refused when
spelled with a lower-case drive letter.

## Resolution

Fixed. The comparison now goes through `samePath` in `internal/node/platform.go`,
which cleans both sides and defers the case rule to the platform through
`pathEqual` (`pathcompare_windows.go` uses `strings.EqualFold`,
`pathcompare_other.go` uses `==`).

Both comparison sites were changed together, because fixing only the symlink check
would have let `c:\users\me` pass the home-directory check as well and turned the
whole home directory into a valid scope root:

- `fence.go` `OpenScope`: `resolved != path` -> `!samePath(resolved, path)`
- `fence.go` `isHomeDirectory`: raw `==` -> `samePath(path, resolvedHome)`

Regression proof: reverting to the old comparison makes
`TestOpenScopeAcceptsEquivalentSpellings/trailing_separator` fail with the exact
misleading message `resolves to "..."; a scope root must not be a symlink`.

Verified on Linux (`go test ./...` green) and on Windows under wine
(`TestSamePathAcceptsEquivalentSpellings`, `TestSamePathFollowsPlatformCaseRule`,
`TestSamePathRejectsDifferentDirectories`, `TestOpenScopeAcceptsEquivalentSpellings`
and `TestIsHomeDirectoryFollowsPlatformCaseRule` all pass).

Note: the defect was never Windows-only. `EvalSymlinks` cleans the path on every
platform, so a trailing separator or a redundant dot segment was refused on Linux
too. That is why a POSIX regression test covers it.
