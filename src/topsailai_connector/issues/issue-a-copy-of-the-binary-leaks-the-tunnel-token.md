---
maintainer: AI
author: DawsonLin
status: open
severity: critical
created: 2026-11-20
---

# A copy of the binary leaks the node secret and the Server-wide tunnel token

## Symptom

A build that carries the `tunnel_token` adds its own executable to the deny list, so
the **running** file is refused. A **copy** of that file is a different inode, so it
is not refused, and a caller with a valid node credential reads the copy in full.
The copy contains the embedded `tunnel_token` and the embedded node credential in
plain text.

Measured on the Windows host, scope `desk` covering
`C:\Users\Administrator\Desktop`, with the packaged binary
`connector-node-desk.exe` running as PID 792 and a byte-identical copy
`desk-copy.exe` beside it:

```
file.read  connector-node-desk.exe   (the running file)
  -> rc=1  denied: the node refused the operation

file.read  desk-copy.exe             (a copy of the same bytes)
  -> rc=0  262144 bytes returned
```

The first 256 KiB of the copy does not contain the secrets, because the linker
places them near offset 4.28 MB. Reading that region through the CLI recovers them:

```
file.read  desk-copy.exe --offset 4285000 --length 1200
  -> rc=0, 1200 bytes
     tunnel_token present: 1 occurrence

file.read  desk-copy.exe --offset 4287000 --length 1200
  -> rc=0, 1200 bytes
     node secret present: 1 occurrence
```

Both secrets were recovered from the Linux build host, over the network, using only
a node credential. The offsets were located in the local artifact with
`grep -abo`, and the same bytes were then read back through the fence, so the
recovery is a remote read rather than a local inspection.

The artifact used for this measurement is
`bin/connector-node-windows-amd64.exe`, sha256
`79b297b164113d9448d02b520b538210abf02b32d96a0ed9dff5bbe343ac48c1`.

## Why this happens

The deny list answers by **file identity**, and a copy is a different file. The
three rules in `docs/permission-design.md` each miss it:

| Rule | Question it answers | Sees a copy? |
|---|---|---|
| Written-path prefix | Does the written path start with a denied directory? | No, the copy is at an unrelated path |
| File identity | Is the opened object the same inode as a denied file? | **No, a copy is a different inode** |
| Ancestor identity | Is any ancestor the same inode as a denied directory? | No |

The design document states the protection as:

> **A build that carries the `tunnel_token` adds its own executable to the deny
> list.** Without this, a scope that contains the binary serves it.

That sentence is true and insufficient. It protects the file, not the secret. The
document's threat model assumes the running binary is the only copy, which is not
true in operation: an operator copies the binary before an upgrade, a packaging
script leaves a `.bak` sibling, or a recipient keeps the downloaded file next to the
installed one.

## Why it was not caught

- No test creates a copy of the binary. The existing tests prove the running file is
  refused and that it is omitted from a listing, which are both correct and both
  silent about a copy.
- The design document states the executable deny entry as a complete mitigation, so
  a reviewer reads it as settled rather than as a partial one.
- The exposure is invisible from the host side. The copy looks like an ordinary
  file, and the question "does this file contain a secret" is answered by content,
  not by identity.
- The first 256 KiB of the binary contains no secret, so a casual `file.read` of a
  copy returns bytes that look harmless. The secret is 4 MB in, which is why the
  defect survived the earlier verification round.

## Consequence

This is a privilege escalation from one node credential to every Node on the Server.

```
one valid node credential (per caller, revocable on the Node)
  -> file.read on a copy of the binary inside any scope
  -> the copy's bytes contain the embedded tunnel_token
  -> tunnel_token is Server-wide: "the blast radius is every Node"
  -> open a channel and impersonate any Node on that Server
```

`docs/permission-design.md` states the blast radius of a leaked `tunnel_token`
explicitly: "Anyone holding it can open a channel and impersonate a Node ... the
blast radius is every Node". The node credential is supposed to be revocable on one
Node without Server involvement. This defect makes it a Server-wide credential
instead, which is the separation the whole design rests on.

The escalation needs two conditions, and both are ordinary:

1. The build carries the `tunnel_token`, which is the default for `make package`
   because "start it and it works" requires it.
2. A copy of the binary sits inside a scope. A whole-volume scope such as `C:\`
   contains every copy on the machine.

## Options

| Option | Effect | Cost |
|---|---|---|
| Hash the running binary at startup and refuse any file whose content hash matches | Closes the copy route wherever the copy sits | Hashes every read target, so a large file costs a full read before the refusal; a read of a 1 GB file becomes a 1 GB hash |
| Refuse any file whose size equals the running binary's size | Cheap, catches a byte-identical copy | Over-refuses legitimate same-size files; a padded copy defeats it |
| Refuse by name pattern such as `connector-node*` | Cheap | Over-refuses; a renamed copy defeats it |
| Do not embed the `tunnel_token`; require it from the environment | Removes the Server-wide secret from the artifact entirely | Breaks "start it and it works", which is the purpose of the embedded mode |
| Accept and document | No code change | One node credential escalates to every Node |

The first option is the only one that closes the route rather than narrowing it, and
its cost is a hash on every read. The fourth option is the only one that removes the
secret rather than protecting it, and it trades away the feature the embedded mode
exists for.

No option is obviously right, which is why this is recorded rather than fixed. The
choice trades a per-request cost against a Server-wide blast radius, and that is a
security decision for the human.

## Verification required

- A test that copies the binary inside a scope and asserts the chosen behaviour, so
  the answer is measured rather than assumed.
- If a content-hash rule is chosen, a test that a legitimate file of the same size
  is still readable, so the over-refusal is bounded.
- If the `tunnel_token` is removed from the artifact, a test that a build without it
  still serves its own install directory, because the deny entry is conditional on
  the secret being present.
- The skill must state the hazard next to the packaging instruction, because the
  operator who builds the bundle is the one who can avoid it.
