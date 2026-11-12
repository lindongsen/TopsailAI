---
maintainer: AI
author: DawsonLin
---
# File command path escape is clamped but documented as rejected

`docs/DESIGN.md` §20.2 and the earlier `skills/topsailai-data/SKILL.md` both
state that a path escaping the object folder, such as `../outside.md`, is
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

The skill documentation was corrected to describe the clamp. `docs/DESIGN.md`
§20.2 still states that escaping paths are rejected and needs the same
correction, or the implementation needs to reject instead of clamp. Choose one
and make the code and both documents agree.
