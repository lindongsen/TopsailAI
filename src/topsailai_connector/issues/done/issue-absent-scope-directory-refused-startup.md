---
maintainer: AI
author: DawsonLin
status: done
created: 2026-11-16
---

# A scope directory that does not exist is tolerated instead of refused

## Symptom

A policy naming a directory that did not exist refused startup with exit code 1.
On Windows the same happened for a drive letter with no volume behind it, such as
`E:\` or `F:\`.

## Why it was wrong

A policy is written before the machine is ready. A directory may not have been
created yet, and a drive letter may have no volume mounted yet, so one absent
directory stopped a Node that served several. The operator had to create every
directory before the Node could start, which made a policy unusable on a machine
that was still being provisioned.

## Change

`validateScopeMapping` now returns `(absent bool, err error)`. An `os.ErrNotExist`
from `os.Lstat` returns `(true, nil)` instead of an error. `openScope` then returns
a `Scope` with no handle and `absent` set, and `Read`, `List` and `Stat` answer
`not_found` for every path on it.

Every other mapping rule is unchanged and still fatal: a relative path, a symlink
root, a file root, the home directory, a mount point, an existing filesystem root
and an existing config overlap.

## Why the remaining rules are skipped for an absent path

Each skip is an argument rather than a convenience. A path that does not exist is
not a symlink, is not a mount point and is not the home directory, because all
three exist. It cannot overlap the config directory either, because the config
directory is written before the authority is loaded and therefore exists.

The filesystem-root rule is skipped because a volume with no volume behind it has
no blast radius. That skip is fail-closed across restarts: when the volume appears,
the next startup sees a real filesystem root and refuses it unless the policy
states `allow_filesystem_root: true`. Measured on Windows with `subst E:`, an
absent `E:\` started, and after the volume was created the next startup refused
with `path "E:\\" is a filesystem root`.

## Why not skip the scope, and why not open it lazily

A skipped scope makes the operator believe a grant exists that does not, which is
the failure `authority.go` already refuses for a partially loaded policy. A lazy
open would move a startup decision to request time and would need a second
validation path, so the fence could be configured differently depending on when
the directory appeared.

## Why `not_found` rather than `denied`

The grant exists and the directory does not. `denied` would send the operator
looking for a policy problem that is not there. It leaks nothing, because every
path on an absent scope answers the same way, including the root, and a caller
without the grant still receives `denied` because the grant is checked first.

## Tests

The tests the new rule invalidated were inverted rather than deleted, and the two
that used a missing directory to prove a different property were re-pointed at a
regular file, because that property was handle cleanup on the failure path and a
file root still fails.

Mutation testing confirmed the tests are not vacuous: restoring the startup refusal
failed all five tolerance tests, and answering `denied` instead of `not_found`
failed all four code-assertion tests.

## Live verification

Linux: three absent scopes started, all three operations answered `not_found`, the
process stayed alive. A mixed policy served the present scope and refused the
absent one. A directory created after startup was not adopted until the restart,
which then served it.

Windows (`administrator@192.168.2.6`, only `C:` present): a policy naming `E:\`,
`F:\` and an absent `C:\` subdirectory started, all three operations answered
`not_found`, and the process stayed alive. Existing `C:\` remained fatal, which is
the contrast the tolerance must preserve.

## Documents updated

`docs/permission-design.md` (scope mapping rule, a new section on an absent scope,
and five enforcement checklist items), `docs/cases/TestCase_policy-and-scope.md`
(TC-POL-12), `docs/cases/AdversarialCase_path-fence.md` (AC-PATH-51), and
`tests/bdd/features/policy-startup.feature`.
