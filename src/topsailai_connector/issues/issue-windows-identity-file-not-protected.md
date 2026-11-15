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
the ACL implementation is still missing.

The issue named two things that must not be lost while it is deferred. One is now
done and one is not:

- **Done: the false documentation claim is corrected.** `docs/Environment_Variables.md`
  no longer says the identity file is protected by "an owner-only ACL on Windows".
  It now states that no ACL is set, that `os.MkdirAll` and `os.Chmod` cannot write a
  security descriptor, that the inherited descriptor grants `BUILTIN\Users` read
  access, that `checkIdentityFileMode` cannot detect this, and that the operator must
  choose a restrictive parent directory. The measured `Get-Acl` output is quoted in
  the document, so the claim is a measurement rather than an intention. The same
  correction was applied to `docs/cases/TestCase_node-id-pair.md` (TC-PAIR-19 and
  TC-PAIR-20) and `docs/cases/TestCase_policy-and-scope.md` (TC-POL-50), which
  asserted the non-existent ACL.
- **Not done: the exposure is unchanged.** The identity file still holds a
  `node-token` that never expires, and on Windows it is still readable by every local
  account. Correcting the document tells the operator the truth; it does not protect
  the credential.

The remaining choice is unchanged and still needs a decision, because it adds the
project's second third-party dependency:

- **Set a real ACL.** Create the file with a security descriptor granting access to
  the creating user only. `syscall` on Windows exposes the SID helpers but no
  `SetNamedSecurityInfo`, `InitializeAcl` or `SetSecurityDescriptorDacl`, so this
  needs `golang.org/x/sys/windows` or a hand-written `advapi32` binding through
  `LazyDLL`. Neither is a change to make without approval.
- **Leave it as documented.** The operator owns the parent directory's ACL. This is
  the current state and is now stated honestly.

Either way, a test must assert the actual protection on Windows rather than skip.
`TestSaveIdentityWritesOwnerOnlyFile` still skips there, so the gap remains invisible
in a green run.

## Documentation correction

Applied on 2026-11-13. The three false claims were replaced with the measured
behaviour, and a `#### Windows file protection` subsection was added to
`docs/Environment_Variables.md` so the consequence is stated where an operator
configures the Node rather than only in this issue.

The correction was verified against a real Windows host rather than inferred:
`connector-node.exe` built for `GOOS=windows` was run with a fresh config directory,
and `Get-Acl` on the resulting identity file reported
`BUILTIN\Users Allow ReadAndExecute, Synchronize`. The document now quotes that
output.

## Live confirmation on a real Windows host

Measured on Windows Server 2022 (10.0.20348.587) with `connector-node.exe` built
from `cmd/connector-node` at commit `b544bc19`. The identity file was created by
the real code path, then its security descriptor was read with `Get-Acl`:

```
Path   : C:\connector\config\identity
Owner  : BUILTIN\Administrators
Group  : i-rxrgnhw9\None
Access : NT AUTHORITY\SYSTEM Allow  FullControl
         BUILTIN\Administrators Allow  FullControl
         BUILTIN\Users Allow  ReadAndExecute, Synchronize
Sddl   : O:BAG:S-1-5-21-...-513D:AI(A;ID;FA;;;SY)(A;ID;FA;;;BA)(A;ID;0x1200a9;;;BU)
```

`BUILTIN\Users Allow ReadAndExecute` is the finding: every local account can read
the file that holds the `node-token`. The descriptor is the inherited default of
the parent directory, which is what the code produces when it never sets one.

The config directory shows the same shape, with `BUILTIN\Users` granted
`ReadAndExecute`, `AppendData` and `CreateFiles`:

```
NT AUTHORITY\SYSTEM        FullControl
BUILTIN\Administrators     FullControl
BUILTIN\Users              ReadAndExecute, Synchronize
BUILTIN\Users              AppendData
BUILTIN\Users              CreateFiles
CREATOR OWNER              268435456
```

This confirms the code-reading conclusion with a measurement rather than an
inference: no ACL is set, and the effective protection is the inherited default.
