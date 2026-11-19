---
maintainer: AI
author: DawsonLin
status: open
created: 2026-11-20
---

# A copy of the config directory is served, including a live credential

## Symptom

The deny list refuses the Node's own config directory by identity, so the real
directory and everything inside it are refused. A **copy** of that directory is a
different inode, so it is not refused, and a caller with a valid node credential
reads the copy in full.

Measured on the Windows host with the drive-root Node, scope `c` covering `C:\`:

```
file.list  Users/Administrator/AppData/Roaming
  -> topsailai-connector.bak-bearer-20261111   dir   0
     (the real topsailai-connector is correctly omitted)

file.list  Users/Administrator/AppData/Roaming/topsailai-connector.bak-bearer-20261111
  -> identity   file   85

file.read  Users/Administrator/AppData/Roaming/topsailai-connector.bak-bearer-20261111/identity
  -> node_3var5wpfhv5w7h7xsw7hdnhffi.wo42vslxitw3472xjvo5vegyvk4mwp3elddiqcit3m3jbhxvo5ca
  rc=0
```

That particular copy held a pre-HMAC bearer credential, which is dead: using it
returns `unauthenticated`. The exposure is therefore not a live leak today, but the
mechanism is not limited to that copy.

Confirmed by copying the **live** `credentials.yaml` into the backup directory and
reading it back through the fence:

```
file.read  .../topsailai-connector.bak-bearer-20261111/credentials.yaml
  -> version: 1
     credentials:
         - key_id: key_ncofi1iiwzmd-vphaz4xuq
           secret: 9FakrYd6-B1UFcAGNDvs6N-nYUyTuUUNuVtPMPNWcik
  rc=0
```

That secret is the one the operator is using, and it never expires. The copy was
removed after the measurement.

## Why this happens

The deny list answers by identity, not by name, and that is deliberate: a name-based
rule would make a whole-volume scope useless, because every directory called
`config` would become unreachable. `docs/permission-design.md` states the
consequence explicitly:

> **A directory that merely looks like the config directory stays readable.** The
> rule answers by identity, so a `config` directory at another path, a sibling
> named `config-backup`, and a look-alike nested inside a look-alike are all
> readable.

The design reasoning is sound for a look-alike that holds nothing. It does not cover
the case that actually occurs in operation: an operator copies the config directory
before an upgrade, or a packaging script leaves a `.bak-<date>` sibling, and the copy
holds a real credential. The rule then protects the original and serves the copy.

## Why it was not caught

- No test creates a copy of the config directory. The existing tests prove the real
  directory is refused and that a look-alike holding nothing is readable, which are
  both correct and both silent about a look-alike holding a credential.
- The design document states the look-alike behaviour as a deliberate consequence,
  so a reviewer reads it as settled rather than as a hazard.
- The skill does not mention backups at all: `grep -i backup
  skills/connector-node-setup/SKILL.md` returns nothing, so an operator who makes a
  backup is not told that the backup becomes remotely readable.
- The exposure is invisible from the host side. The file looks correctly protected
  by its own ACL, and the question "can a remote caller read this" is answered by a
  different mechanism.

## Consequence

A caller holding a valid node credential reads any copy of the config directory that
sits inside a scope. On a whole-volume scope such as `C:\`, that includes every
backup an operator or a packaging script has ever left behind. The secret never
expires, so a copy made months ago is as good as the current one.

The blast radius is one Node per leaked credential, which is the same radius as the
`credentials.yaml` ACL gap on Windows
(`issues/issue-windows-identity-file-not-protected.md`). The two defects compound:
the ACL gap lets a local account read the file, and this one lets a remote caller
read a copy.

## Options

| Option | Effect | Cost |
|---|---|---|
| Document the hazard in the skill and the design document | An operator learns not to leave a copy inside a scope | No code change; relies on the operator |
| Deny by name as well as by identity, for the config directory's own basename | Refuses `topsailai-connector.bak-*` and any sibling sharing the prefix | Over-refuses a legitimate sibling, which is the failure the identity rule exists to avoid |
| Deny a directory whose contents match the config directory's contents | Refuses a copy wherever it sits | A content comparison on every listing is expensive and can be defeated by changing one byte |
| Refuse a scope that contains any file named `credentials.yaml` outside the config directory | Closes the specific file | A name-based rule again, and the next secret file has a different name |

No option is obviously right, which is why this is recorded rather than fixed. The
first option is the only one with no false refusal, and it is a documentation change.

## Verification required

- A test that copies the config directory inside a scope and asserts the documented
  behaviour, whichever option is chosen, so the answer is measured rather than
  assumed.
- If a name-based rule is chosen, a test that a legitimate sibling such as
  `config-backup` holding nothing is still readable, so the over-refusal is bounded.
- The skill must state the hazard next to the backup instruction, because the
  operator who makes the backup is the one who can avoid it.
