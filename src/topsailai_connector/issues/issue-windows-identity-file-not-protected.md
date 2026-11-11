---
maintainer: AI
author: DawsonLin
status: deferred
created: 2026-11-11
---

# The identity file has no protection on Windows, and the documents claim it does

## Symptom

The file holding the `node-id.node-token` pair is readable by every account on a
Windows machine. `docs/Environment_Variables.md` states twice that it is protected
by "an owner-only ACL on Windows".

## Reproduction

On Windows, through the real code path:

```
resolveConfigDir -> os.MkdirAll(value, 0o700)
  config dir mode: drwxrwxrwx perm=0777

SaveIdentity -> temporary.Chmod(0o600)
  identity file mode: -rw-rw-rw- perm=0666

os.Chmod(identityPath, 0o644)
  identity file mode: -rw-rw-rw- perm=0666   (unchanged)
```

`LoadIdentity` then accepts the file without complaint, because
`checkIdentityFileMode` returns nil on Windows before it stats anything.

## Impact

The `node-token` is a credential that never expires and that authorizes every
operation on that Node. On Windows it is readable by every local account, and
nothing in the Node detects or reports it. The documented mitigation does not
exist, so an operator reading the document believes a protection is in place that
is not.

## Root cause

Two separate causes, and both must be addressed:

1. **No ACL code exists.** `SaveIdentity` and `resolveConfigDir` rely on POSIX
   permission bits. On Windows `syscall.Chmod` only toggles
   `FILE_ATTRIBUTE_READONLY`; it never writes a security descriptor. `os.MkdirAll`
   ignores its perm argument on Windows entirely.
2. **The documentation describes an intention, not the implementation.** The
   sentence "an owner-only ACL on Windows" was written as part of the design and
   never checked against the code.

## Detection failure

`checkIdentityFileMode` deliberately returns nil on Windows, with a comment
explaining that the permission bits Go reports are synthesised and carry no
ownership information. That reasoning is correct, but it was treated as the end of
the matter: the check was disabled and no replacement was written, and no test
asserted what protection the file actually has on Windows. The POSIX test
`TestSaveIdentityWritesOwnerOnlyFile` skips on Windows, so the gap is invisible in
a green run.

## Fix

Choose one, and make the documents match:

- **Set a real ACL.** Create the file with a security descriptor granting access to
  the creating user only, which needs `golang.org/x/sys/windows` and is the only
  option that actually protects the credential. This adds the project's second
  third-party dependency, so it needs a decision.
- **State the truth.** Correct `docs/Environment_Variables.md` to say that on
  Windows the file relies on the default ACL of the config directory, that this
  grants access to the local account and to administrators, and that the operator
  must place the config directory somewhere with a restrictive ACL if that is not
  acceptable.

Either way, a test must assert the actual protection on Windows rather than skip,
and the two sentences in `docs/Environment_Variables.md` must be corrected.

## Decision

Deferred by the human on 2026-11-11: this is a file-permission problem and is not
being fixed now. The issue stays open as a record rather than being closed, because
the documentation still claims a protection the code does not provide.

Two things must not be lost while it is deferred:

- `docs/Environment_Variables.md` states at lines 77, 153 and 157 that the identity
  file and the config directory are protected by "an owner-only ACL on Windows".
  No ACL code exists. The claim is false on a supported platform, which is worse
  than the missing feature, because an operator reads it and believes the token is
  protected.
- The exposure is real: the identity file holds a `node-token` that never expires,
  and on Windows it is readable by every local account.

When this is picked up, the choice is between implementing the ACL and correcting
the document to state the actual behaviour and its consequence. Correcting the
document is the smaller change and is required either way.
