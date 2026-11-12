---
maintainer: AI
author: DawsonLin
---
# File command path escape is clamped but documented as rejected

`docs/DESIGN.md` section 20.2 and the earlier `skills/topsailai-data/SKILL.md`
both state that a path escaping the object folder, such as `../outside.md`, is
rejected. The implementation does not reject it: the path is silently clamped
to the object root, so `../outside.md` addresses `outside.md` inside the object
and the command succeeds.

## Observed behaviour

```
bin/topsailai-data file write ../outside.md --object verifyobj --content "clamped"
OK
bin/topsailai-data file list-dirs . --object verifyobj
.:
    - outside.md
    - verifyobj.md
```

The write exits `0` and creates `outside.md` at the object root. No error is
reported, so a caller that relies on the documented rejection cannot detect the
clamp.

## Impact

- The security property still holds: a file command cannot reach a file outside
  the object, because the clamp keeps every path inside the object root.
- The documented contract is wrong. A caller expecting an error instead gets a
  silent success at a different path, which can overwrite an unrelated file at
  the object root.

## Resolution

Resolved by correcting the documentation; the implementation was left unchanged
because the clamp already keeps every path inside the object root.

- `docs/DESIGN.md` section 20.2 now states that an escaping path is clamped
  rather than rejected, that it is normalized against the object root, and that
  the command succeeds without an error.
- `skills/topsailai-data/SKILL.md` already described the clamp and needed no
  further change.

The silent-success risk is documented rather than removed: a caller that
expected a rejection instead addresses a different file at the object root. A
future change that makes the implementation reject escaping paths must update
both documents again.
