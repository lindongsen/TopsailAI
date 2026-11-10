---
maintainer: AI
author: DawsonLin
---

# Node Authority

## What an operator sees

The Node decides what may be served. Its policy file names the scopes it exposes
and the permissions granted on each one. A request that names a scope the policy
does not define, or asks for a permission the policy does not grant, is refused
by the Node.

The Server cannot widen this. It has no scope table and no permission table, so
it cannot answer "may this caller do this" and does not try. Changing the Server
configuration never expands what a Node serves.

## Behaviour

- A scope is a name, never a path. A name containing a path separator is
  refused, because it would let a caller address a directory the policy never
  named.
- A permission is an action inside a scope: `read`, `list`, `stat`, `write`,
  `exec`. The first version implements the first three.
- A grant is one scope plus the permissions allowed on it. A grant naming a scope
  the policy does not define is a startup failure, because it is a permission
  nobody can use and a mistake nobody would notice.
- No permission implies another. `read` does not imply `list`, `list` does not
  imply `read`, and `stat` does not imply `read`. Each one is granted or it is
  not.
- A permission granted on one scope does not apply to another, even when both
  scopes map to the same directory.
- An operation with no matching grant is refused. An empty policy refuses
  everything. A missing policy file is a startup failure, not an implicit allow.
- A refusal does not say whether the scope exists. The difference between "no
  such scope" and "no permission on that scope" is a scope-name oracle, so both
  answer the same way.
- The policy is reloaded on `SIGHUP`. A grant that is removed stops working
  immediately, because a delay is a window of permission nobody granted.
- A reload that fails leaves the previous policy in force and logs the failure.
  A failed reload must not leave the Node serving nothing, and must not leave it
  serving something the operator did not write.

## Why the Node is the only authority

The Node is the only party that knows what it is exposing. The Server is a pipe:
it forwards a request and returns the answer. If the Server could grant, then
compromising the Server would grant everything, and the separation between the
channel authority and the operation authority would collapse into one authority.

## What this feature does not do

- It does not implement `write` or `exec`. Both are declared so a policy naming
  them is refused at startup rather than silently ignored, but neither is
  dispatchable in the first version.
- It does not sandbox a command. `exec` is excluded from the first version
  because a command allowlist is not a sandbox: `find -exec`, `git -c
  core.pager=...`, `tar --to-command` and `less` shell escapes all reach an
  interpreter through a program that looks harmless.
