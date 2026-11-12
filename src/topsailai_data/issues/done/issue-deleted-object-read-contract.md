---
maintainer: AI
author: DawsonLin
---
# Deleted objects are documented as readable but reads are refused

`docs/DESIGN.md` section 7.11 states that a `deleted` object allows
`Read Actual: Yes`, and the surrounding prose says "`deleted` objects retain
metadata and actual data. `Read` is allowed". The implementation refuses every
actual-data read unless the object is `active`.

## Observed behaviour

```
bin/topsailai-data delete demo
deleted object demo

bin/topsailai-data get demo demo.md
error: get: object not found: demo
```

The exit status is `1` and the payload is still present on disk, so the object
is not actually missing. The message reports a missing object rather than a
lifecycle restriction.

## Root cause

`pkg/manager/manager.go` routes both `ReadActualFile` and `ReadActualArchive`
through `readActiveObject`, which calls `requireActive`:

```
pkg/manager/custody.go:54    obj, err := m.requireActive(ctx, id)
```

`requireActive` rejects any status other than `active`, so a `deleted` object
cannot be read even though its payload is intact.

## Impact

- The documented recovery story is broken. A user who soft-deletes an object
  and then wants to inspect it before deciding to recover cannot read it,
  although the design promises that read is allowed.
- The error message is misleading. `object not found` suggests the object is
  gone, so a caller may conclude the delete was destructive when the payload is
  still there.
- `show` behaves differently from `get`: `show` resolves any status and prints
  metadata, while `get` refuses. The two commands disagree about whether a
  `deleted` object exists.

## Resolution

Resolved by correcting the documentation; the implementation was left unchanged.

- `docs/DESIGN.md` section 7.11 now records `Read Actual: No` for `deleted`
  objects, and the prose states that actual-data reads are refused because reads
  require `active` status, and that `recover` restores readability.
- `skills/topsailai-data/SKILL.md` now explains that the omitted actual-data
  sections are caused by the `active`-only read rule, so `get` and `get-archive`
  fail for a `deleted` object even when its payload is intact.

The misleading `object not found` message is still returned for a non-`active`
object. It is documented as a lifecycle restriction, but a future change that
names the status in the error would be an improvement rather than a contract
change.
