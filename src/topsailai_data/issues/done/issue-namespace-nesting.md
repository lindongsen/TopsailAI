---
maintainer: AI
author: DawsonLin
---
# Object namespace nesting

Creating a parent over a classification directory containing an existing object can invoke payload replacement over the child tree. Per-object locks do not coordinate distinct IDs. Serialize manager create/move namespace changes, validate ancestors, and reject nonempty destinations before any mutation. Verify preservation with isolated tests. Runtime layout cutover remains a separate task.

## Resolution

Fixed in `c54bf09b` (guard object namespace against nested creation and moves)
and hardened in `8a8f73e9` (reject unsafe namespace lock leaves).

- **Serialized namespace changes.** `local.AcquireNamespaceLock` gates every
  namespace mutation. `publishCreatedObject` holds it across boundary
  reservation, record publication, and payload write; `lockLifecycleObject`
  holds it across `MoveObject` and the lifecycle operations. Lock order is
  namespace then object.
- **Ancestor validation.** `checkNamespaceAncestor` refuses a symlink, a
  non-directory, or an object boundary (`metadata.json` or the same-named
  `.md`) anywhere in the destination path, so a create or move can never land
  inside another object's payload.
- **Nonempty destination rejected before mutation.** `CheckNamespaceDestination`
  inspects the destination with `Readdirnames(1)` and returns
  `ErrObjectExists` when it holds any entry. It runs before `os.MkdirAll` in
  creation and before `actual.Move` in relocation, so no payload is replaced.
- **Preservation tests.** `TestNamespaceCreateParentPreservesChild` proves a
  child's bytes are unchanged after a rejected parent create;
  `TestNamespaceRejectsNestedCreateAndMove` proves both a nested create and a
  nested move fail while both boundaries survive;
  `TestNamespaceManagerContention` proves create and move honor a held
  namespace lock. `TestNamespaceDestination` and
  `TestNamespaceLockRejectsAliases` cover the destination and lock-leaf alias
  cases.

Runtime layout cutover remains a separate task, as the issue states.
