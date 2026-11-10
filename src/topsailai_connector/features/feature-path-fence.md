---
maintainer: AI
author: DawsonLin
---

# Path Fence

## What an operator sees

A scope is a name the policy maps to a local directory. A request names a scope
and a relative path inside it. The Node resolves the path inside the scope root
and refuses anything that would land outside it, so a caller can read the files
the policy exposes and nothing else.

The fence is enforced by the operating system, not by comparing strings. A
request for `../outside/secret.txt` is refused because the kernel refuses to
resolve it, not because the Node noticed the two dots.

## Behaviour

- A path must be relative. An absolute path is refused, because it would let a
  caller address a location the policy never named.
- A path must not contain `..`, `.`, an empty component, a backslash, a colon, a
  NUL byte or a control character. The grammar is a whitelist, so a separator
  spelling nobody thought of is refused rather than accepted.
- A path must not end in a dot or a space, and must not begin with a space.
  Windows silently strips those, so a name that looks distinct would resolve to
  a different file.
- A path must not name a reserved device (`CON`, `NUL`, `COM1`, `LPT1` and the
  rest). Those are not files, and reading one is not a file read.
- A symlink is reported as a link and never followed. Following one would make
  the fence's proof depend on the state of the filesystem at request time.
- A scope root must be an absolute, real directory. A symlink, a file, a
  filesystem root, the home directory and a mount point are all refused at
  startup, because each one has a blast radius nobody measured.
- A scope whose root is inside the Node's config directory, or which contains
  it, is refused, because that directory holds the identity file.
- The Node's own identity file and policy file are refused by identity, not by
  name, so a symlink or a different spelling cannot rename them into reach.
- A read is capped at 256 KiB. A larger file is refused rather than truncated,
  because a truncated read looks like a complete one.
- A fifo, a socket and a device file are refused. A fifo blocks forever and a
  device file never ends, so both are a denial of service rather than a read.

## Why the fence is the whole risk

The first version is read-only, so it cannot corrupt data. The only thing it can
do wrong is hand out a file it should not, and every such mistake is a fence
mistake. That is why the fence is the component with the most adversarial tests
and the one that must be right before anything else is built.

## What this feature does not do

- It does not stop a hard link. A hard link is not an escape: the inode is
  genuinely inside the scope, and only someone who already has write access to
  the scope can create one.
- It does not stop a mount point created after startup. A bind mount inside a
  scope is readable through the fence. The startup check refuses a scope that is
  itself a mount point, which is the case an operator can be warned about.
- It does not protect against a compromised host. If the host is compromised the
  fence is gone entirely, and nothing in this design helps.
