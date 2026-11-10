---
maintainer: AI
author: DawsonLin
status: undo
created: 2026-11-09
---

# Token validation ignores the documented 60 second leeway

## Status: obsolete

This issue was filed against the signed-token design, which the human replaced
with three shared secrets. There is no `IssuedAt`, no `ExpiresAt` and no validity
window any more, so there is no leeway to apply.

The defect was real when it was filed: the document promised a 60 second leeway and
`Token.Validate` compared `now` directly against both ends, so two hosts with
ordinary clock drift could not use the system. It is kept here rather than deleted
because the reasoning is still useful if expiry is ever reintroduced.

## What replaced it

`docs/permission-design.md` now specifies that no secret expires. Rotation is the
only revocation mechanism. The clock comparison, the leeway and the whole validity
window are gone, which removes a class of defect rather than fixing one instance of
it.

## If expiry is reintroduced

The original fix still applies: add a leeway parameter to the comparison and apply
it at both ends, as a parameter rather than a package constant so a test can set it
to zero and pin the exact boundary. The original detection failure also still
applies: the existing tests used a large margin, so a missing leeway passed them.
