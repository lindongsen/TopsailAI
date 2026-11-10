---
maintainer: AI
author: DawsonLin
status: open
created: 2026-11-09
---

# Scope name validation accepts characters that are not identifiers

## Symptom

`internal/security/scopes.go` `ValidateScopeName` rejects only an empty name, a
path separator, `.` and `..`. A scope name is supposed to be an identifier, but a
space, a tab, a NUL byte, a colon and a trailing dot are all accepted.

## Reproduction

```
"a b"    ACCEPTED
"a\tb"   ACCEPTED
"a."     ACCEPTED
"a\x00b" ACCEPTED
"a:b"    ACCEPTED
```

## Impact

A scope name reaches a filesystem call and a policy file. A NUL byte truncates the
string at the syscall boundary, so the name that was validated and the name that
is used can differ. A colon introduces an alternate data stream on Windows. A
trailing dot is stripped by Windows, so `a.` and `a` are the same directory while
the policy treats them as different names.

## Root cause

The validation was written to stop path traversal only, because traversal was the
obvious attack. The identifier requirement in the design document was not
translated into a character set, so the check is narrower than the rule it is
supposed to enforce.

## Fix

Restrict a scope name to letters, digits, `-` and `_`, and reject a leading or
trailing separator. Reject any control character, any NUL byte, any colon and any
trailing dot. The rule must be stated in `docs/permission-design.md` so a future
change has to argue against it.

## Detection failure

The existing tests cover the separator, `.` and `..` cases, which are the cases the
implementation was written for. No test asserted that a name must be an
identifier, so the gap between the rule and the check was never exercised.
