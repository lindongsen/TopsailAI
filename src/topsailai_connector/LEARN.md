---
maintainer: AI
author: DawsonLin
---

# Lessons

Project-specific lessons discovered while building the Connector: root causes,
detection failures and reusable pitfalls. Cross-project lessons belong in the
AI reflection archive, not here.

## Layout

- `internal/protocol` and `internal/security` are the only packages both
  binaries import. Keep them free of IO, otherwise the Server and the Node can
  disagree about the contract while both still compile.
- `internal/` is used instead of `pkg/` so the compiler enforces the boundary:
  the Node binary cannot import server code and the Server binary cannot import
  node code.
